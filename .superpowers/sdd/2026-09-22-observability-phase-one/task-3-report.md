# Task 3 실행 보고서

## 구현

- `observe --shadow-dir PATH [--production-state-path PATH]`를 추가했다.
  Discord 자격 증명, `DiscordBot`, `run_watcher`, 운영 상태 내용에 접근하지 않고
  endpoint snapshot을 즉시 기록한다.
- `DiagnosticRun`이 한 run ID로 `run_started`, `source_fetched`,
  `post_observed`, `classified`, `run_finished` JSONL 이벤트를 기록한다.
- `observations.json`은 measurement epoch, canonical event, 근거 hash 버전,
  endpoint별 최초/최종 관측, 마지막 정상 membership만 저장한다. 원문 본문, 원시 오류,
  자격 증명, 발송 자격·상태는 저장하지 않는다.
- X URL은 검증 후 `x:<id>`, 그 밖의 사건은 `provider:<provider>:<id>`로 식별한다.
  evidence hash는 본문·URL·reply/repost·source/source_kind를 포함하고 수집 시각과 HTML은
  제외한다.
- pagination partial 관측은 기록하지만 완주 전 membership을 갱신하지 않는다. 실패한
  snapshot도 이전 정상 membership을 덮어쓰지 않는다.
- index를 잠근 뒤 읽고 snapshot마다 `.tmp`에 쓴 후 원자 교체한다. malformed index는
  기존 시간을 새로 만들지 않고 명시적으로 실패한다. symlink output은 검증 뒤 target을
  한 번 canonicalize해 잠금·읽기·교체 identity를 유지한다.
- `watch --require-existing-state [--metrics-path PATH]`를 추가했다. state lock은 load 전부터
  fetch/send/save 후까지 유지한다. metrics를 지정하지 않은 기존 경로는 계속
  `fetch_all_sources` seam을 사용한다.
- metrics를 지정한 watch만 snapshot 경로를 사용한다. 실제 게시물/health/recovery 전송의
  attempted/succeeded/failed를 기록한다. 진단 기록이 실패하면 안전한 degraded 문구를
  남기고 실제 전송 결과와 마지막 유효 watcher 상태 저장을 유지한다. post-send 기록 실패는
  성공한 전송을 retry 상태로 바꾸지 않는다.
- watch index는 `METRICS.with_suffix('.observations.json')`이고, runtime helper로 state,
  metrics, index와 각 temp/lock alias를 출력 전에 검증한다.
- README에 observe/watch 명령, measurement epoch, first observation 의미, 현재 high-water
  자격 정책, 304 cache·SQLite·VM 전환이 후속 범위임을 문서화했다.

## TDD 기록

### RED

```text
PYTHONPATH=src .../.venv/bin/python -m pytest tests/test_diagnostics.py -q
ERROR tests/test_diagnostics.py
ModuleNotFoundError: No module named 'help_me_tibooo.diagnostics'
```

```text
PYTHONPATH=src .../.venv/bin/python -m pytest tests/test_observe.py -q
5 failed
AttributeError: help_me_tibooo.__main__ has no attribute 'fetch_source_snapshots'
```

```text
PYTHONPATH=src .../.venv/bin/python -m pytest tests/test_cli.py -q \
  -k 'without_metrics or require_existing or metrics_uses or post_send or metrics_alias'
4 failed, 1 passed, 25 deselected
unrecognized arguments: --require-existing-state / --metrics-path
```

```text
PYTHONPATH=src .../.venv/bin/python -m pytest \
  tests/test_diagnostics.py tests/test_observe.py -q -k 'semantic or malformed_index'
2 failed, 1 passed, 12 deselected
semantic malformed index did not raise; observe emitted only generic error
```

```text
PYTHONPATH=src .../.venv/bin/python -m pytest tests/test_observe.py -q -k lock_identity
1 failed, 6 deselected
observations.json symlink was replaced, changing the next-run lock identity
```

### GREEN

```text
PYTHONPATH=src .../.venv/bin/python -m pytest \
  tests/test_diagnostics.py tests/test_observe.py tests/test_cli.py \
  tests/test_runtime.py tests/test_source_snapshots.py -q
64 passed in 0.42s
```

```text
PYTHONPATH=src .../.venv/bin/python -m pytest -q
234 passed in 1.37s
```

## 읽기 전용 live observe 증거

부모 통합 검증에서 현재 구현으로 임시 shadow 디렉터리에 두 번 실행했다.

- 두 실행 모두 종료 코드 0
- reset 21, twiscan 4, resets 53
- 공유 canonical event 76개
- version first-observed timestamp 78개가 두 번째 실행에서도 유지됨
- `source_fetched` 성공 8개
- body/token/posts 필드 없음
- 검증 뒤 임시 디렉터리 제거
- Discord 발송과 운영 상태 변경 없음

## 자체 리뷰

- observe 경로는 production state의 존재·inode alias만 검사하며 내용을 읽지 않는다.
- diagnostics JSON 직렬화 대상에 `Post.text`나 raw error가 들어가는 경로가 없는지 확인했다.
  본문은 hash 입력으로만 사용한다.
- provider_visible_at은 항상 null이며 origin time이 없을 때 observed time으로 채우지 않는다.
- 음수 origin latency는 음수 값을 유지하고 `origin_latency_valid=false`로 기록한다.
- A→B→A에서 기존 version의 first timestamp를 유지하고 last timestamp만 갱신한다.
- 실패/partial snapshot은 마지막 완전 정상 membership을 덮어쓰지 않는다.
- 성공한 Discord send 뒤 metrics logger가 실패하는 테스트에서 send 1회, 최신 state 저장,
  pending delivery 없음을 확인했다.
- default watch의 `fetch_all_sources` monkeypatch seam과 기존 callback 동작을 유지했다.
- SQLite, 304 cache, VM 배포, 후발 eligibility 정책은 추가하지 않았다.

## 남은 제약

- 이 단계의 최초 관측은 measurement epoch 이후 우리 수집기가 본 최초 시각이다.
- 기존 watcher의 high-water 자격 정책은 그대로라 후발 게시물 누락을 해결하지 않는다.
- membership overlap은 연속 완전 snapshot의 공통 ID 여부이며 rolling timeline 완전성을
  증명하지 않는다.
- 진단 sidecar는 audit 자료이며 watcher 발송 이력이나 운영 상태로 승격할 수 없다.

## 리뷰 수정 1: v1 인덱스 추가 필드 거부

리뷰에서 v1 인덱스의 필수 필드 타입은 검증하지만 알 수 없는 필드를 허용하는 문제가
확인됐다. 이 상태에서는 top/event/endpoint/version/membership 객체에 들어온 원문이나
자격 증명 필드가 다음 atomic save에서 그대로 재직렬화될 수 있었다.

### RED

```text
PYTHONPATH=src .../.venv/bin/python -m pytest tests/test_diagnostics.py -q \
  -k unknown_fields
5 failed, 9 deselected
```

top의 `body`, event의 `credentials`, endpoint의 `raw_response`, version의 `text`,
membership의 `token`을 각각 실제 인덱스 파일에 넣었을 때 모두 예외 없이 열렸다.

### GREEN

```text
PYTHONPATH=src .../.venv/bin/python -m pytest tests/test_diagnostics.py -q \
  -k unknown_fields
5 passed, 9 deselected in 0.09s

PYTHONPATH=src .../.venv/bin/python -m pytest \
  tests/test_diagnostics.py tests/test_observe.py -q
21 passed in 0.17s
```

각 고정 스키마 객체에서 허용 키 집합과 정확히 일치하는지 확인한다. map 역할인 `events`,
`endpoints`, `versions`, `endpoint_memberships`의 동적 식별 키는 유지했다. 회귀 테스트는
거부 전에 metrics가 추가되지 않고 malformed index byte가 변경되지 않는 것도 검증한다.

## 최종 리뷰 수정: 빈 membership과 뒤늦은 origin 보강

### RED

```text
PYTHONPATH=src .../.venv/bin/python -m pytest tests/test_diagnostics.py -q \
  -k 'empty_snapshot or empty_final or later_known'
2 failed, 1 passed, 14 deselected
```

- 정상 membership 뒤의 빈 complete snapshot이 마지막 성공 membership을 빈 목록으로
  덮어써, 다음 정상 snapshot과의 overlap이 `none`이 됐다.
- `created_at=None`으로 처음 관측한 canonical event가 뒤의 다른 provider에서 실제
  origin을 제공해도 `origin_at=None`으로 남았다.
- 앞 pagination 페이지의 nonempty membership 뒤 마지막 빈 페이지가 complete인 경우의
  누적 membership 테스트는 기존 구현에서도 통과했으며 수정 중 회귀 방지 조건으로
  유지했다.

### GREEN

```text
PYTHONPATH=src .../.venv/bin/python -m pytest tests/test_diagnostics.py -q \
  -k 'empty_snapshot or empty_final or later_known'
3 passed, 14 deselected in 0.11s

PYTHONPATH=src .../.venv/bin/python -m pytest \
  tests/test_diagnostics.py tests/test_observe.py -q
24 passed in 0.24s
```

빈 complete snapshot은 `outcome=empty`로 계속 기록하지만 마지막 성공 membership과 시각을
갱신하지 않는다. pagination에서 앞 페이지까지 누적한 membership이 nonempty면 마지막
페이지 자체가 비어 있어도 완전 membership으로 저장한다. canonical event의 origin은 기존
값이 `None`이고 새 관측에 실제 시각이 있을 때만 채우며, 이후 unknown 관측은 이를 지우지
않는다. event/version의 최초 관측 시각은 변경하지 않는다.
