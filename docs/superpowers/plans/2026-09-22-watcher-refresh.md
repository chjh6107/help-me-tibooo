# 티보햄 갱신·분류 개선 Implementation Plan

> 후속 설계로 일부 대체됨: 지연·후발 글 수정은 [인덱싱 지연 수정 설계](../specs/2026-09-22-indexing-latency-design.md)의 계약과 9절 순서를 우선한다. 아래 Task 4→5→6 의존관계는 실행하지 않는다. 기존 분류기를 유지한 관측·자격·outbox를 먼저 완성하고 새 분류 정책·힌트 묶음은 분리한다. migration/7일 기준/reset 중복/304 계약도 후속 설계에 맞춰 상세 구현 계획을 다시 작성해야 한다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 유료 API 없이 사용자 VM에서 수집 간격을 안정화하고, 중요 소식과 힌트를 구분하며 늦게 도착한 글을 재평가한다.

**Architecture:** 먼저 기존 Python watcher와 v4 JSON 상태를 systemd timer·영속 디스크로 이전한다. 이후 원문 관측, 분류 판정, 전송 이력을 SQLite에 분리하여 현재 high-water 기준의 누락과 재평가 불가를 해결한다. 속도 개선을 저장 계층 전체 재작성에 묶지 않는다.

**Tech Stack:** Python ≥3.12, 기존 httpx/curl_cffi/BeautifulSoup/pytest, Linux systemd, Python 표준 sqlite3.

**Spec:** [갱신·분류 설계](../specs/2026-09-22-watcher-refresh-design.md)

## Global Constraints

- 유료 X API·LLM API를 사용하지 않는다.
- 사용자가 준비하는 AWS 또는 Oracle Linux VM에서 운영한다.
- Python 3.12 이상, 기존 HTTP/파서/Discord 코드를 재사용한다.
- 운영 전환 중 발송 주체는 한 곳이다. 수집만 하는 검증 실행은 별도 상태를 쓴다.
- 최초 초기화 시 과거 글을 일괄 발송하지 않는다. 기존 상태가 분실된 운영 실행은 조용히 재초기화하지 않는다.
- 원문과 X 링크를 보존하고 멘션을 발생시키지 않는다.
- 원문→알림 2분 보장, 외부 전송 exactly-once, 미관측 글의 완전 수집을 약속하지 않는다.
- 현재 기준은 `0e9dfcaf7b073ee88a8dfe787dbef9514c6516e0`. 착수 시 최신 main 차이를 다시 확인한다.
- `source-probe`, `latest-posts` 등 기존 worktree와 미추적 문서를 덮어쓰지 않는다.
- 커밋은 변경 내용만 한국어 한 줄로 작성하고, 이미 push된 커밋은 수정하지 않는다.

---

## 진행 순서와 범위

| 순서 | 결과 | 선행 |
|---|---|---|
| 1 | 읽기 전용 shadow, 지연·coverage 계측, 운영 상태 필수 옵션 | 없음 |
| 2 | VM timer + v4 상태 이전 + 실제 24시간 실행 검수 | 1 |
| 3 | 소스별 증거 병합과 감시 범위 상태 분리 | 1; 2와 독립 검토 가능 |
| 4 | 분류 판정 함수와 평가셋, 즉시/힌트/무시 정책 | 3의 근거 형식 |
| 5 | SQLite 관측·판정 기록과 늦은 글/보강 글 재평가 | 3,4 |
| 6 | 전송 대기·힌트 묶음·재시작 회복, 최종 검수 | 5 |

1~2만으로 실행 공백을 먼저 줄인다. 3~6 완료 전에는 분류·누락 문제가 모두 해결됐다고 하지 않는다. 각 task는 독립 PR/검토 단위로 끝낸다. 날짜 추정 대신 아래 통과 조건으로 순서를 관리한다.

## 파일 책임

| 파일 | 책임 |
|---|---|
| `__main__.py` | CLI, 운영/shadow 모드 조합 |
| `diagnostics.py` 신규 | 시각·소스별 관측·실행 간격 JSONL |
| `runtime.py` 신규 | 파일 잠금과 상태 존재 조건 |
| `sources.py`, `source_transport.py` | 기존 제공자 파서/수집, 캐시·재시도 헤더 전달 |
| `classification.py` 신규 | 근거를 받는 순수 판정 함수 |
| `classifier.py` | 기존 tuple API 호환 wrapper, 전환 후 정리 |
| `storage.py` 신규 | SQLite schema, 관측·판정·delivery 트랜잭션 |
| `pipeline.py` 신규 | 관측→판정→대기 생성의 순서 |
| `delivery.py` 신규 | 대기 조회, 전송, 조각 단위 성공 기록 |
| `watcher.py`, `state.py` | 단계 A 운영 유지; 단계 B legacy 읽기·마이그레이션 |
| `discord.py` | Embed 생성·Discord HTTP 전송; 중요도 판단을 넣지 않음 |
| `deploy/systemd/*` 신규 | VM 실행 서비스·timer |
| `docs/operations/vm-runbook.md` 신규 | 설치·상태 이전·검증·rollback |

경로 표의 Python 파일은 `src/help_me_tibooo/` 아래다. 기존 `sources.py`를 별도 제공자 파일로 쪼개는 것은 3번 task에서 변경량이 커질 때만 수행한다. 추상 Provider 프레임워크나 플러그인 시스템은 만들지 않는다.

## Task 1: 관측 가능한 shadow와 안전한 운영 시작

**Files:** Modify `src/help_me_tibooo/{__main__,models,state}.py`; Create `src/help_me_tibooo/{diagnostics,runtime}.py`; Test `tests/test_cli.py`, `tests/test_runtime.py`, `tests/test_diagnostics.py`.

**Interfaces:**

- 기존 `watch --state-path PATH`는 호환 유지.
- 추가: `watch --require-existing-state --metrics-path PATH`.
- 추가: `observe --production-state-path PROD_PATH --shadow-dir SHADOW_DIR`; Discord 환경 변수 불필요. 상태와 metrics는 SHADOW_DIR 아래에만 쓴다. shadow 실행에서는 부분 전송도 실제 발송하지 않는다. 모든 쓰기 경로가 PROD_PATH와 resolve/samefile 기준으로 같으면 수집 전에 거부한다. 운영 상태는 선택적으로 읽어 비교하되 절대 쓰지 않는다.
- `exclusive_state(path: Path) -> ContextManager[None]`: load부터 최종 save까지 POSIX 잠금.
- `emit_metric(path: Path, event: dict[str, object]) -> None`: 한 줄 JSON, UTC ISO-8601, 본문/토큰/응답 전문 제외.

- [ ] 다음 회귀 검사를 먼저 추가하고 실행한다.

```python
from pathlib import Path
from help_me_tibooo.__main__ import main

def test_production_does_not_bootstrap_missing_state(tmp_path, monkeypatch):
    monkeypatch.setenv('DISCORD_BOT_TOKEN', 'test-token')
    monkeypatch.setenv('DISCORD_CHANNEL_ID', '123')
    state = tmp_path / 'missing.json'
    assert main(['watch', '--require-existing-state', '--state-path', str(state)]) != 0
    assert not state.exists()
```

동반 사례: observe에 운영 경로와 동일한 파일/심볼릭 링크/하드 링크를 지정하면 실행 전 거부; 정상 observe는 Discord transport 호출 0회, 기존 운영 state bytes 불변, 별도 shadow만 변경; 같은 state lock을 두 프로세스가 요청하면 한쪽만 진행; 깨진 JSON은 초기화하지 않음.

- [ ] `python -m pytest tests/test_cli.py tests/test_runtime.py tests/test_diagnostics.py -q`가 새 동작 부재로 실패함을 확인한다.
- [ ] 기존 `_watch` 수집·판정 부분을 공통 실행 함수로 추출하고 발송 callback을 주입한다. observe에는 기록 callback을 넣는다. 기존 `run_watcher()`와 v4 JSON 구조는 유지한다.
- [ ] 실행/소스/판정/전송 로그에 아래 최소 스키마를 적용한다. `provider_published_at`은 제공자가 명시하지 않으면 null이다.

```json
{"event":"source_fetched","run_id":"uuid","source":"twiscan","fetched_at":"2026-09-22T01:00:00Z","elapsed_ms":1200,"count":5,"head_id":"2101921202436702657","tail_id":"2099000000000000000","previous_anchor_present":false,"coverage":"unknown","provider_published_at":null}
```

`run_started`, `run_finished`, `post_observed`, `classified`, `delivery_attempted`, `delivery_succeeded`도 같은 run_id로 연결한다. `first_observed_at`은 canonical event key별 관측 로그의 최소 시각이다. shadow에는 실제 send가 없으므로 전송 SLO를 shadow 결과로 판정하지 않는다. previous anchor 부재는 unknown이며 자동으로 outage로 승격하지 않는다. raw body를 로그에 쓰지 않는다.

- [ ] 전체 기존 테스트와 새 프로세스 잠금 검사를 실행한다. 현재 193개가 baseline이다. 관측 명령 실제 실행 1회에서 Discord 호출이 없음을 확인한다.
- [ ] 커밋: `feat: 수집 관측과 운영 상태 검증 추가`.

## Task 2: VM 실행과 상태 보존 전환

**Files:** Create `deploy/systemd/help-me-tibooo.service`, `deploy/systemd/help-me-tibooo.timer`, `docs/operations/vm-runbook.md`; Modify `.github/workflows/watch.yml`, `README.md`; Test `tests/test_workflows.py`, Task 1 runtime tests.

**Interfaces:** Task 1의 CLI와 v4 전체 상태를 그대로 사용. 코드 `/opt/help-me-tibooo`, 상태 `/var/lib/help-me-tibooo`, 환경 파일 `/etc/help-me-tibooo.env`.

- [ ] 두 단계 전환을 문서화한다. 준비 PR은 Actions를 계속 운영하고 export/shadow만 지원한다. 전환 PR/설정은 VM 검증 후 Actions 발송을 끈다. 설치만으로 기존 운영이 중지되지 않게 한다.
- [ ] 아래 unit 파일을 만든다. VM의 `flock` 실행파일과 Python 3.12 경로를 설치 때 검증한다.

```ini
# help-me-tibooo.service
[Unit]
Description=Tibo news watcher
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=tibooo
Group=tibooo
WorkingDirectory=/opt/help-me-tibooo
EnvironmentFile=/etc/help-me-tibooo.env
StateDirectory=help-me-tibooo
UMask=0077
ExecStart=/opt/help-me-tibooo/.venv/bin/python -m help_me_tibooo watch --require-existing-state --state-path /var/lib/help-me-tibooo/watcher.json --metrics-path /var/lib/help-me-tibooo/metrics.jsonl
TimeoutStartSec=180
NoNewPrivileges=true
```

```ini
# help-me-tibooo.timer
[Unit]
Description=Poll Tibo news every two minutes

[Timer]
OnCalendar=*-*-* *:0/2:00
AccuracySec=1s
Persistent=true
Unit=help-me-tibooo.service

[Install]
WantedBy=timers.target
```

180초 초과는 실패로 기록하고 다음 실행에서 회복한다. 강제 종료가 보낸 메시지의 재전송 창을 만들 수 있음을 명시한다. 동일 service가 active면 새 인스턴스를 만들지 않는 systemd 동작과 Task 1 잠금을 함께 사용한다. [systemd timer 원문](https://github.com/systemd/systemd/blob/main/man/systemd.timer.xml)

- [ ] 신규 `export-state` 수동 mode를 workflow에 추가한다. 입력 `state_cache_key`는 가장 최근에 state cache save step이 성공한 watch run의 정확한 key이며 전체 job 성공 여부로 고르지 않는다. watch job이 실패했어도 더 최신 부분 전송 상태가 저장될 수 있다. Export manifest에는 source run_id/run_attempt, state version, SHA-256을 넣는다.  restore는 일치 없으면 실패, `lookup-only`가 아닌 읽기 복원 후 상태만 단기 artifact로 export한다. watch와 Discord 자격증명을 사용하지 않고 cache를 저장하지 않는다. artifact 보존 1일.
- [ ] workflow에 `vars.WATCH_RUNTIME == 'actions'` 조건을 schedule/watch 발송에 적용한다. 전환 전 변수 `actions`를 설정하고 호환을 검증한 후, 최종 전환에서 `vm`으로 바꾼다. schedule 제거 후에도 수동 watch가 VM과 동시에 전송되지 않게 같은 guard를 유지한다. test-bot은 자동 실행하지 않는다.
- [ ] VM에서 소스 smoke를 먼저 검증한다. 대상 VM이 ARM이면 curl_cffi 설치와 실제 수집까지 확인한다. 단순 pip 성공으로 적격 판정하지 않는다.
- [ ] 24시간 shadow로 source 접근·120초 timer·gap/분류 로그를 검증한다. 서버가 작아도 기존 20초 수준 작업이 맞는지 VM에서 실측한다.
- [ ] 전환 절차: Actions 신규 watch 차단 → 실행 중 watch 종료 확인 → 가장 최근 state cache save 성공 watch run의 정확한 key와 manifest export → checksum/전체 v4 load 검증 → VM 영속 디렉터리 설치 → 한 번 즉시 실행 → timer enable. shadow state는 폐기하지 않고 비교용으로만 보관하며 운영 상태로 승격하지 않는다.
- [ ] 상태 export가 없거나 cache miss면 자동 baseline하지 않는다. 기존 알림 기록과 상태 복원 가능성을 확인하고, 별도 재초기화 결정이 있어야 진행한다.
- [ ] `systemd-analyze verify`와 `systemctl list-timers`, `journalctl -u help-me-tibooo.service`를 확인한다. 24시간 p95 시작 간격 ≤150초 및 5분 초과 공백 0건, 재부팅 1회 후 state·pending 보존을 통과한다.
- [ ] 단계 A rollback은 VM timer/writer 정지→최신 JSON 백업→동일 v4를 읽는 직전 검증 바이너리 설치→현재 JSON load 검증→timer 재시작으로 고정한다. Actions로의 자동 rollback은 제공하지 않는다. 서버 자체 장애라면 백업으로 같은 VM runtime을 복구한다. 오래된 Actions cache로 다시 발송하지 않는다.
- [ ] 커밋: `feat: VM 감시 실행과 상태 이전 절차 추가`.

## Task 3: 소스 증거 보존과 범위별 상태

**Files:** Modify `src/help_me_tibooo/{sources,source_transport,models,discord}.py`; Test `tests/test_sources.py`, `tests/test_source_transport.py`, `tests/test_health_cycle.py`, `tests/test_public_resets.py`.

**Interfaces:** 기존 `SourceBatch`와 `fetch_all_sources(client)`는 watcher 호환 adapter로 유지한다. 신규 `SourceObservation(post: Post, provider: str, endpoint: str, observed_at: datetime, content_hash: str, provider_kind: str | None)`를 별도 모델로 둔다.

```python
@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    source: SourceName
    endpoint: str
    observations: tuple[SourceObservation, ...]
    fetched_at: datetime
    error: str | None
    cache_headers: dict[str, str]
    coverage: Literal['overlap', 'unknown', 'complete']
```

`fetch_source_snapshots(client: httpx.Client) -> tuple[SourceSnapshot, ...]`가 신규 canonical 수집 API다. `fetch_all_sources`는 이를 호출하고 기존 SourceBatch로 투영한다. Task 4·5 runtime은 snapshots에서 observations를 꺼내 사용한다. `merge_observations(observations: tuple[SourceObservation, ...]) -> Post`는 같은 canonical ID의 유효 원문을 선택하며 원래 observations는 별도 보존한다.

- [ ] 실제 파서 fixture로 4가지 failing case를 추가한다: JSON 정상+HTML 실패가 JSON posts를 잃음; JSON/HTML 동일 ID 본문 보강이 setdefault로 사라짐; timeline 정상+confirmed-reset 실패가 overall 정상에 가려짐; 두 endpoint가 같은 제공자여서 독립 소스처럼 집계됨.
- [ ] 다음 핵심 기대값을 고정한다.

```python
assert merged.id == json_post.id
assert merged.text == complete_html_post.text
assert {o.endpoint for o in observations} == {'/api/feed', '/tibo'}
assert health['news'] == 'available'
assert health['confirmed_resets'] == 'unavailable'
```

동일 본문에서 태그만 다르면 근거 2개를 보존한다. 긴 본문이면 무조건 신뢰하는 규칙은 금지하고 파서의 유효 원문인지 먼저 검증한다. 제공자의 `limits`는 source tag로 남기며 카테고리 정답으로 만들지 않는다.

- [ ] 코드에서 endpoint별 fetch와 merge를 분리한다. 파싱 실패/403/429/빈 응답의 오류를 endpoint별로 보존한다. 기존 byte/시간 제한은 유지한다.
- [ ] transport는 `Retry-After`, `Cache-Control`, `Age`, `ETag`, `Last-Modified` 중 실제 응답에 있는 값만 전달한다. 조건부 요청은 304일 때 이전 snapshot을 복구할 수 있는 저장 계약이 갖춰진 Task 5에서 활성화한다. 지원 여부를 추정해 활성화하지 않는다.
- [ ] 리셋 목록은 공식 pagination을 유지한다. 10페이지 상한 초과를 데이터 끝으로 오인하지 않는다. 타임라인의 backfill 미지원은 `coverage=unknown`으로 남긴다.
- [ ] 관련 테스트와 실제 읽기 전용 smoke를 수행한다. HTTP 성공·수집 범위·최근 anchor overlap을 따로 확인한다.
- [ ] 커밋: `fix: 소스 근거와 감시 범위 상태 보존`.

## Task 4: 중요도 판정과 무료 평가 체계

**Files:** Create `src/help_me_tibooo/classification.py`, `tests/fixtures/classification_gold.json`, `tests/test_classification_policy.py`, `scripts/evaluate_classification.py`; Modify `classifier.py`, `models.py`.

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ClassificationDecision:
    categories: tuple[AlertCategory, ...]
    disposition: Literal['immediate', 'digest', 'ignore']
    reasons: tuple[str, ...]
    rule_version: str
    evidence_hash: str
```

`decide(post: Post, observations: tuple[SourceObservation, ...]) -> ClassificationDecision`는 순수 함수다. 신뢰도를 수치 확률로 내보내지 않는다. 기존 `classify(post)`는 이전 watcher의 즉시 알림을 유지하는 wrapper로 두고, 새로운 정책은 Task 6 전까지 shadow에서만 비교한다.

- [ ] 실제 공개 원문 80건 이상에 id/url/text/metadata/expected disposition/categories/reason/split을 기록한다. 확정 중요 30, 힌트20, 무관30 이상; 같은 원문 중복은 제거한다. 기존 tests fixture만으로 정확도를 보고하지 않는다.
- [ ] 다음 구체 사례를 단위·gold 검증에 넣는다.

```python
assert decide(keyword_only_codex_reply, ()).disposition == 'digest'
assert decide(keynote_next_week_teaser, ()).disposition == 'digest'
assert AlertCategory.PLANS in decide(pro_subscription_pause, ()).categories
assert AlertCategory.LIMITS not in decide(smalltalk_with_limits_tag, ()).categories
assert decide(ordinary_repost, ()).disposition == 'ignore'
assert decide(confirmed_reset, ()).disposition == 'immediate'
```

fixture 변수는 gold 파일의 해당 실제 ID 레코드를 `Post`로 읽어서 구성한다. `ship` 부분문자열이 friendship 등에서 출시로 판정되는 경계도 포함한다.

- [ ] 실패를 확인한 뒤 source 태그 단독 확정과 `source_kind is None` 요금제 제한을 제거한다. 제품명·구체적인 변경/시점·원문/답글 문맥을 조합한 이유 코드를 반환한다. 예고를 확정 출시로 바꾸지 않는다.
- [ ] source의 확정 리셋 경로만 authoritative reset evidence로 사용한다. 공개 API의 scheduled/watch는 confirmed reset으로 판정하지 않는다.
- [ ] 평가 스크립트는 split별 confusion matrix, 클래스별 recall, 즉시 알림 precision, 표본 수, 틀린 ID를 출력한다. 규칙 변경 때 holdout을 반복 튜닝하지 않게 분리한다.
- [ ] `python scripts/evaluate_classification.py --fixture tests/fixtures/classification_gold.json` 실행: 목표 recall≥95%, precision≥90%에 미달하면 어떤 클래스 때문인지 보고하고 배포를 막는다. 수동 검증한 근거 없이 gold 라벨을 바꾸지 않는다.
- [ ] 24시간 shadow 비교에서 즉시→묶음 전환/새로 포착/버림 목록을 검토한다. 운영 알림 정책 변경은 Task 6에서 활성화한다.
- [ ] 커밋: `feat: 중요 소식과 힌트 판정 분리`.

## Task 5: 관측·판정 영속화와 후발 글 재평가

**Files:** Create `src/help_me_tibooo/{storage,pipeline}.py`, `tests/test_storage.py`, `tests/test_ingestion.py`, `tests/test_state_migration.py`; Modify `__main__.py`, `models.py`, `state.py`.

**Interfaces:**

- `SqliteStore(path: Path)`가 connection/transaction을 소유한다. 아래 ingest/record_decision은 이 클래스의 메서드다. global connection은 사용하지 않는다.
- `ingest(observations: tuple[SourceObservation, ...], now: datetime) -> tuple[str, ...]`: 신규·변경 event key 반환.
- `record_decision(event_key: str, decision: ClassificationDecision, now: datetime) -> None`.
- `migrate_json(source: Path, database: Path, migration_at: datetime) -> None`: 독립 migration 함수. 재실행 안전하고 원본 파일 보존. 원래 설치 시각을 추정하지 않는다. endpoint별 `baseline_completed_at`과 최초 snapshot membership을 저장한다. legacy known IDs는 자동 재전송 금지, 첫 snapshot의 legacy checkpoint 이하 unknown ID는 audit-only baseline, checkpoint 이후 ID는 기존 eligibility로 평가한다. 새 설치는 첫 snapshot 전부 baseline이다. baseline 완료 뒤 최초 관측된 일반 뉴스 ID는 원문 시각이 최근 7일 이내이면 높은 checkpoint와 무관하게 평가하고, 더 오래됐거나 시각 불명은 audit-only다. 확정 리셋은 기존 handled_reset_ids와 별도 이벤트 정책을 적용한다.
- canonical key: X ID는 `x:<id>`, 그 외 `provider:<name>:<id>`.

- [ ] 다음 실패 조건을 먼저 적는다: baseline 완료 후 ID 107 처리 뒤 처음 들어온 101도 최근 7일 원문이면 평가; 이미 본 101의 근거 해시가 바뀌면 재평가; 같은 observation 재수집은 무작업; 초기 snapshot 멤버는 baseline; migration snapshot의 checkpoint 이후 글은 기존 eligibility로 평가; legacy seen은 발송 완료로 추정하지 않되 자동 재전송 금지.

```python
assert store.ingest(first_snapshot, now=t0) == ('x:107',)
assert store.ingest(late_snapshot, now=t1) == ('x:101',)
assert store.ingest(late_snapshot, now=t2) == ()
assert store.ingest(enriched_snapshot, now=t3) == ('x:101',)
```

test fixture에서 baseline이 완료됐고 원문 시각이 최근 7일인 게시물로 만든다. 첫 snapshot의 낮은 legacy ID, 첫 snapshot의 checkpoint 이후 새 ID, baseline 뒤 등장한 낮은 ID, 7일보다 오래된 ID를 각각 검사한다. 아직 소스에 없던 ID 102를 DB가 생성하는 기대는 넣지 않는다.

- [ ] 아래 최소 schema를 구현한다. 외부 DB·ORM을 추가하지 않는다.

```sql
CREATE TABLE posts (
  event_key TEXT PRIMARY KEY, origin_at TEXT, is_baseline INTEGER NOT NULL,
  first_observed_at TEXT NOT NULL, last_observed_at TEXT NOT NULL
);
CREATE TABLE observations (
  event_key TEXT NOT NULL REFERENCES posts(event_key), provider TEXT NOT NULL,
  endpoint TEXT NOT NULL, content_hash TEXT NOT NULL, payload_json TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  UNIQUE(event_key, provider, endpoint, content_hash)
);
CREATE TABLE decisions (
  event_key TEXT NOT NULL REFERENCES posts(event_key), evidence_hash TEXT NOT NULL,
  rule_version TEXT NOT NULL, disposition TEXT NOT NULL, categories_json TEXT NOT NULL,
  reasons_json TEXT NOT NULL, decided_at TEXT NOT NULL,
  PRIMARY KEY(event_key, evidence_hash, rule_version)
);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```

`PRAGMA foreign_keys=ON`, 명시적 트랜잭션, UTC 문자열, bound SQL parameters를 사용한다. 고정 정책으로 본문·관측은 90일 보관하고 전송 중복 key는 삭제하지 않는다. 규칙 변경의 과거 재평가는 기본 audit-only, 자동 재전송은 신규/보강 근거가 생긴 미전송 항목만 허용한다.

- [ ] source snapshots의 head/tail/anchor와 endpoint별 baseline_completed_at/initial membership 관측도 metadata에 저장해 coverage 계산에 쓴다. ETag/Last-Modified가 실제 제공되면 snapshot과 함께 저장하고 304 응답을 동일 데이터의 관측 성공으로 처리한다. source history 일일 reconciliation을 별도 due time으로 수행한다.
- [ ] v4 JSON의 모든 state 필드를 `legacy_state_v4` metadata와 구조화 마이그레이션 결과로 보존한다. `alert_delivery` 조각 위치, `handled_reset_ids`, deferred/pending, outage/recovery를 roundtrip 검증한다. seen-only ID에 대해서는 `legacy_handled_unknown` 표식을 두고 자동 과거 재발송을 막는다.
- [ ] 이 task의 SQLite는 별도 DB에서 shadow로만 검증한다. 운영 JSON writer를 유지하고 SQLite sender는 켜지 않는다. Task 6의 delivery와 부분 전송 migration이 완성된 뒤에만 실제 JSON→SQLite cutover를 수행한다.
- [ ] 관련 테스트, DB 손상/마이그레이션 중단/중복 migration, `sqlite3.Connection.backup()`로 생성한 백업의 restore 검사를 수행한다. [Python 문서](https://docs.python.org/3.12/library/sqlite3.html)
- [ ] 커밋: `feat: 게시물 관측과 판정 이력 저장`.

## Task 6: 전송 기록과 힌트 묶음, 완료 검수

**Files:** Create `src/help_me_tibooo/delivery.py`, `tests/test_delivery_queue.py`, `tests/test_hint_digest.py`; Modify `storage.py`, `pipeline.py`, `discord.py`, `__main__.py`, `deploy/systemd/help-me-tibooo.service`, `README.md`, `docs/operations/vm-runbook.md`.

**Interfaces:**

- `SqliteStore.enqueue(event_key: str, event_kind: str, payloads: tuple[dict[str, object], ...], due_at: datetime) -> None`.
- `deliver_due(store: SqliteStore, now: datetime, send: Callable[[dict[str, object]], str]) -> int`. send는 Discord 성공 message ID를 반환한다.
- delivery uniqueness: `(event_key, destination, event_kind, part_index)`; rule_version/text hash는 포함하지 않는다.
- event_kind는 `important_news`, `confirmed_reset`, `hint_digest`다. 힌트 aggregate의 delivery event_key는 `hint:<UTC 30분 window 시작 ISO 시각>`이고 단일 X post key와 구별한다. 하나의 중요 공지는 범주가 여럿이어도 하나의 이벤트다. 뒤늦은 확정 리셋은 별도 1회 허용한다.

- [ ] 전송 대기 schema와 unique constraint를 추가한다. 필드는 payload_json/status/due_at/attempts/last_error/message_id/sent_at이며, `hint_members(digest_key,event_key)`에 unique event_key를 둔다. digest 생성·멤버 예약·payload 저장을 같은 트랜잭션에서 확정하고, 실패 시 기존 digest key/payload를 그대로 재시도한다. 마지막 조각 성공 때만 멤버를 sent 처리한다. 예약된 멤버는 다음 window에 재예약하지 않는다. delivery aggregate key는 posts 외래키로 제한하지 않고 hint_members만 posts를 참조한다.
- [ ] 관측→판정→enqueue를 한 트랜잭션에서 확정한다. HTTP 전송 중 DB 트랜잭션을 오래 잡지 않는다. 성공한 조각마다 즉시 기록한다.
- [ ] 실패 검사를 먼저 작성한다: 중복 enqueue 1회 전송; 조각 2 실패 후 조각1 재전송 없음; 실패한 글 때문에 뒤의 독립 알림이 사라지지 않음; 429 `Retry-After` 존중; 새 후보 없는 digest 미전송; 확정 공지는 digest due를 기다리지 않음.

```python
assert delivered_parts_after_retry == [0, 1, 2]
assert important_news_sent_at < next_digest_due
assert second_empty_digest_payloads == ()
```

명시적 HTTP 실패와 '서버가 받았는지 알 수 없는 timeout'은 구분해서 기록한다. timeout 직후 중복 가능성은 없다고 주장하지 않는다. 401/403은 매 2분 재폭주시키지 않고 발송 경로 장애를 기록한다. 복잡한 Discord history reconciliation은 구현하지 않는다.

- [ ] 힌트는 UTC 30분 window당 최대 1개 batch로 만들되, embed 제한 때문에 필요한 조각은 기존 분할기를 사용한다. 과거 성공 멤버를 재포함하지 않는다. 원문·링크·'예고/힌트' 구분을 보존한다.
- [ ] Task 5 migration에 보존된 legacy 부분 전송은 기존 payload/categories와 next_payload_index를 그대로 delivery에 수입한다. 전달 중이던 payload에 새 분류 정책을 적용하지 않는다. timer 정지→진행 JSON writer 종료→최신 JSON·shadow DB 백업→새 운영 DB migration→관측/분류/부분전송 roundtrip→SQLite 지원 runtime 활성화→timer 시작 순서로 전환한다. 실패 시 sender 시작 전에는 원 JSON과 이전 VM 바이너리로 돌아간다. SQLite 발송 시작 후 rollback은 최신 DB를 읽는 직전 호환 바이너리로만 한다. DB를 오래된 백업으로 되돌리는 재해복구는 중복 가능성을 별도 검증하고 조용히 시행하지 않는다.
- [ ] Task 4 새 정책을 shadow에서 운영으로 전환한다. 193개 기존 baseline 회귀 중 의미가 달라진 테스트는 새 정책의 근거를 명시해 바꾸고, 나머지는 유지한다.
- [ ] smoke, 전체 테스트, 재시작/부분전송/호스트 재부팅, 24시간 실측을 수행한다. source window 단절은 unknown으로 남는지, first_observed→sent p95≤60초가 가능한지 측정한다. 표본 0이면 미측정으로 보고한다.
- [ ] 외부 호스트 정지 감시는 선택한 AWS/Oracle 환경의 독립 모니터가 실제 연결된 경우에만 완료로 표시한다. 같은 VM의 health timer는 전체 VM 정지를 감지했다고 주장하지 않는다.
- [ ] README에 실제 운영 커밋, 실행 주기 실측, 소스별 제한, 분류 평가 표본/결과, 백업과 rollback을 기록한다.
- [ ] 커밋: `feat: 알림 전송 이력과 힌트 묶음 추가`.

## 최종 체크

- [ ] 원격 최신 코드에서 기능 테스트와 평가셋 검증 완료.
- [ ] 실제 VM에서 24시간 연속 동작, 간격/소스 접근/보관 상태 검증.
- [ ] Actions·VM 이중 발송 없음, 실제 최신 운영 상태 import 확인.
- [ ] late-arrival/enrichment/partial-delivery 사례 재현 후 해결 확인.
- [ ] 확정 중요 소식 recall·즉시 알림 precision을 split별로 공개.
- [ ] 외부 피드 지연과 자체 지연을 구분, 미측정 항목을 성공으로 표시하지 않음.
- [ ] 기록된 근거 없이 전체 뉴스 완전 수집/2분 전달/exactly-once를 주장하지 않음.
