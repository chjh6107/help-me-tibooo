# Task 1 보고서: endpoint별 snapshot 수집과 기존 adapter

## 구현 결과

- `SourceSnapshot`에 endpoint/provider, 요청·응답·관측 시각, 안전한 HTTP 메타데이터, 표현 SHA-256, 페이지와 완주 여부를 추가했다.
- `fetch_source_snapshots()`는 JSON, HTML, TwiScan, 공개 reset 페이지를 순서대로 요청하고 각 endpoint/page의 파싱 결과를 다음 요청 전에 즉시 yield한다.
- `codex-reset.com/api/feed`와 `/tibo`는 endpoint는 분리하되 같은 provider로 기록한다.
- 요청 시작 직전, bounded body 수신 완료 직후, 파싱 성공 직후에 각각 시각을 기록한다. HTTP/transport/크기/파싱 실패에는 실제 도달한 시각과 메타데이터만 남긴다.
- 완전히 읽은 본문만 SHA-256 표현 해시를 남기며 응답 헤더는 `Date`, `Age`, `Cache-Control`, `ETag`, `Last-Modified`, `Retry-After`만 snapshot에 보존한다.
- 공개 reset 페이지는 성공한 각 페이지의 관측을 보존한다. 최종 페이지까지 성공한 snapshot만 `complete=True`이며 중간 실패·cursor 반복·10페이지 상한은 incomplete failure로 끝난다.
- legacy adapter는 공개 reset 페이지가 중간 실패하면 기존처럼 partial posts를 버린 실패 batch를 반환한다. JSON/HTML은 기존 JSON 우선 same-ID 병합을 유지하면서 건강한 JSON을 HTML 실패로 덮던 결함만 수정했다.
- `fetch_timeline_sources()`는 기존 JSON/TwiScan 두 batch 계약을 유지하고 공통 bounded request/read/parse 경로를 사용한다.
- `SourceTransport`는 `User-Agent`, `Accept`, `If-None-Match`, `If-Modified-Since`만 전달한다. `Authorization`, `Cookie`, `Host`와 그 밖의 요청 헤더는 전달하지 않으며 응답 메타데이터는 유지한다.
- 조건부 GET과 표현 cache는 활성화하지 않았다.

## origin time 근거

`Post`와 watcher state 직렬화는 변경하지 않았다. Snapshot에 `origin_time_bases`를 additive metadata로 두고 파서가 실제 입력 의미만 기록한다.

- reset JSON `at`: `x_source_field`
- `/tibo`의 X snowflake 파생 시각: `x_snowflake`
- TwiScan: `unknown` (기존 `Post.created_at=None` 유지)
- 공개 reset `source.type=x_post`: `x_source_field`
- 공개 reset `source.type=observed`: X URL 유무와 관계없이 `provider_observed`

`observed` record의 `announced_at`을 X 게시 시각으로 표시하지 않는다.

## TDD 증거

RED 명령:

```text
PYTHONPATH=src /Users/jonghunchoe/Playground/help-me-tibooo/.worktrees/source-probe/.venv/bin/python -m pytest tests/test_source_snapshots.py tests/test_latest_posts.py tests/test_source_transport.py tests/test_public_resets.py -q
```

구현 전 결과: `7 failed, 30 passed in 0.22s`.

- snapshot API 부재로 5건 실패
- HTML 실패가 정상 JSON을 덮는 기존 결함으로 1건 실패
- SourceTransport가 allowlist 헤더를 전달하지 않아 1건 실패

GREEN 명령과 결과:

```text
PYTHONPATH=src /Users/jonghunchoe/Playground/help-me-tibooo/.worktrees/source-probe/.venv/bin/python -m pytest tests/test_source_snapshots.py tests/test_latest_posts.py tests/test_source_transport.py tests/test_public_resets.py -q
37 passed in 0.14s
```

기존 timeline/source 회귀 검증:

```text
PYTHONPATH=src /Users/jonghunchoe/Playground/help-me-tibooo/.worktrees/source-probe/.venv/bin/python -m pytest tests/test_sources.py -q
19 passed in 0.18s
```

부모 통합 작업에서 새 구현으로 read-only smoke를 실행했고 `exit 0`, `reset=21`, `twiscan=4`, `resets=53`으로 변경 전 baseline 표본과 같았다. SourceTransport가 allowlist의 User-Agent/Accept를 전달한 뒤에도 이 표본에서는 공개 소스 접근 회귀가 없었다.

전체 suite는 같은 worktree에 병렬 구현 중인 Task 3의 의도적 RED 테스트가 있어 부모의 통합 gate로 넘겼다.

## Self-review

- snapshot generator의 첫 `next()`가 첫 endpoint만 요청하는지 URL sequence와 실제 파싱된 ID로 검증했다.
- JSON/HTML provider identity, endpoint별 독립 시각, 안전 헤더, 표현 해시, parse failure timestamp를 검증했다.
- 공개 reset 성공 페이지 관측이 후속 페이지 실패에도 남고 legacy batch에서는 partial posts가 제거되는 양쪽 계약을 검증했다.
- JSON/HTML 양쪽 표현은 snapshot으로 보존하고 operational adapter만 기존 precedence로 합치는지 확인했다.
- 2 MiB, 15초 timeout, redirect 거부, 오류 sanitization, 실제 parser, 공개 reset 10페이지 상한을 유지했다.
- SQLite, 새 classifier, 304 cache, watcher/CLI/runtime/docs 변경은 추가하지 않았다.
- `git diff --check`를 통과했다.

## 변경 파일

- `src/help_me_tibooo/models.py`
- `src/help_me_tibooo/sources.py`
- `src/help_me_tibooo/source_transport.py`
- `tests/test_source_snapshots.py`
- `tests/test_latest_posts.py`
- `tests/test_source_transport.py`
- `.superpowers/sdd/2026-09-22-observability-phase-one/task-1-report.md`

`tests/test_public_resets.py`의 기존 페이지 2 실패 테스트가 legacy partial-page 안전성을 이미 검증하므로 수정하지 않았다.

## 남은 위험

- 실제 외부 provider의 cache/Cloudflare 동작은 표본과 시점에 따라 달라질 수 있다. 현재 read-only smoke에서는 User-Agent 전달 변경 후에도 동일 수집량을 확인했다.
- `origin_time_bases`는 snapshot 진단 metadata이며 watcher 상태나 알림 자격을 바꾸지 않는다.
