# Help Me Tibooo 구현 계획

> **에이전트 작업자 필수 하위 스킬:** 이 계획을 작업별로 구현할 때
> `superpowers:subagent-driven-development`(권장) 또는
> `superpowers:executing-plans`를 사용한다. 진행 상황은 각 단계의 체크박스로 추적한다.

**목표:** Tibo의 새 원글과 답글 중 중요한 OpenAI 소식을 약 10분마다 찾아 Discord로
중복 없이 전달하는 무료 GitHub Actions 감시기를 만든다.

**아키텍처:** Python 애플리케이션이 Codex Reset JSON 피드와 TwiScan HTML을 하나의
게시물 모델로 정규화하고, 결정론적 규칙으로 분류한 뒤 비공개 Discord 봇의 REST API로
전송한다. GitHub Actions 캐시에 최근 처리 ID와 연속 실패 상태를 보관하며, 소스별
장애 격리와 3회 연속 전체 장애 알림을 지원한다.

**기술 스택:** Python 3.12, `httpx==0.28.1`, `beautifulsoup4==4.15.0`,
`pytest==9.1.1`, GitHub Actions, Discord Bot REST API

**설계 문서:** `docs/superpowers/specs/2026-09-04-help-me-tibooo-design.md`

## 전역 제약 조건

- 저장소는 `chjh6107/help-me-tibooo`라는 이름의 공개 저장소이며 MIT 라이선스를 쓴다.
- 유료 X API와 언어 모델 API를 사용하지 않는다.
- 예약 실행 주기는 `*/10 * * * *`이며 GitHub Actions의 실제 실행은 늦어질 수 있다.
- Tibo의 원글과 답글은 포함하고 단순 리포스트는 제외한다.
- 첫 정상 실행은 기준점만 저장하고 과거 알림을 보내지 않는다.
- Discord 메시지는 멘션을 발생시키지 않으며 Bot Token을 로그나 저장소에 남기지 않는다.
- 야간 알림 억제는 이번 구현 범위에 포함하지 않는다.

## 파일 구조

- `pyproject.toml`: Python 버전, 고정된 런타임·테스트 의존성, pytest 설정
- `.gitignore`: 가상환경, Python 캐시, pytest 캐시, 로컬 상태 파일 제외
- `src/help_me_tibooo/__init__.py`: 패키지 버전
- `src/help_me_tibooo/models.py`: 게시물, 범주, 소스 결과, 감시 상태 모델
- `src/help_me_tibooo/state.py`: JSON 상태 검증·읽기·원자적 저장
- `src/help_me_tibooo/sources.py`: Codex Reset JSON과 TwiScan HTML 수집·정규화
- `src/help_me_tibooo/classifier.py`: 중요 뉴스의 결정론적 분류 규칙
- `src/help_me_tibooo/discord.py`: 안전한 Discord payload 생성과 제한 재시도
- `src/help_me_tibooo/watcher.py`: 기준점, 중복 제거, 실패 누적, 알림 순서 조율
- `src/help_me_tibooo/__main__.py`: `watch`, `test-bot`, `smoke` 명령
- `tests/fixtures/codex_reset_feed.json`: 구조화 피드 테스트 입력
- `tests/fixtures/twiscan_timeline.html`: 원글·답글·리포스트를 포함한 HTML 입력
- `tests/conftest.py`: fixture 파일 로더와 게시물 생성 테스트 fixture
- `tests/test_state.py`: 상태 직렬화와 손상 복구 테스트
- `tests/test_sources.py`: 두 소스 파서와 부분 장애 테스트
- `tests/test_classifier.py`: 다섯 범주와 오탐·누락 경계 테스트
- `tests/test_discord.py`: 메시지 형식, 멘션 억제, 재시도 테스트
- `tests/test_watcher.py`: 최초 실행, 순서, 중복, 장애 상태 테스트
- `tests/test_cli.py`: 세 CLI 명령의 환경 변수와 종료 코드 테스트
- `tests/test_setup_wizard.py`: 설치 마법사의 Secret·Variable 전달과 토큰 비노출 테스트
- `.github/workflows/ci.yml`: push와 pull request에서 전체 테스트 실행
- `.github/workflows/watch.yml`: 10분 예약 실행과 수동 테스트 실행
- `scripts/setup-discord-bot.sh`: 비공개 봇 생성·초대와 GitHub 설정 마법사
- `assets/tiboham-avatar.png`: 티보햄 픽셀아트 프로필 이미지
- `README.md`: 한글 설치·운영·문제 해결 안내
- `LICENSE`: MIT 라이선스

---

### Task 1: 프로젝트 기반, 도메인 모델, 상태 저장

**파일:**

- 생성: `pyproject.toml`
- 생성: `.gitignore`
- 생성: `src/help_me_tibooo/__init__.py`
- 생성: `src/help_me_tibooo/models.py`
- 생성: `src/help_me_tibooo/state.py`
- 생성: `tests/test_state.py`

**인터페이스:**

- 제공: `AlertCategory`, `Post`, `SourceBatch`, `WatcherState`
- 제공: `load_state(path: Path) -> WatcherState | None`
- 제공: `save_state(path: Path, state: WatcherState) -> None`
- 상태 형식: `version`, `latest_id`, `seen_ids`, `consecutive_failures`,
  `outage_notified`

- [ ] **1단계: 상태 읽기·저장 실패 테스트 작성**

```python
from pathlib import Path

from help_me_tibooo.models import WatcherState
from help_me_tibooo.state import load_state, save_state


def test_state_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    expected = WatcherState(
        latest_id="102",
        seen_ids=("100", "101", "102"),
        consecutive_failures=2,
        outage_notified=False,
    )

    save_state(path, expected)

    assert load_state(path) == expected


def test_missing_state_returns_none(tmp_path: Path) -> None:
    assert load_state(tmp_path / "missing.json") is None
```

- [ ] **2단계: 테스트가 예상대로 실패하는지 확인**

실행: `python -m pytest tests/test_state.py -v`

예상: `ModuleNotFoundError: No module named 'help_me_tibooo'`

- [ ] **3단계: 패키지 설정과 모델의 최소 구현 작성**

`pyproject.toml`에는 Python 3.12 이상, 다음 고정 의존성, `src` 패키지 탐색 설정을
명시한다.

```toml
[build-system]
requires = ["setuptools==80.9.0"]
build-backend = "setuptools.build_meta"

[project]
name = "help-me-tibooo"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "beautifulsoup4==4.15.0",
  "httpx==0.28.1",
]

[project.optional-dependencies]
test = ["pytest==9.1.1"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.setuptools.packages.find]
where = ["src"]
```

`.gitignore`와 패키지 초기화 파일은 아래처럼 작성한다.

```gitignore
.state/
.pytest_cache/
.venv/
__pycache__/
*.egg-info/
*.py[cod]
```

```python
# src/help_me_tibooo/__init__.py
__version__ = "0.1.0"
```

`models.py`의 공개 모델은 다음 필드 이름을 그대로 사용한다.

```python
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AlertCategory(StrEnum):
    RESET = "리셋"
    LIMITS = "한도"
    LAUNCH = "출시"
    PLANS = "요금제"
    INCIDENT = "장애"


@dataclass(frozen=True, slots=True)
class Post:
    id: str
    text: str
    created_at: datetime | None
    url: str
    source: str
    is_reply: bool = False
    is_repost: bool = False
    source_kind: str | None = None


@dataclass(frozen=True, slots=True)
class SourceBatch:
    source: str
    posts: tuple[Post, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class WatcherState:
    latest_id: str | None = None
    seen_ids: tuple[str, ...] = ()
    consecutive_failures: int = 0
    outage_notified: bool = False
```

`state.py`는 JSON 객체의 버전이 `1`인지 확인하고, 임시 파일을 같은 디렉터리에 쓴 뒤
`Path.replace()`로 원자적으로 교체한다. 알 수 없는 필드는 무시하되 타입이 잘못된
핵심 필드는 `ValueError`를 발생시킨다. `seen_ids`는 저장 직전에 최근 500개로 제한한다.

```python
def load_state(path: Path) -> WatcherState | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError("지원하지 않는 상태 버전입니다")
    return WatcherState(
        latest_id=payload.get("latest_id"),
        seen_ids=tuple(payload.get("seen_ids", [])),
        consecutive_failures=int(payload.get("consecutive_failures", 0)),
        outage_notified=bool(payload.get("outage_notified", False)),
    )


def save_state(path: Path, state: WatcherState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    payload = {
        "version": 1,
        "latest_id": state.latest_id,
        "seen_ids": list(state.seen_ids[-500:]),
        "consecutive_failures": state.consecutive_failures,
        "outage_notified": state.outage_notified,
    }
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
```

- [ ] **4단계: 상태 테스트 통과 확인**

실행: `python -m pip install -e '.[test]' && python -m pytest tests/test_state.py -v`

예상: `2 passed`

- [ ] **5단계: 기반 작업 커밋**

```bash
git add pyproject.toml .gitignore src/help_me_tibooo tests/test_state.py
git commit -m "feat: 감시 상태 모델과 저장소 추가"
```

---

### Task 2: 공개 데이터 소스 수집과 정규화

**파일:**

- 생성: `src/help_me_tibooo/sources.py`
- 생성: `tests/fixtures/codex_reset_feed.json`
- 생성: `tests/fixtures/twiscan_timeline.html`
- 생성: `tests/conftest.py`
- 생성: `tests/test_sources.py`

**인터페이스:**

- 소비: `Post`, `SourceBatch`
- 제공: `parse_reset_feed(payload: object) -> tuple[Post, ...]`
- 제공: `parse_twiscan_html(html: str) -> tuple[Post, ...]`
- 제공: `fetch_all_sources(client: httpx.Client) -> tuple[SourceBatch, ...]`
- 상수 URL은 실제 외부 의존성이므로 테스트에서 교체할 수 있게 모듈 수준에 둔다.

- [ ] **1단계: JSON과 HTML 파서 실패 테스트 작성**

fixture에는 다음 경우를 실제 응답 구조와 같은 최소 형태로 넣는다.

```python
# tests/conftest.py
import json
from pathlib import Path

import pytest

from help_me_tibooo.models import Post


@pytest.fixture
def load_json_fixture():
    return lambda name: json.loads((Path(__file__).parent / "fixtures" / name).read_text())


@pytest.fixture
def load_text_fixture():
    return lambda name: (Path(__file__).parent / "fixtures" / name).read_text()


@pytest.fixture
def make_post():
    return lambda **changes: Post(
        id=changes.pop("id", "999"),
        text=changes.pop("text", ""),
        created_at=None,
        url="https://x.com/thsottiaux/status/999",
        source="test",
        **changes,
    )
```

```python
def test_reset_feed_keeps_replies(load_json_fixture) -> None:
    posts = parse_reset_feed(load_json_fixture("codex_reset_feed.json"))

    assert [post.id for post in posts] == ["201", "202"]
    assert posts[1].is_reply is True
    assert posts[1].source_kind == "signal"


def test_twiscan_parser_marks_plain_repost(load_text_fixture) -> None:
    posts = parse_twiscan_html(load_text_fixture("twiscan_timeline.html"))

    assert [post.id for post in posts] == ["301", "302", "303"]
    assert posts[0].text == "We are launching GPT-6 Astra today."
    assert posts[2].is_repost is True
```

TwiScan fixture의 게시물 본문은 `id="clamp-<게시물 ID>-<리포스트 ID>"` 요소에 넣는다.
리포스트 ID가 `0`이 아니면 `is_repost=True`로 해석한다.

- [ ] **2단계: 파서 테스트 실패 확인**

실행: `python -m pytest tests/test_sources.py -v`

예상: `ImportError` 또는 정의되지 않은 파서로 실패

- [ ] **3단계: 정규화 파서 최소 구현**

`parse_reset_feed()`는 최상위 `tweets` 배열만 읽고, 각 레코드의 `id`, `text`, `at`,
`url`, `is_reply`, `kind`를 변환한다. `parse_twiscan_html()`은 아래 선택 규칙을 쓴다.

```python
POST_ID_PATTERN = re.compile(r"^clamp-(\d+)-(\d+)$")

for element in soup.select("div[id^='clamp-']"):
    match = POST_ID_PATTERN.fullmatch(element.get("id", ""))
    if match is None:
        continue
    post_id, repost_id = match.groups()
    text = element.get_text(" ", strip=True)
    posts.append(
        Post(
            id=post_id,
            text=text,
            created_at=None,
            url=f"https://x.com/thsottiaux/status/{post_id}",
            source="twiscan",
            is_repost=repost_id != "0",
        )
    )
```

본문, ID, URL이 없거나 ID가 숫자가 아닌 레코드는 버린다. JSON 시각은 `Z`를
`+00:00`으로 바꿔 timezone-aware `datetime`으로 읽는다.

- [ ] **4단계: 부분 장애 수집 테스트와 구현**

```python
def test_fetch_all_sources_isolates_one_failure(load_text_fixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(RESET_FEED_URL):
            raise httpx.ConnectError("reset feed unavailable", request=request)
        return httpx.Response(200, text=load_text_fixture("twiscan_timeline.html"))

    client = httpx.Client(transport=httpx.MockTransport(handler))

    batches = fetch_all_sources(client)

    assert batches[0].error == "reset feed unavailable"
    assert batches[1].posts[0].id == "301"
```

각 요청은 15초 시간제한, `User-Agent: help-me-tibooo/0.1`, 최대 2MiB 응답 제한을
사용한다. 오류 문자열에는 URL, 헤더, 응답 본문을 포함하지 않는다.

- [ ] **5단계: 소스 테스트 통과 확인**

실행: `python -m pytest tests/test_sources.py -v`

예상: 모든 테스트 통과

- [ ] **6단계: 소스 수집 커밋**

```bash
git add src/help_me_tibooo/sources.py tests/conftest.py tests/fixtures tests/test_sources.py
git commit -m "feat: Tibo 공개 피드 수집 추가"
```

---

### Task 3: 중요 뉴스 규칙 분류기

**파일:**

- 생성: `src/help_me_tibooo/classifier.py`
- 생성: `tests/test_classifier.py`

**인터페이스:**

- 소비: `Post`, `AlertCategory`
- 제공: `classify(post: Post) -> tuple[AlertCategory, ...]`
- 반환 범주는 `AlertCategory` 선언 순서를 유지하며 중복되지 않는다.

- [ ] **1단계: 범주별 실패 테스트 작성**

```python
@pytest.mark.parametrize(
    ("text", "source_kind", "expected"),
    [
        ("Your Codex usage reset will land at 6pm.", "candidate", (AlertCategory.RESET,)),
        ("We are bringing back the 5h limit for Plus.", "limits", (AlertCategory.LIMITS,)),
        ("We are starting to release GPT-6 Astra.", None, (AlertCategory.LAUNCH,)),
        ("Plus users now get access at no extra cost.", None, (AlertCategory.PLANS,)),
        ("We found elevated errors and are rolling out a fix.", None, (AlertCategory.INCIDENT,)),
    ],
)
def test_classifies_important_news(make_post, text, source_kind, expected) -> None:
    assert classify(make_post(text=text, source_kind=source_kind)) == expected
```

다음 경계 사례도 명시한다.

```python
def test_ignores_plain_repost(make_post) -> None:
    assert classify(make_post(text="GPT-6 launch", is_repost=True)) == ()


def test_ignores_conversational_reset_without_product_context(make_post) -> None:
    assert classify(make_post(text="Feeling reset after sleeping.")) == ()


def test_recall_first_rule_keeps_ambiguous_openai_shipment(make_post) -> None:
    post = make_post(text="Big Codex news is landing tomorrow.")
    assert classify(post) == (AlertCategory.LAUNCH,)
```

- [ ] **2단계: 분류 테스트 실패 확인**

실행: `python -m pytest tests/test_classifier.py -v`

예상: 분류 함수가 없어 실패

- [ ] **3단계: 문맥 결합 규칙 구현**

소문자로 정규화한 본문에 아래 문맥군을 조합한다.

```python
PRODUCT_TERMS = ("openai", "codex", "chatgpt", "gpt-", "astra")
RESET_TERMS = ("usage reset", "limits reset", "banked reset", "reset button", "reset will")
LIMIT_TERMS = ("usage limit", "rate limit", "weekly limit", "5h limit", "quota")
LAUNCH_TERMS = ("release", "launch", "rollout", "rolling out", "ship", "landing tomorrow")
PLAN_TERMS = ("plus", "pro", "business", "enterprise", "subscription", "pricing", "access")
INCIDENT_TERMS = ("outage", "degraded", "elevated errors", "investigating", "incident", "recovery")
```

`source_kind`가 `candidate`, `banked`, `signal`이고 본문에 reset 문맥이 있으면 리셋으로,
`limits`이면 한도로 분류한다. 일반 타임라인은 제품 문맥과 범주별 표현이 함께 있어야
하며, `big|major|important`와 `news|update|launch`가 제품명과 함께 있으면 출시 범주로
보수적으로 포함한다.

- [ ] **4단계: 분류 테스트 통과 확인**

실행: `python -m pytest tests/test_classifier.py -v`

예상: 모든 테스트 통과

- [ ] **5단계: 분류기 커밋**

```bash
git add src/help_me_tibooo/classifier.py tests/test_classifier.py
git commit -m "feat: 중요 OpenAI 소식 분류 추가"
```

---

### Task 4: Discord 메시지와 제한 재시도

**파일:**

- 생성: `src/help_me_tibooo/discord.py`
- 생성: `tests/test_discord.py`

**인터페이스:**

- 소비: `Post`, `AlertCategory`
- 제공: `build_alert_payload(post: Post, categories: tuple[AlertCategory, ...]) -> dict[str, object]`
- 제공: `build_health_payload(failure_count: int) -> dict[str, object]`
- 제공: `DiscordBot.send(payload: dict[str, object]) -> None`

- [ ] **1단계: payload 보안과 길이 실패 테스트 작성**

```python
def test_alert_payload_disables_mentions(make_post) -> None:
    post = make_post(text="@everyone reset landed")
    payload = build_alert_payload(post, (AlertCategory.RESET,))

    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["embeds"][0]["title"] == "티보햄 · 리셋"
    assert payload["embeds"][0]["url"] == post.url
    assert payload["embeds"][0]["description"] == post.text


def test_health_payload_names_three_failures() -> None:
    payload = build_health_payload(3)
    assert "3회 연속" in payload["embeds"][0]["description"]
```

- [ ] **2단계: payload 테스트 실패 확인**

실행: `python -m pytest tests/test_discord.py -v`

예상: payload 함수가 없어 실패

- [ ] **3단계: payload 생성 최소 구현**

원문은 Discord Embed 설명의 4,096 UTF-16 코드 단위 제한 안에서 자른다. 제목에는
`티보햄`과 한국어 범주, URL에는 검증된 원본 X 링크, 색상에는 첫 범주의 지정 색을 넣는다.

```python
def build_alert_payload(post: Post, categories: tuple[AlertCategory, ...]) -> dict[str, object]:
    labels = " · ".join(category.value for category in categories)
    return {
        "embeds": [{
            "title": f"티보햄 · {labels}",
            "description": post.text,
            "url": post.url,
        }],
        "allowed_mentions": {"parse": []},
    }
```

- [ ] **4단계: 재시도 실패 테스트 작성과 구현**

429와 5xx만 최대 3회 재시도하고, 그 밖의 4xx는 즉시 실패한다. `Retry-After`가 있으면
최대 10초 범위에서 따르고, 없으면 `1`, `2`초로 증가시킨다. 테스트에서는 주입한
`sleep: Callable[[float], None]`로 실제 대기를 제거한다.

```python
def test_bot_retries_server_error_then_succeeds() -> None:
    statuses = iter((500, 200))
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(next(statuses))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    bot = DiscordBot("secret.bot.token", "123456789", client, sleeps.append)

    bot.send({"content": "test", "allowed_mentions": {"parse": []}})

    assert len(calls) == 2
    assert sleeps == [1.0]
```

봇은 `POST /api/v10/channels/<channel_id>/messages`에 `Authorization: Bot <token>`을
사용한다. 예외 메시지와 로그에는 Bot Token이나 Discord 응답 본문을 포함하지 않는다.

- [ ] **5단계: Discord 테스트 통과 확인**

실행: `python -m pytest tests/test_discord.py -v`

예상: 모든 테스트 통과

- [ ] **6단계: Discord 전송 커밋**

```bash
git add src/help_me_tibooo/discord.py tests/test_discord.py
git commit -m "feat: Discord 봇 알림 추가"
```

---

### Task 5: 감시 실행 흐름과 장애 상태

**파일:**

- 생성: `src/help_me_tibooo/watcher.py`
- 생성: `tests/test_watcher.py`

**인터페이스:**

- 소비: `SourceBatch`, `WatcherState`, `classify()`, Discord payload 생성기
- 제공: `run_watcher(batches, state, send_alert, send_health) -> WatcherState`
- `send_alert`는 `(Post, tuple[AlertCategory, ...]) -> None`
- `send_health`는 `(int) -> None`

- [ ] **1단계: 최초 실행과 중복 제거 실패 테스트 작성**

```python
def important_post(post_id: str) -> Post:
    return Post(
        id=post_id,
        text="Your Codex usage reset will land soon.",
        created_at=None,
        url=f"https://x.com/thsottiaux/status/{post_id}",
        source="test",
        source_kind="candidate",
    )


def no_alert(*_args: object) -> None:
    raise AssertionError("알림을 보내면 안 됩니다")


def test_first_run_baselines_without_alerting() -> None:
    alerts: list[str] = []
    batches = (SourceBatch("reset", posts=(important_post("401"),)),)

    state = run_watcher(batches, None, lambda post, _: alerts.append(post.id), lambda _: None)

    assert alerts == []
    assert state.latest_id == "401"
    assert state.seen_ids == ("401",)


def test_cross_source_duplicate_sends_once() -> None:
    alerts: list[str] = []
    duplicate = important_post("402")
    batches = (
        SourceBatch("reset", posts=(duplicate,)),
        SourceBatch("twiscan", posts=(duplicate,)),
    )

    state = run_watcher(batches, WatcherState(latest_id="401", seen_ids=("401",)),
                        lambda post, _: alerts.append(post.id), lambda _: None)

    assert alerts == ["402"]
    assert state.seen_ids[-1] == "402"
```

- [ ] **2단계: 시간순 전송과 리포스트 제외 테스트 추가**

게시물 ID를 정수로 정렬하되 파싱 불가능한 ID는 `created_at`과 입력 순서를 보조 키로
사용한다. `403`, `404`가 최신순으로 들어와도 알림은 `403`, `404` 순서여야 한다.
리포스트와 분류 결과가 빈 게시물은 알림 없이 `seen_ids`에 포함한다.

- [ ] **3단계: 실행 흐름 최소 구현**

```python
def run_watcher(
    batches: tuple[SourceBatch, ...],
    state: WatcherState | None,
    send_alert: Callable[[Post, tuple[AlertCategory, ...]], None],
    send_health: Callable[[int], None],
) -> WatcherState:
    healthy = tuple(batch for batch in batches if batch.error is None)
    if not healthy:
        return record_total_failure(state or WatcherState(), send_health)

    posts = deduplicate_posts(healthy)
    if state is None:
        return baseline(posts)

    next_state = clear_failure_state(state)
    for post in unseen_posts_oldest_first(posts, state.seen_ids):
        categories = classify(post)
        if categories:
            send_alert(post, categories)
        next_state = remember(next_state, post.id)
    return next_state
```

알림 전송이 실패한 게시물은 기억하지 않고 예외를 다시 발생시켜 다음 실행에서
재시도한다. 그 게시물 뒤의 최신 게시물도 처리하지 않아 메시지 순서를 보존한다.

- [ ] **4단계: 3회 연속 전체 장애 테스트와 구현**

```python
def test_health_alert_fires_once_on_third_consecutive_failure() -> None:
    health_alerts: list[int] = []
    state = WatcherState()
    failed = (SourceBatch("reset", error="down"), SourceBatch("twiscan", error="down"))

    state = run_watcher(failed, state, no_alert, health_alerts.append)
    state = run_watcher(failed, state, no_alert, health_alerts.append)
    state = run_watcher(failed, state, no_alert, health_alerts.append)
    state = run_watcher(failed, state, no_alert, health_alerts.append)

    assert health_alerts == [3]
    assert state.consecutive_failures == 4
    assert state.outage_notified is True
```

정상 소스가 하나라도 돌아오면 `consecutive_failures=0`, `outage_notified=False`로
초기화한다. 세 번째 장애 알림 전송 자체가 실패하면 `outage_notified`를 설정하지 않아
다음 실행에서 다시 시도한다.

- [ ] **5단계: 감시 흐름 테스트 통과 확인**

실행: `python -m pytest tests/test_watcher.py -v`

예상: 모든 테스트 통과

- [ ] **6단계: 감시 실행 흐름 커밋**

```bash
git add src/help_me_tibooo/watcher.py tests/test_watcher.py
git commit -m "feat: 중복 방지 감시 흐름 추가"
```

---

### Task 6: CLI, GitHub Actions, 운영 문서

**파일:**

- 생성: `src/help_me_tibooo/__main__.py`
- 생성: `tests/test_cli.py`
- 생성: `.github/workflows/ci.yml`
- 생성: `.github/workflows/watch.yml`
- 생성: `README.md`
- 생성: `LICENSE`

**인터페이스:**

- 제공: `python -m help_me_tibooo watch --state-path .state/watcher.json`
- 제공: `python -m help_me_tibooo test-bot`
- 제공: `python -m help_me_tibooo smoke`
- 환경 변수: `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`는 `watch`와 `test-bot`에서만 필수

- [ ] **1단계: CLI 실패 테스트 작성**

```python
def test_watch_requires_bot_credentials(monkeypatch, capsys) -> None:
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)

    exit_code = main(["watch", "--state-path", ".state/test.json"])

    assert exit_code == 2
    assert "DISCORD_BOT_TOKEN" in capsys.readouterr().err


def test_smoke_does_not_require_bot_credentials(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_all_sources",
        lambda _client: (
            SourceBatch(
                "reset",
                posts=(
                    Post(
                        id="501",
                        text="Codex usage reset",
                        created_at=None,
                        url="https://x.com/thsottiaux/status/501",
                        source="test",
                    ),
                ),
            ),
        ),
    )
    assert main(["smoke"]) == 0
```

- [ ] **2단계: CLI 구현과 테스트 통과 확인**

`watch`는 상태를 읽고, 두 소스를 가져오고, `run_watcher()`를 호출한 뒤 `finally`에서
갱신된 상태를 저장한다. `test-bot`은 `티보햄 · 연결 테스트` Embed만 보내며 상태
파일을 열지 않는다. `smoke`는 소스별 정상 여부와 게시물 개수만 출력하고 Discord를
호출하지 않는다.

실행: `python -m pytest tests/test_cli.py -v`

예상: 모든 테스트 통과

- [ ] **3단계: CI 워크플로 작성**

`.github/workflows/ci.yml`은 `push`, `pull_request`에서 Python 3.12를 설치하고 다음
명령을 실행한다.

```yaml
permissions:
  contents: read

steps:
  - uses: actions/checkout@v4
  - uses: actions/setup-python@v5
    with:
      python-version: "3.12"
      cache: pip
  - run: python -m pip install -e '.[test]'
  - run: python -m pytest -q
```

- [ ] **4단계: 10분 예약·수동 실행 워크플로 작성**

`.github/workflows/watch.yml`은 중복 실행을 막고 최소 권한을 사용한다.

```yaml
on:
  schedule:
    - cron: "*/10 * * * *"
  workflow_dispatch:
    inputs:
      mode:
        description: 실행 방식
        required: true
        default: test-bot
        type: choice
        options:
          - test-bot
          - watch
          - smoke

permissions:
  contents: read

concurrency:
  group: help-me-tibooo-watcher
  cancel-in-progress: false
```

예약 이벤트는 항상 `watch`, 수동 이벤트는 선택한 `inputs.mode`를 실행한다. `watch`일
때만 `actions/cache/restore@v4`로 `help-me-tibooo-state-` 접두사의 최신 캐시를
`.state`에 복원한다. 실행 후 `actions/cache/save@v4`를 `if: always()`와
`help-me-tibooo-state-${{ github.run_id }}-${{ github.run_attempt }}` 키로 호출한다.
Bot Token은 `env.DISCORD_BOT_TOKEN: ${{ secrets.DISCORD_BOT_TOKEN }}`, 채널 ID는
`env.DISCORD_CHANNEL_ID: ${{ vars.DISCORD_CHANNEL_ID }}`로 `watch`와 `test-bot`
단계에만 전달한다.

- [ ] **5단계: 한글 README와 MIT 라이선스 작성**

README에는 다음 실제 운영 절차를 순서대로 적는다.

1. `scripts/setup-discord-bot.sh`로 Discord Developer Portal에서 `티보햄` 비공개 봇을
   만들고 픽셀아트 프로필 이미지를 등록한다.
2. 봇을 개인 서버에 `채널 보기`, `메시지 보내기` 권한으로 초대한다.
3. 마법사가 Bot Token을 GitHub Secret `DISCORD_BOT_TOKEN`, 채널 ID를 GitHub Variable
   `DISCORD_CHANNEL_ID`로 등록한다.
4. `Actions → Tibo watcher → Run workflow → test-bot`으로 연결을 확인한다.
5. 예약 실행은 10분마다 요청되지만 GitHub 사정으로 늦을 수 있음을 안내한다.
6. 공개 피드 장애, 규칙 기반 분류의 오탐·누락, 캐시 유실 시 재기준점 설정 가능성을
   알려진 제약으로 명시한다.

라이선스 저작권 표기는 `Copyright (c) 2026 chjh6107`로 한다.

- [ ] **6단계: 전체 로컬 검증**

실행:

```bash
python -m pytest -q
python -m help_me_tibooo smoke
git diff --check
```

예상: 전체 테스트 통과, 두 공개 소스 중 하나 이상의 정상 상태와 게시물 개수 출력,
공백 오류 없음. `smoke`는 Discord 메시지를 보내지 않는다.

- [ ] **7단계: 운영 파일 커밋**

```bash
git add src/help_me_tibooo/__main__.py tests/test_cli.py .github README.md LICENSE
git commit -m "feat: GitHub Actions 감시 운영 추가"
```

- [ ] **8단계: 푸시 후 GitHub 검증**

실행:

```bash
git push origin main
gh run list --repo chjh6107/help-me-tibooo --limit 5
```

CI가 성공한 뒤 `Tibo watcher`를 `smoke` 모드로 수동 실행해 공개 소스 접근을 확인한다.
`DISCORD_BOT_TOKEN` Secret과 `DISCORD_CHANNEL_ID` Variable이 설정된 뒤에만
`test-bot`을 실행한다. 값이 없다면 구현 완료 보고에는 Discord 실전 전송이 아직
사용자 설정 대기 중임을 분명히 표시한다.
