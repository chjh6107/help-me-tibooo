# 티보햄 갱신 지연 조사

조사일: 2026-09-22 KST (실제 조회 2026-09-21 15시대 UTC).
대상: 운영 커밋 `0e9dfcaf7b073ee88a8dfe787dbef9514c6516e0`.
범위: 읽기 전용 운영 조사, 공개 소스 조회, 오프라인 재현, 설계·계획. 운영 코드/배포/Discord 발송은 변경하지 않았다.

## 결론

현재 가장 큰 지연은 처리 속도보다 **예약 실행 사이의 수시간 공백**이다. 분류기는 실제로 자동 분류하지만, 제품명 포함 여부에 많이 의존해 정보량이 적은 답글은 통과시키고 문맥이 중요한 예고는 놓친다. 성공 상태는 데이터가 제때 도착했는지까지 검증하지 않는다.

사용자 조건은 **유료 API 미사용, 사용자가 준비하는 AWS 또는 Oracle 서버 사용 가능**이다. 따라서 상시 서버에서 Python 감시기를 자주 실행하고 상태를 영속화하는 방향을 추천한다. 외부 피드의 수집 지연까지 자체 서버가 해결하지는 않는다.

## 1. 운영 실측

GitHub CLI로 `watch.yml` 실행 200개까지 요청해 전체 126개를 받았고, 이 중 예약 실행은 114개였다. 별도 REST API의 `event=schedule` 조회도 총 114개로 일치했다. 최신 운영 커밋의 예약 실행 28개를 추려 **모든 로그**를 읽었다.

| 항목 | 관측값 |
|---|---:|
| 설정 주기 | 매시 7분·37분, 30분 |
| 최신 커밋 예약 실행 표본 | 2026-09-17 07:32:18Z ~ 09-21 11:01:42Z, 28회 |
| 실행 간격 표본 | 27개 |
| 실행 간격 최소 / 중앙 / 최대 | 125.03 / 204.22 / 341.22분 |
| 실행 간격 p95 | 318.92분 (정렬 후 ceil(0.95×n)번째) |
| 실행 전체 소요 중앙 / 최대 | 20 / 54초 (`updatedAt-createdAt`, 준비·정리 포함) |
| 수집 정상 로그 | 28/28회 |
| 상태 캐시 저장 성공 로그 | 28/28회 |
| 게시물 전송 성공 로그 | 8건, 모두 `OpenAI 소식` |
| 최근 실행의 소스별 개수 | reset 26 / twiscan 5 / resets 53 |

근거: [최근 실행](https://github.com/chjh6107/help-me-tibooo/actions/runs/35591850529), [직전 실행](https://github.com/chjh6107/help-me-tibooo/actions/runs/35564231678), [고정 커밋 workflow](https://github.com/chjh6107/help-me-tibooo/blob/0e9dfcaf7b073ee88a8dfe787dbef9514c6516e0/.github/workflows/watch.yml#L3).
개별 실행 ID·시각·안전한 로그 발췌는 [증거 JSON](evidence/2026-09-22-watch-runs.json)에 보관했다. 자격증명·Discord 채널 ID·원본 전체 로그는 넣지 않았다.

### 재현 명령

저장된 관측 자료에 대해 아래 검사는 실행 주기가 설정의 두 배보다 긴지 판정한다. 조사 때 실제로 실패했다. 이는 관측 공백을 재현하는 검사이지, GitHub 내부 원인을 재현하는 테스트가 아니다.

```bash
python3 - <<'PY'
import json, statistics
from datetime import datetime
from pathlib import Path
rows = json.loads(Path('docs/research/evidence/2026-09-22-watch-runs.json').read_text())['runs']
times = sorted(datetime.fromisoformat(r['createdAt'].replace('Z', '+00:00')) for r in rows)
gaps = [(b-a).total_seconds()/60 for a,b in zip(times,times[1:])]
print(f'n={len(gaps)} median={statistics.median(gaps):.2f}m max={max(gaps):.2f}m')
assert max(gaps) <= 60, 'observed polling gap exceeds twice the configured cadence'
PY
```

결과: `n=27 median=204.22m max=341.22m`, `AssertionError`.

### 확정할 수 있는 것과 없는 것

- **확정:** 관측된 예약 실행은 30분마다 실행되지 않았다. 프로그램을 몇 초 최적화해도 이 수시간 공백은 제거되지 않는다.
- **확정:** 최신 실행은 이전 실행의 상태 캐시를 복원했고, 3개 소스가 응답했으며 1건 전송했다. 현 지연 전체를 9월 16일의 HTTP 403 문제로 설명하면 틀린다.
- **미확정:** 실행이 드문 GitHub 내부 이유. 조회 가능한 기록만으로 각각의 예정 실행이 지연·드롭됐는지 판정할 수 없다. 삭제된 과거 실행의 존재도 별도 확인하지 않았다.
- **미확정:** 제공자 최초 게시 시각. `created_at`/`announced_at`은 원문·발표 시각이고, 우리 봇에 나타난 시각과 다르다.
- **제약:** GitHub는 schedule 지연과 부하에 따른 작업 드롭 가능성을 문서화한다. 5분 cron으로 바꾸는 것만으로 정시성을 보장하지 않는다. [공식 문서](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

## 2. 실제 분류 결과

최신 커밋을 임시 디렉터리로 추출하고 기존 Python 환경으로 `fetch_all_sources`와 `classify`를 실행했다. Discord 자격증명을 사용하지 않았고 감시 상태를 쓰지 않았다. 2026-09-21 15:14:26Z 수집은 약 12초, 소스 개수 26/5/53이었다. [ID·분류 증거](evidence/2026-09-22-live-source-summary.json)

| 원문 | 현재 결과 | 문제의 의미 |
|---|---|---|
| [짧은 Codex 답글](https://x.com/thsottiaux/status/2101921202436702657), `👁️codex👁️` | OpenAI 소식, 운영에서도 전송됨 | 제품명만으로 중요 소식으로 격상된다. 힌트일 가능성은 있으므로 무조건 삭제보다 별도 후보 등급이 적합 |
| [다음 주 공개를 언급한 keynote 예고](https://x.com/thsottiaux/status/2101157729037586694) | 분류 없음 | 제품명이 없어도 업무상 의미가 있는 예고를 놓칠 수 있다. 출시 확정과는 구분해야 함 |
| [확정 리셋 기록](https://x.com/thsottiaux/status/2098685367058612394) | 리셋 | 확정 리셋 피드라는 출처 근거는 이미 활용 중 |

첫 사례의 코드가 계산한 원문 시각은 09-21 06:27:21Z, Discord 성공 로그는 11:01:58Z라 약 4시간 35분 차이다. 원문 시각은 현재 파서의 X ID 변환식을 적용한 값이며 독립적인 X API 조회 시각은 아니다. 이 값은 전체 관측 지연의 예시이고 제공자 지연과 우리 실행 대기를 분리하지 못한다.

기존 초기 명세는 '애매하면 누락 방지 우선'이었다. 따라서 넓은 통과 자체가 전부 구현 버그인 것은 아니다. 이번 개선은 **즉시 알릴 중요 소식과 근거가 약한 힌트를 분리하는 정책 조정**이다. 제품명이 없는 모든 게시물을 통과시키는 보정도 잡음을 늘리므로 채택하지 않는다.

## 3. 지연·건강 상태의 계측 공백

`SourceBatch`에는 posts/error만 있고 실제 요청·관측 시각, 지연, 커버리지, 최신성 근거가 없다. `collection_status()`는 타임라인 한 곳이 비어 있지 않으면 '수집 정상'이다. 리셋 API 실패나 다른 타임라인의 누락도 이 전체 성공값 뒤에 가려질 수 있다. [models](https://github.com/chjh6107/help-me-tibooo/blob/0e9dfcaf7b073ee88a8dfe787dbef9514c6516e0/src/help_me_tibooo/models.py#L59), [상태 판정](https://github.com/chjh6107/help-me-tibooo/blob/0e9dfcaf7b073ee88a8dfe787dbef9514c6516e0/src/help_me_tibooo/sources.py#L152)

최신 글이 오래됐다는 이유만으로 장애라 판단해서는 안 된다. 저자가 실제로 새 글을 안 썼을 수 있고, 확정 리셋은 며칠간 없을 수도 있다. `fetch 성공`, `감시 실행 간격`, `상류 최신성 unknown`, `다른 소스보다 뒤처짐`, `알림 전송 성공`을 별도 표시해야 한다.

## 4. 분석 가설과 판정

| 가설 | 예측 | 조사 결과 |
|---|---|---|
| H1 예약 공백이 주요 지연 | 처리 시간보다 실행 사이 공백이 훨씬 큼 | 지지: 중앙 204분 대 20초 |
| H2 지금도 전면 수집 차단 | 최근 소스 실패/403 다수 | 이번 28회 표본에서는 기각 |
| H3 분류기 정책이 중요도와 다름 | 짧은 제품명 답글 통과, 문맥 예고 누락 | 실제 원문으로 재현 |
| H4 캐시 손실이 지금 지연의 주원인 | cache miss/재초기화 흔적 | 이번 표본은 저장 28회 성공, 최근 복원 성공. 현재 주원인 근거 없음 |
| H5 원문·소스·전송 시각 미분리 | 상류 지연 대 자체 지연 비교 불가능 | 지지: 해당 시각 필드 부재 |

코드 감사·비교 사이트 조사·설계 토론 결과는 아래 설계와 계획에 반영했다. 외부 피드 사이트를 조사했다고 내부 크롤러나 분류 모델의 구현까지 확인한 것으로 취급하지 않는다.

## 5. 코드 감사에서 재현한 결함

오프라인 [재현 스크립트](evidence/2026-09-22-pipeline-probe.py)는 실제 `classify`, `fetch_all_sources`, `run_watcher`를 호출하고 HTTP/Discord 경계만 가짜로 대체한다. 실제 외부 발송·상태 수정이 없다. [실행 결과](evidence/2026-09-22-pipeline-probe.txt)

```bash
PYTHONPATH=src .worktrees/source-probe/.venv/bin/python docs/research/evidence/2026-09-22-pipeline-probe.py
```

해당 기존 venv가 없으면 Python 3.12 이상으로 프로젝트 의존성을 설치한 환경에서 같은 스크립트를 실행한다. probe의 짧은 문장 일부는 경계 확인용 합성 입력이며 전부 실제 게시물 인용이 아니다.

| 우선순위 | 재현 | 원인과 범위 |
|---|---|---|
| P1 | `limits_plan → ['한도']` | source_kind가 있으면 요금제 규칙을 건너뜀. upstream의 주제 태그를 사건 판정으로 오인 |
| P1 | `limits_chat → ['한도']` | source_kind=limits를 본문 증거 없이 확정 |
| P1 | `partnership → ['출시']` | `ship` 부분문자열 매칭 |
| P1 | `REENRICH [] [] 101` | 같은 ID의 본문이 보강돼도 seen/checkpoint 때문에 재평가 없음 |
| P1 | `WINDOW_GAP 103..107 / late=[]` | 늦게 처음 나타난 101,102를 높은 기준점 때문에 제외 |
| P1 | `MERGE_COLLISION None []` | JSON 우선 setdefault가 HTML의 추가 근거를 버림 |
| 전환 필수조건 | `BOOTSTRAP [] True 101` | 상태 없으면 중요 글도 첫 기준점으로만 저장. 신규 설치의 의도된 동작이지만 마이그레이션 때 위험 |

코드 근거: [분류](https://github.com/chjh6107/help-me-tibooo/blob/0e9dfcaf7b073ee88a8dfe787dbef9514c6516e0/src/help_me_tibooo/classifier.py#L53), [병합](https://github.com/chjh6107/help-me-tibooo/blob/0e9dfcaf7b073ee88a8dfe787dbef9514c6516e0/src/help_me_tibooo/sources.py#L108), [처리 완료 전진](https://github.com/chjh6107/help-me-tibooo/blob/0e9dfcaf7b073ee88a8dfe787dbef9514c6516e0/src/help_me_tibooo/watcher.py#L130), [기준점 판정](https://github.com/chjh6107/help-me-tibooo/blob/0e9dfcaf7b073ee88a8dfe787dbef9514c6516e0/src/help_me_tibooo/watcher.py#L330).

늦은 글을 버리는 경로는 재현됐지만 **실제 운영에서 특정 원문이 이 원인으로 누락됐다는 증거까지 확보한 것은 아니다.** 짧은 snapshot 창과 긴 공백이 결합하면 누락 가능성이 커진다. DB를 도입해도 외부 소스가 한 번도 제공하지 않은 글을 복구할 수는 없다.

## 6. 에이전트 회의 기록과 채택/제외

3명의 독립 에이전트가 비교 사이트, 코드 경로, 운영 설계를 나눠 조사했다. 운영 실측은 루트가 확보했고, 결과를 서로 전달한 뒤 반론과 수정안을 받아 아래 순서로 합의했다. 전원 `gpt-5.6-sol`, high reasoning을 사용했다.

| 쟁점 | 제안/반론 | 최종 계획 |
|---|---|---|
| 속도 개선 순서 | 코드 병렬화보다 실행 공백이 훨씬 큼 | P0 VM timer 이전, 내부 최적화는 측정 뒤 |
| SQLite를 먼저 도입할지 | 관측/재평가에는 필요하지만 서버 이전까지 막으면 과도함 | P0 JSON 그대로 영속 이전, P1 SQLite |
| 기존 JSON 안전성 | tmp→replace가 이미 있음. 다중 실행만 막아야 함 | 전체 v4 상태 보존·잠금·missing-state 실패 추가 |
| shadow state 승격 | '보낸 것처럼 처리한' shadow를 승격하면 누락 | 가장 최근 cache 저장이 성공한 Actions 운영 state만 이전 |
| 낮은 ID 누락 해결 | DB가 모든 gap을 복구한다는 주장은 틀림 | 후발 관측은 평가, 미관측 gap은 unknown·지원되는 backfill만 |
| 분류 방식 | 유료 LLM은 사용자 조건 위반, 로컬 LLM도 초기 과도함 | 설명 가능한 규칙과 실제 평가셋 |
| 짧은 힌트 제거 | 무조건 차단하면 리셋 힌트도 사라짐 | 중요 공지 즉시, 약한 힌트 30분 묶음 |
| upstream 태그 신뢰 | 실제 `limits`가 다른 주제에도 달림 | 출처 근거로만 사용, 본문과 함께 판정 |
| 빠른 사이트 복제 | UI 30초와 내부 수집 주기는 다름 | 공개 계약만 사용, 전체 파이프라인을 안다고 주장하지 않음 |
| 전체 호스트 장애 | 같은 호스트의 감시기는 자체 사망을 알릴 수 없음 | 실제 클라우드 선택 때 독립 모니터 연결/검증 |
| outbox의 보장 | 전송 후 상태 기록 전 crash 창은 남음 | 재시도·중복 제한, exactly-once 주장 제외 |

최종 산출물: [설계](../superpowers/specs/2026-09-22-watcher-refresh-design.md), [6단계 구현 계획](../superpowers/plans/2026-09-22-watcher-refresh.md).

설계 초안 최종 리뷰에서는 ① 실패한 job의 더 최신 pending 상태도 인계해야 한다는 점, ② shadow 경로 격리, ③ 수집 observation 반환 인터페이스, ④ SQLite 활성화는 delivery 완성 뒤로 미룰 것, ⑤ digest ID와 멤버 예약을 고정할 것을 지적받아 문서에 반영했다. rollback은 현재 상태 형식을 읽는 VM 바이너리로 제한하고, 구현되지 않은 Actions import 경로를 가정하지 않도록 수정했다.
