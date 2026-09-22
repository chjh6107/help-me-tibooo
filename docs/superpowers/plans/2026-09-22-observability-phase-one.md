# 수집 관측과 안전한 shadow 실행 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 실제 수집 시각·소스별 결과를 기록하고, Discord와 운영 상태를 변경하지 않는 관측 명령을 제공한다.

**Architecture:** endpoint별 snapshot iterator를 기존 SourceBatch 수집의 공통 기반으로 만들고, 진단 기록은 명시적으로 요청한 실행에만 추가한다. 기존 JSON watcher와 분류·발송 정책을 유지하며 상태 잠금·필수 상태 검사를 제공한다. SQLite 후발 처리, 캐시 재검증, pagination continuation, VM cutover는 후속 단계다.

**Tech Stack:** Python ≥3.12, 기존 httpx/curl_cffi/BeautifulSoup/pytest, 표준 pathlib/json/hashlib/fcntl.

**Spec:** [인덱싱 지연 수정 설계](../specs/2026-09-22-indexing-latency-design.md), 특히 4·5·8·9절의 첫 단계.

## Global Constraints

- 유료 X API·LLM API를 사용하지 않는다.
- Python 3.12 이상과 기존 HTTP·파서·Discord 코드를 재사용한다.
- 기존 카테고리와 즉시 알림 정책을 유지한다.
- shadow는 운영 파일과 다른 경로에 쓰고 Discord transport를 호출하지 않는다.
- 원천 최초 노출 시각이 없으면 null로 기록하고 우리 관측 시각으로 채우지 않는다.
- metrics에 원문 본문·자격증명·원시 오류/응답 전문을 기록하지 않는다.
- 기존 schedule·배포·운영 상태를 바꾸지 않는다. 테스트와 실제 읽기 전용 observe만 수행한다.
- 신규 기능은 TDD로 검증한다. Python 문법에 맞춰 기존 named def·dataclass 관례를 유지한다. JS arrow/interface 지침을 Python lambda로 번역하지 않는다.
- 내부 import는 help_me_tibooo 절대 경로를 사용한다. 커밋은 변경 내용만 한국어 제목 한 줄이다.

## 단계 범위

이 계획은 전체 수정 설계 중 첫 번째 독립 구현 단위다. 아래 세 작업을 모두 완료한다. 완료해도 후발 게시물 누락이나 Actions 실행 편차가 해결됐다고 표시하지 않는다. 후속 구현 순서는 원 설계 9절을 따른다.

## Task 1: endpoint별 snapshot 수집과 기존 adapter

**Files:** Modify `src/help_me_tibooo/models.py`, `src/help_me_tibooo/sources.py`, `src/help_me_tibooo/source_transport.py`; Create `tests/test_source_snapshots.py`; Modify `tests/test_latest_posts.py`, `tests/test_source_transport.py`, `tests/test_public_resets.py` as needed.

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    source: SourceName
    provider: str
    endpoint: str  # fixed public URL, without page cursor
    request_started_at: datetime
    response_received_at: datetime | None
    observed_at: datetime | None
    posts: tuple[Post, ...] = ()
    error: str | None = None
    http_status: int | None = None
    cache_headers: tuple[tuple[str, str], ...] = ()
    representation_hash: str | None = None
    page: int = 1
    complete: bool = True
    origin_time_bases: tuple[tuple[str, str], ...] = ()

def fetch_source_snapshots(client: httpx.Client, *, now: Callable[[], datetime] | None = None) -> Iterator[SourceSnapshot]: ...
def batches_from_snapshots(snapshots: tuple[SourceSnapshot, ...]) -> tuple[SourceBatch, ...]: ...
def fetch_all_sources(client: httpx.Client) -> tuple[SourceBatch, ...]: ...
```

The signatures above define the contract; implementation must not contain ellipsis stubs. `fetch_timeline_sources(client)` remains compatible. SourceSnapshot observations are public parsed posts; it is not an indication of notification eligibility. No state/checkpoint or Discord dependency belongs in sources.

- [x] Write failing tests for immediate yield before the next HTTP call, separately timed endpoint responses, same provider for JSON/HTML, JSON success surviving HTML failure, page-one posts retained in the iterator when page two fails, and complete only on successful final reset page.
- [x] Use real parsers with `httpx.MockTransport`. Assert IDs/timestamps/errors and request sequence, not only callback call counts. A core assertion is:

```python
iterator = fetch_source_snapshots(client, now=clock)
first = next(iterator)
assert first.endpoint == RESET_FEED_URL
assert first.posts[0].id == '201'
assert requested_urls == [RESET_FEED_URL]
```

- [x] Run `python -m pytest tests/test_source_snapshots.py tests/test_latest_posts.py tests/test_source_transport.py tests/test_public_resets.py -q`, capture the expected red result before implementation.
- [x] Share request/read/parse logic for both iterator and legacy adapters. Keep existing 2 MiB, timeout, redirect, error sanitization, parser and 10-page limits. An iterator reset failure must retain earlier snapshots; legacy adapter still returns failed reset batch with no partial posts because old watcher cannot safely initialize from partial history.
- [x] For JSON/HTML merge retain current same-ID precedence in the operational adapter, but preserve both snapshots for diagnostics. Only change the proven fallback defect: healthy JSON must survive failed HTML. Conflicting/better content selection belongs to the later pipeline, not this task.
- [x] Response timestamps: before request, after complete bounded body read, after successful parse. Transport/HTTP/parse failures retain only actually reached timestamps. `representation_hash` is SHA-256 of received bytes when complete. Headers allow only Date/Age/Cache-Control/ETag/Last-Modified/Retry-After; never arbitrary response headers.
- [x] Preserve per-post time semantics in `origin_time_bases`: JSON at/x_post announced_at → x_source_field; /tibo ID-derived → x_snowflake; observed reset announced_at → provider_observed even with an X URL; no parsed time → unknown. Do not change Post/v4 state serialization to carry diagnostic-only metadata.
- [x] Forward only User-Agent/Accept/If-None-Match/If-Modified-Since through SourceTransport, retain response metadata. Do not turn conditional GET on before persistent cached representations exist. Test rejected Authorization/Cookie/Host forwarding and permitted headers.
- [x] Run focused tests, then full suite once, self-review and commit only owned files: `feat: 소스별 수집 관측과 응답 메타데이터 추가`.

## Task 2: 운영 상태 잠금과 shadow 경로 격리

**Files:** Create `src/help_me_tibooo/runtime.py`, `tests/test_runtime.py`.

**Interfaces:**

```python
def exclusive_state(path: Path) -> ContextManager[None]: ...
def validate_shadow_paths(production_state_path: Path | None, shadow_dir: Path) -> None: ...
def validate_output_paths(protected_paths: tuple[Path, ...], output_paths: tuple[Path, ...]) -> None: ...
def require_existing_state(path: Path) -> None: ...
```

The caller holds the lock from before loading until after saving and uses the canonical state path for both operations. Lock identity must remain stable across state file atomic replacement; use a sibling lock file, resolving symlink path aliases. Reject hardlinked operational state files because distinct sibling names cannot reliably coordinate them across atomic replacements. Nonblocking contention raises a safe exception. No destructive unlink of an active lock. `require_existing_state` rejects missing/non-regular/symlink-corrupt state before fetch/send; JSON validity remains `load_state` responsibility. `validate_output_paths` rejects output/protected aliases and output/output aliases before any write, including symlinks/hardlinks; both shadow and arbitrary watch metrics use it.

- [x] Write tests using two actual processes holding the same canonical state lock, release after exception, and symlink aliases. Verify one process cannot enter until the first releases. Do not use sleeps to decide success; use subprocess handshakes/pipes.
- [x] Write tests rejecting shadow dir equal to/containing the production state, output symlink/hardlink aliases to production, and output files that already alias each other. Expected output paths are `metrics.jsonl` and `observations.json`; shadow never stores watcher state. Validate before mkdir/write/network.
- [x] Run `python -m pytest tests/test_runtime.py -q` red, implement the narrow filesystem helpers, then green. Path resolution is separate from file content loading; no credentials or network.
- [x] Commit only owned files: `feat: 감시 상태 잠금과 관측 경로 검증 추가`.

## Task 3: 관측 명령·진단 기록과 기존 watch 연동

**Files:** Create `src/help_me_tibooo/diagnostics.py`, `tests/test_diagnostics.py`, `tests/test_observe.py`; Modify `src/help_me_tibooo/__main__.py`, `tests/test_cli.py`, `README.md`.

**Consumes:** Task 1 SourceSnapshot iterator/adapter; Task 2 runtime functions. Agent must read the actual implementations before integration.

**Produces:**

```text
python -m help_me_tibooo observe --shadow-dir PATH [--production-state-path PATH]
python -m help_me_tibooo watch --state-path PATH --require-existing-state [--metrics-path PATH]
```

`observe` never instantiates DiscordBot, never invokes run_watcher, never reads/writes an operational watcher state. The optional production path exists to prohibit aliasing, not to simulate successful delivery. It collects snapshots, records safe observations/classifications, prints safe source results and returns the same news collection status exit convention as smoke. It requires no Discord environment variables.

- [x] Write CLI failing tests for no credential/no Discord call/no watcher call, production bytes unchanged including pending delivery, symlink/hardlink rejection before first network request, and repeated observe maintaining first observation.
- [x] Write real-file diagnostics tests: distinct endpoint membership, canonical ID dedup across providers, evidence hash stable despite relative-time HTML changes, history of A→B→A, earliest version/event timestamp stable, no provider_visible_at inference, overlap using full previous successful membership, failed snapshot not overwriting membership.
- [x] `observations.json` is a diagnostic-only versioned index (atomic temp→replace) with measurement epoch; event/version first and last observed times and endpoint memberships, not delivery/eligibility state. On absent index create new epoch. On malformed index fail clearly rather than inventing previous times. Lock before reading through final save. A sidecar must never be used as watcher state or migrated as sent history.
- [x] Derive canonical key from a validated X URL or provider-qualified opaque ID. Content hash includes parsed text/url/reply/repost/source_kind/confirmed source evidence; excludes timestamps/relative display/HTML. Logs contain ID, hash, category, timestamps and safe outcome only. Do not serialize raw posts into metrics/index. `origin_time_basis` distinguishes X field/X ID/provider observed/unknown, and negative latency is marked invalid rather than clamped.
- [x] Every run writes run_started/source_fetched/post_observed/classified/run_finished events under one run ID. Metrics append per snapshot immediately; store first/last observation index after each snapshot atomically. Include safe cache headers, counts/head/tail, full membership overlap, provider and source identity. Source failed/empty/pagination-partial outcomes remain visible; do not claim rolling timeline complete.
- [x] Optional watch metrics uses the same snapshot path only when enabled. Existing no-metrics watch and smoke test seam remains `fetch_all_sources`. Record actual alert attempt/success/failure and source observations, not hypothetical eligibility. Diagnostics failure after a real send must not prevent saving latest valid watcher state; use safe diagnostic error handling and distinguish degraded telemetry from successful delivery.
- [x] For watch metrics at `PATH`, its diagnostic index is `PATH.with_suffix('.observations.json')`; observe keeps the fixed `metrics.jsonl`/`observations.json` output names. Validate metrics, index, index temporary and diagnostic lock against watcher state, state temporary and watcher lock before opening any of them. Reject identical derived metrics/index names. The shared runtime path helper owns alias checks.
- [x] Watch always holds state lock across load/fetch/send/save. `--require-existing-state` checks before network; malformed JSON already fails through load_state. Metrics/index paths must be disjoint from state, its `.tmp` and lock files, and each other; path validation happens before any output write. Preserve old watcher callback behavior and failure-state save semantics.
- [x] Run focused CLI/diagnostic/runtime tests, then full suite. Document commands and limits: current high-water eligibility still applies, no 304 caching/SQLite/VM deployment yet, first observation is ours, diagnose can write only its output paths.
- [x] Run one live `observe` to a temporary shadow dir without Discord credentials, examine safe event counts/status, and delete only the temporary directory after verification or retain safe evidence in report. Public source failure is evidence, not reason to send Discord or change production credentials.
- [x] Commit: `feat: 발송 없는 관측 명령과 감시 진단 추가`.

## Final verification

- [x] Review each task for spec compliance and code quality; fix important findings with covering tests.
- [x] Whole-branch review after integration, tests pristine and no implementation outside this phase.
- [x] `python -m pytest -q`, `git diff --check`, read-only live observe. Report actual results and upstream failures honestly.
- [x] Leave the isolated branch reviewable, keep existing main/untracked design artifacts intact. No production deploy or live Discord send.

검증 결과: [수집 관측 1단계 검증 기록](../../research/2026-09-22-observability-phase-one-verification.md).
