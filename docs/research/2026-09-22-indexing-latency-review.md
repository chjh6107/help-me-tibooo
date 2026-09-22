# 인덱싱 지연 수정 설계 토론 기록

작성일: 2026-09-22 KST.
기준: `0e9dfcaf7b073ee88a8dfe787dbef9514c6516e0`.
요청: Discord 알림의 큰 편차와 외부 인덱싱 가능성을 에이전트들과 논의한 뒤 수정 설계 작성.
결과: [수정 설계](../superpowers/specs/2026-09-22-indexing-latency-design.md). 운영 코드·배포·Discord 메시지는 변경하지 않았다.

## 검토 방법

브레인스토밍의 구조 설계 경로, systematic-debugging/diagnosing-bugs의 재현·근거 분리, dispatching-parallel-agents의 독립 검토, codebase-design의 작은 Interface, writing-plans의 의존관계·인수 조건 정리 방식을 적용했다. 이번 산출물은 설계와 구현 순서이며 상세 코드 구현 계획·구현 승인을 대신하지 않는다.

기존 연구·설계·구현 계획을 읽고 세 에이전트가 읽기 전용으로 독립 검토했다. 이후 서로 직접 반론과 계약 확인을 주고받았고, 루트가 통합안을 작성했다. 외부에 이슈·댓글·메시지를 게시하지 않았다.

| 검토자 | 모델 / reasoning | 책임 |
|---|---|---|
| `late_arrival_design` | gpt-5.6-sol / high | 후발 관측·7일 기준·baseline·legacy migration·중복 |
| `freshness_design` | gpt-5.6-sol / high | 시각의 의미·캐시/304·coverage·지연 지표 |
| `rollout_review` | gpt-5.6-sol / high | 단계 분리·실행 주기·outbox·전환·회복 |

루트는 현재 코드와 최신 Actions 기록, HTTP 캐시·Discord·systemd·SQLite 공식 문서를 확인하고 실제 watcher의 후발 누락을 다시 재현했다. 외부 제공자 내부 인덱싱은 직접 관측하지 못했으므로 원인으로 확정하지 않았다.

## 재확인한 증거

조회 명령:

```bash
gh run list --workflow watch.yml --event schedule --limit 8 \
  --json databaseId,createdAt,updatedAt,conclusion,headSha,url
PYTHONPATH=src .worktrees/source-probe/.venv/bin/python \
  docs/research/evidence/2026-09-22-pipeline-probe.py
```

최근 네 실행의 UTC 시작 시각은 `09-21 16:57:09`, `20:56:41`, `23:59:29`, `09-22 04:38:15`였다. 마지막 실행은 `04:38:43`에 완료되어 28초였다. 동일 기준 커밋이다. [최신 실행](https://github.com/chjh6107/help-me-tibooo/actions/runs/35687631087)

기존 오프라인 probe 결과:

```text
REENRICH [] [] 101
WINDOW_GAP ['103', '104', '105', '106', '107'] [] 107
MERGE_COLLISION None []
```

후발 글이 반드시 포착돼야 한다는 assertion도 실제 `run_watcher` 경로에서 실행했다. 외부 HTTP와 Discord 호출 없이 실패를 확인했다.

```python
from datetime import UTC, datetime
from help_me_tibooo.models import Post, SourceBatch, SourceCheckpoint, CheckpointPosition, WatcherState
from help_me_tibooo.watcher import run_watcher

state = WatcherState(initialized=True, source_checkpoints=(
    SourceCheckpoint('twiscan', CheckpointPosition('100')),
))
sent = []
for ids in ((103, 104, 105, 106, 107), (101, 102)):
    posts = tuple(Post(str(i), 'Codex launch', datetime(2026, 9, 22, tzinfo=UTC),
                       f'https://x.com/thsottiaux/status/{i}', 'twiscan') for i in ids)
    state = run_watcher((SourceBatch('twiscan', posts),), state,
                        lambda p, c: sent.append(p.id), lambda _: None)
assert {'101', '102'}.issubset(sent), 'late-arriving unseen posts are discarded after checkpoint 107'
```

실행 결과는 `sent=['103','104','105','106','107']`, 위 assertion에서 종료 코드 1이었다. 이 결과는 코드의 누락 가능성을 입증하며 운영에서 특정 게시물이 이 이유로 누락됐음을 입증하지는 않는다. 설계 단계이므로 해당 동작은 아직 수정되지 않았다.

## 제안·반론·채택

| 쟁점 | 반론·발견 | 최종 설계 |
|---|---|---|
| 기존 대규모 refresh 계획을 그대로 구현 | 분류기·평가셋·digest 때문에 실행·누락 수정이 늦어짐 | JSON+VM 먼저, 최소 SQLite+기존 classify+outbox 다음. 새 분류 정책은 분리 |
| JSON에 recent IDs만 추가 | 본문 버전·부분 전송·다중 대기까지 필요해지면 별도 저장 엔진이 됨 | v4 JSON은 실행기 이전에만 유지, 후발 처리의 운영 활성화는 최소 SQLite와 묶음 |
| 최초 관측=외부 인덱싱 완료 | 우리 수집 간격·CDN 캐시가 섞임 | provider 노출 시각은 명시 근거 없으면 null, 자체 관측과 다른 필드로 기록 |
| 부재→존재 사이가 인덱싱 지연 범위 | rolling window·캐시·비단조 목록에서는 성립하지 않음 | 샘플 관측 구간만 저장, 인덱싱의 확정 상·하한 주장 제외 |
| 첫 event 관측 시각 기준 7일 | 약한 A가 일찍 보이면 7일 밖의 보강 B도 자동 발송됨 | 실제 알림 근거 버전 최초 관측 시각으로 7일 평가. 이미 대기인 항목은 만료시키지 않음 |
| migration 첫 snapshot만 baseline | 500개 밖의 과거 발송 ID가 두 번째 snapshot에 나타나면 재전송 | 같은 저자/domain의 고정 legacy fence, 이력 불명 과거 항목은 계속 audit-only |
| source별 legacy fence 중 하나만 통과하면 발송 | A=200/B=100일 때 B의150은 A에서 이미 보냈을 수 있음 | 같은 X domain의 보수적 최대 fence, pending은 명시적 예외 |
| baseline 플래그 하나를 posts에 두기 | 새 endpoint baseline이 기존 endpoint 알림 자격을 덮음 | 출처별 provenance와 ID별 run 합산, 기존 자격 우선 |
| baseline 본문 보강도 모두 발송 | 실제 새 편집과 과거 본문 늦은 복원을 구분 못 해 초기 알림 폭주 | baseline-only 일반 뉴스는 보강 후도 audit-only; 신규 확정 리셋은 별도 |
| event_kind unique만으로 리셋 중복 차단 | 일반 RESET 알림 뒤 confirmed API가 오면 다시 보내게 됨 | news/reset 효과 예약과 완료 기록. NEWS-only 뒤 확정은 추가 1회 |
| 오래된 확정 리셋도 과거 watermark로 제외 | 뒤늦게 확정된 사건을 잡는 기존 기능을 다시 잃음 | 이 제안은 채택하지 않음. 초기 리셋 baseline·handled IDs·reset 효과로 중복 방지하고 이후 신규 확정 사건은 일반 7일 조건에서 제외 |
| 전송 실패 먼저 재시도 | 기존 pending 실패가 새 글 판정·상태 저장까지 막음 | 관측 저장은 발송과 독립, 전송 실패는 영속 대기 |
| 긴 Retry-After는 짧게 잘라 재시도 | 현재 10초 cap이 서버가 요구한 대기를 무시 | 실제 not_before 보존, 같은 destination/global gate. health/recovery도 공유 |
| 한 run 90초만 제한 | 느린 source 또는 대기 메시지가 다른 일을 굶김 | 수집45/전송45 예산, 소스 순환, 새/기존 알림 교대, 최대20 조각 |
| reset pagination은 매 run 처음부터 | 느린 정상 페이지에서 영원히 완주 못 할 수 있음 | generation/cursor 영속, 관측 즉시 저장, 완주 promotion만 지연 |
| 성공 메시지만 p95 계산 | 실패·미완료가 빠져 실제 나쁜 지연을 숨김 | 전체 대상·완료·미완료·최대 대기 함께 보고, 정상 조건 subset은 별도 |

## 기존 문서에서 달라진 결정

1. 일반 뉴스에 현재 최대 ID를 계속 적용하는 규칙을 폐기하되, migration 불확실성에는 **동결된** 과거 기준점을 유지한다.
2. 7일 조건의 시계를 정확한 근거 버전으로 고정하고 baseline-only의 보강 정책을 명시한다.
3. 새 classifier·digest를 저장/전송 정합성의 선행 조건에서 제거한다.
4. 일반 뉴스와 reset의 notification 효과를 구분해 기존 reset 중복 방지 동작을 보존한다.
5. 304 cache key·헤더 전달, pagination continuation, health/recovery outbox까지 같은 회복 계약에 포함한다.
6. VM cadence 검수와 SQLite 자체 처리 지연 검수를 단계별로 나눈다.

원본→Discord 지연에서 상류 인덱싱의 기여도는 여전히 미확정이다. VM에서 짧고 안정적인 수집과 시각 기록을 확보한 뒤에도 provider 내부 최초 노출 시각을 제공받지 못하면 정확한 분해는 불가능하며, 관측한 endpoint 간 차이만 보고할 수 있다.

## 통합 문서 최종 검토

rollout 검토자가 통합 문서를 다시 읽고 P1 두 건과 P2 두 건을 지적했다. 루트가 아래 계약을 보완했다.

- P1: endpoint별 관측 즉시 저장과 같은 run payload 통합의 충돌 → 수집 종료/예산 도달 barrier 뒤 ID별 판정·enqueue, crash 미판정 관측의 다음 run 병합.
- P1: migration 뒤 기존 endpoint를 신규 baseline으로 오인 → SourceName별 established 매핑, reset→두 endpoint 매핑, v1 LEGACY와 미초기화 소스 구분.
- P2: 예산 소진/429 대기/부분 pagination의 실패 집계 불명확 → 범위별 상태 전이표와 generation당 실패 1회 규칙.
- P2: 큰 multipart가 전송 예산 독점 → 다음 조각 1개 단위 선택, 순번·마지막 시도·다음 그룹 차례 영속.

이에 대응하는 A26~A29를 더해 총 29개 인수 시나리오를 정의했다. 운영 코드 수정이나 그 인수 테스트 통과를 주장하는 기록은 아니다.
