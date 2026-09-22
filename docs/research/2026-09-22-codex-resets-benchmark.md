# codex-resets.com 공개 동작 벤치마크

- 조사 시각: 2026-09-22 00:18 KST / 2026-09-21 15:18 UTC
- 조사 대상: <https://codex-resets.com/ko>
- 조사 범위: 공개 페이지, 공개 OpenAPI, 공개 MCP, 배포된 클라이언트 자바스크립트, 공개 Telegram 채널, 공개 HTTP 헤더
- 제외 범위: 비공개 저장소·인프라·프롬프트 추정, 현재 프로젝트의 분류기·운영 로그 감사

## 결론

codex-resets.com은 `@thsottiaux`의 모든 글을 공개하는 피드가 아니다. 공개 API와 MCP가 제공하는 것은 확정된 리셋 이력, 현재 예정된 리셋, 현재 활성화된 리셋 가능성 관찰과 통계다. 비리셋 글, 제외 판정, 과거 관찰·예정 상태의 전체 이력은 공개 API에 없다.

사이트는 스스로 `@thsottiaux`의 글을 “로봇이 분류한다”고 밝히고, OpenAPI와 MCP는 `active_watch`를 “AI-classified forecast”라고 명시한다. 그러나 확정 리셋의 분류까지 LLM이 담당하는지, 규칙과 LLM을 함께 쓰는지, 어떤 모델·프롬프트·임계값을 쓰는지는 공개되어 있지 않다. 따라서 “전체 분류가 LLM 기반”이라고 단정할 수 없다.

최근 수집 이벤트는 내부 UI 응답에서 `source: "webhook"`으로 표시되고, 공개 Telegram의 확정 알림은 원문 시각과 비교할 수 있는 13개 표본 중 12개가 10~45초 뒤에 게시됐다. 이는 빠른 이벤트 수집·분류·알림 파이프라인의 강한 관측 증거지만, 원본 공급자와 실제 웹 페이지 갱신 시각은 공개되지 않았다. 13개 중 하나는 약 4시간 48분이 걸렸으므로 항상 수십 초라고 보장할 수도 없다.

현재 봇이 이미 `/api/v1/resets`를 읽는다면 codex-resets.com과 경쟁하는 별도 분류기가 아니라 그 사이트의 확정 결과를 소비하는 구조다. 이 API만으로는 전체 Tibo 글 분류를 재현할 수 없고, 캐시 정책 때문에 호출 주기를 줄인다고 바로 1~2분의 종단 지연을 보장할 수도 없다.

## 확정된 공개 사실

### 수집 대상과 공개 범위

홈페이지는 데이터가 [`@thsottiaux`](https://x.com/thsottiaux)의 게시물에서 온다고 밝힌다. 공개 API 스키마의 `ResetSource`도 `x_post`의 `author`를 `thsottiaux` 한 값으로 제한한다.

공개 OpenAPI가 열거하는 경로는 다음 두 개뿐이다.

- [`GET /api/v1/status`](https://codex-resets.com/api/v1/status): 최근 확정 리셋, 현재 예정 리셋, 현재 활성 관찰, 통계
- [`GET /api/v1/resets`](https://codex-resets.com/api/v1/resets): 확정 리셋 이력의 커서 페이지네이션

공개 MCP의 `tools/list`도 `get_status`, `list_resets` 두 도구만 반환한다. MCP 설명과 설치 주소는 [사이트가 직접 연결한 MCP](https://codex-resets.com/mcp)에서 확인할 수 있다.

따라서 다음 데이터는 공개 API에서 확인할 수 없다.

- `@thsottiaux`의 전체 게시물 피드
- 각 게시물의 비리셋 판정 결과
- 분류 점수·근거·모델·프롬프트·규칙 버전
- 과거 `active_watch`와 `scheduled_reset`의 상태 전이 이력
- 수집 시각, 분류 시작·완료 시각, 사이트 게시 시각

[한국어 홈페이지](https://codex-resets.com/ko)의 “모든 발표를 기록합니다”는 모든 Tibo 글이 아니라 사이트가 리셋 발표로 채택한 기록을 뜻한다. 2026-09-21 UTC 기준 공개 이력은 53건이었다.

### 분류 결과의 공개 모델

[OpenAPI 3.1 문서](https://codex-resets.com/api/openapi.json)에 공개된 상태는 다음과 같다.

| 상태 | 공개 필드 | 의미 |
| --- | --- | --- |
| 확정 리셋 | `reset_type`, `regular` / `banked`, `announced_at`, `text`, `source` | 실행된 것으로 기록한 리셋 |
| 예정 리셋 | `status: scheduled`, `reset_type`, `announced_at`, `scheduled_for` | 명시적 발표가 있으나 실행 근거를 기다리는 상태 |
| 활성 관찰 | `level`, `elevated` / `strong`, `reset_chance_percent`, `forecast_window`, `observed_at`, `expires_at` | AI가 분류한 예측 상태 |
| 출처 | `x_post` 또는 `observed` | X 게시물 또는 발표 없이 관찰된 사건 |

문서가 강조하는 상태 의미도 보수적이다.

- 예정 시각이 지나도 완료를 뜻하지 않는다.
- 예정 리셋은 실행 근거가 확인될 때까지 대기 상태다.
- 관찰 데이터는 AI가 분류한 예측이며 OpenAI의 약속이 아니다.
- `announced_at`은 “발표 시각 또는 최초 관찰 시각”이다.

현재 공개 상태에는 `scheduled_reset`과 `active_watch`가 모두 `null`이었다. 따라서 라이브 상태 객체의 실제 비어 있지 않은 예시는 OpenAPI 스키마와 [공개 Telegram 아카이브](https://t.me/s/codex_resets)에서 확인했다.

### 수집 방식에 대해 말할 수 있는 범위

배포된 홈페이지가 사용하는 같은 출처의 JSON 응답 `/api/resets`에는 이벤트별 `source`가 있다. 2026-09-21 UTC 관측치 53건은 다음과 같았다.

| `source` | 건수 | 공개 정보로 가능한 해석 |
| --- | ---: | --- |
| `webhook` | 17 | webhook 경로로 들어온 이벤트라는 내부 라벨 |
| `backfill` | 34 | 과거 데이터를 소급 적재한 이벤트 |
| `observed` | 2 | 발표가 없거나 발표 시각 대신 최초 관찰 시각을 쓴 이벤트 |

`webhook`은 주기적 전체 폴링보다 이벤트 전달형 입력을 시사한다. 다만 어떤 X API·공급자·중계 서비스를 썼는지, webhook을 받기 전에 다른 폴링이 있는지는 공개되지 않았다. 이 필드는 공식 v1 API 스키마에 없는 내부 UI 필드이므로 구현 의존 대상으로 삼으면 안 된다.

사이트 제작자는 [공개 GitHub 프로필](https://github.com/wong2)에서 Codex Resets를 빌드 중인 서비스로 연결하지만, 사이트는 소스 저장소를 연결하지 않는다. 조사 당시 제작자의 공개 저장소 목록에서도 이 서비스의 구현 저장소는 확인되지 않았다. 이것은 “오픈소스가 아니다”의 완전한 증명이 아니라, 공개 구현 근거를 찾지 못했다는 뜻이다.

### 분류기가 LLM인지 규칙인지

확정할 수 있는 내용은 두 가지다.

1. [홈페이지](https://codex-resets.com/index.md)는 게시물을 로봇이 분류한다고 설명한다.
2. [OpenAPI](https://codex-resets.com/api/openapi.json)와 공개 MCP는 `active_watch`를 AI가 분류한 예측이라고 명시한다.

그 이상은 불명확하다. 다음을 공개 근거 없이 단정하면 안 된다.

- 확정 리셋과 `regular`/`banked` 구분도 LLM이 수행한다.
- 모든 Tibo 글을 LLM에 넣는다.
- 특정 상용 모델이나 유료 API를 사용한다.
- 규칙 전처리, 중복 제거, 수동 보정이 없다.
- Telegram의 `observed` 사건이 자동 또는 수동으로 만들어졌다.

### 언어 처리

사이트는 영어, 중국어 간체, 중국어 번체, 일본어, 한국어 다섯 언어를 제공한다. 각 HTML 페이지는 서버 렌더링되고 동일 언어의 Markdown 대체 문서도 제공한다. 예: [한국어 HTML](https://codex-resets.com/ko), [한국어 Markdown](https://codex-resets.com/ko.md).

배포된 홈페이지 번들 [`index-CusWs7pC.js`](https://codex-resets.com/assets/index-CusWs7pC.js)에서 확인한 구조는 다음과 같다. 파일 해시는 배포 때 바뀔 수 있다.

- 고정 UI 문구는 클라이언트의 5개 언어 사전으로 제공한다.
- 내부 UI용 `/api/resets?locale=ko` 응답은 `text`에 영어 원문, `display_text`에 한국어 표시문을 함께 반환한다.
- 공개 v1 OpenAPI에는 `locale` 파라미터가 없고 v1 응답의 `text`는 영어 원문이다.

번역 모델, 번역 요청 시점, 캐시, 실패 시 폴백은 공개되지 않았다. 다국어 `display_text`가 서버 응답에 이미 포함되므로 브라우저가 새 글마다 직접 LLM 번역을 호출하는 구조는 아니다.

### 게시·알림 구조

공개 출력 채널은 다음과 같다.

- 서버 렌더링 홈페이지와 언어별 Markdown
- 브라우저 푸시
- [Telegram 채널](https://t.me/codex_resets)
- 이메일 알림
- [`@codex_resets` X 계정](https://x.com/codex_resets)
- 공개 REST API와 MCP

Telegram 공개 기록에는 다음처럼 확정 이력 API보다 넓은 상태가 보인다.

- `Possible Codex reset`과 확률·예측 창
- `Codex reset announced`와 예정 시각
- `Codex reset confirmed`
- Tibo가 아직 게시하지 않았지만 여러 사용자가 리셋을 보고했다는 관찰

그러나 공개 REST API는 현재 상태만 보존하고 과거 관찰·예정 상태를 조회하는 엔드포인트는 제공하지 않는다. Telegram은 사람이 읽는 공개 아카이브이지 전체 분류 데이터 API가 아니다.

### 화면 갱신과 원문 수집 주기는 다르다

배포된 클라이언트 번들은 탭이 보이는 동안 내부 UI용 `/api/resets`를 `refreshInterval: 3e4`, 즉 30초마다 `cache: "no-store"`로 다시 읽는다. 포커스 복귀와 네트워크 재연결 때도 재검증한다.

이것은 브라우저의 상태 갱신 주기다. Tibo의 원문을 30초마다 수집한다는 근거가 아니며, 서버 분류 주기도 아니다. `source: "webhook"`과 함께 보면 서버에서 사건이 먼저 적재되고 브라우저가 최대 약 30초 단위로 화면을 따라가는 구조로 관측된다.

### 공개 알림 지연 관측

공개 Telegram 메시지의 `datetime`과 같은 X 상태를 가리키는 내부 UI 이벤트의 `announced_at`을 비교했다. `source: "webhook"`이며 양쪽을 정확히 연결할 수 있는 13건이 대상이다.

- 12건: 10~45초
- 중앙값: 16초
- 1건: 17,306초, 약 4시간 48분 26초
- 표본 메시지: [24](https://t.me/codex_resets/24), [27](https://t.me/codex_resets/27), [29](https://t.me/codex_resets/29), [31](https://t.me/codex_resets/31), [34](https://t.me/codex_resets/34), [36](https://t.me/codex_resets/36), [42](https://t.me/codex_resets/42)

이 수치는 “원문 발표/관찰 시각 → Telegram 게시 시각”의 지연 대용치다. 다음 이유로 웹 게시 지연이나 분류 실행 시간으로 바꿔 말하면 안 된다.

- API에는 `ingested_at`, `classified_at`, `published_at`이 없다.
- `announced_at`은 원문 발표 시각 또는 최초 관찰 시각이다.
- Telegram의 편집 시각과 최초 게시 시각을 분리해 주지 않는 항목이 있다.
- 웹 페이지와 Telegram이 같은 트랜잭션에서 게시되는지 공개되지 않았다.
- 4시간 48분의 이상치가 있어 항상 수십 초라는 보장이 없다.

사이트가 UI 문구로 약속하는 수준도 “발표하면 몇 분 안에 표시”다. 공개 표본은 대체로 이 주장과 맞지만 서비스 수준 보장은 아니다.

## API 캐시·제한·타임스탬프

### 2026-09-21 15:18 UTC 실제 응답 헤더

| URL | `Cache-Control` | 추가 관측 |
| --- | --- | --- |
| [`/api/v1/status`](https://codex-resets.com/api/v1/status) | `public, max-age=14400, s-maxage=60, stale-while-revalidate=300` | `ETag`, `Age`, CORS `*` |
| [`/api/v1/resets?limit=1`](https://codex-resets.com/api/v1/resets?limit=1) | `public, max-age=60, s-maxage=300, stale-while-revalidate=300` | `ETag`, CORS `*` |
| [`/ko.md`](https://codex-resets.com/ko.md) | `public, max-age=60` | 매 응답 끝에 생성 시각 표기 |
| [`/ko`](https://codex-resets.com/ko) | `private, no-store` | 서버 렌더링 HTML |

공유 캐시만 보아도 v1 이력 응답은 300초 동안 신선한 것으로 취급되고, 추가 300초 동안 오래된 응답을 재검증 중 반환할 수 있다. 실제 갱신은 캐시 purge나 재검증 방식에 따라 더 빨라질 수 있으므로 “항상 10분 늦는다”라고 단정할 수 없다. 반대로 소비자가 1~2분마다 호출한다는 이유만으로 1~2분 종단 지연을 약속해서도 안 된다.

[API 문서](https://codex-resets.com/api/docs)는 키 없이 무료라고 명시한다. OpenAPI는 `429`와 `Retry-After`를 정의하지만 숫자로 된 요청 한도는 공개하지 않는다. `ETag`와 `304 Not Modified`를 공식 응답으로 정의하므로 소비자는 조건부 요청과 보수적인 폴링을 사용하는 편이 맞다.

[`robots.txt`](https://codex-resets.com/robots.txt)는 모든 user-agent에 `/`를 허용한다. 이것은 API의 무제한 호출 허가가 아니며, 별도의 수치형 API 한도는 여전히 불명확하다.

### 타임스탬프 의미

| 필드 | 의미 | 지연 측정에 쓸 수 있는가 |
| --- | --- | --- |
| `announced_at` | 원문 발표 또는 최초 관찰 시각 | 시작점으로만 사용 가능 |
| `scheduled_for` | 발표된 예정 실행 시각 | 실제 완료 시각이 아님 |
| `observed_at` | 관찰 예측을 만든 기준 시각 | 활성 관찰에만 있음 |
| `expires_at` | 관찰 예측 만료 시각 | 게시 지연과 무관 |
| `meta.generated_at` | API 응답 생성 시각 | 이벤트 적재 시각이 아님 |
| Markdown `Generated …` | 문서 응답 생성 시각 | 이벤트 적재 시각이 아님 |
| Telegram `<time datetime>` | 채널 메시지 게시 시각 | 알림 지연의 대용치 |

관측된 API 기계 시각은 ISO 8601 UTC(`Z`)였다. 한국어 SSR HTML도 UTC 절대 시각과 `data-datetime`을 포함하며, 클라이언트는 브라우저 `Intl.DateTimeFormat`으로 표시를 다시 계산한다.

## 현재 봇과 비교할 때 유효한 항목

| 비교 질문 | codex-resets.com에서 확인된 답 | 비교 시 주의점 |
| --- | --- | --- |
| 원천 범위 | 단일 `@thsottiaux` | 전체 글은 공개하지 않음 |
| 새 글 수집 | 최근 확정 이벤트에 `webhook` 라벨 | 공급자·실제 수집 구현 불명 |
| 분류 | 로봇 분류, watch는 AI 분류 | 확정 분류의 LLM 사용 여부 불명 |
| 결과 모델 | 확정·예정·관찰, regular·banked | 제외 판정·과거 상태 전이 미공개 |
| 웹 갱신 | 활성 탭에서 30초 재조회 | 원문 수집 주기가 아님 |
| 확정 알림 속도 | 공개 표본 대부분 10~45초, 이상치 4시간 48분 | Telegram 대용치이며 SLA가 아님 |
| 번역 | 5개 언어, 서버 제공 번역문 | 번역 기술·실패 정책 불명 |
| 배포 | 웹·Markdown·푸시·Telegram·이메일·X·API·MCP | 채널별 원자성·재시도 공개 안 됨 |
| API 최신성 | list 공유 캐시 300초 + stale 300초 | 짧은 호출 주기만으로 상쇄 못 함 |
| 전체 피드 재사용 | 불가 | 리셋 결과 보강 신호로만 적합 |

현재 봇이 v1 이력 API를 이미 소비한다면 사이트와 봇의 시간 차이는 크게 두 구간으로 나눠야 한다.

1. Tibo 게시물 → codex-resets.com 수집·분류·v1 공개
2. v1 응답 → 현재 봇의 수집·영속화·Discord 발송

공개 데이터에는 1번 구간의 완료 시각이 없으므로, 현재 봇 로그만 보고 사이트 분류가 느리다고 결론 내릴 수 없다. 반대로 Telegram이 빠른 사례만 보고 현재 봇의 지연을 전부 v1 캐시 탓으로 돌릴 수도 없다. 비교 실험에는 각 구간의 별도 타임스탬프가 필요하다.

## 회의에서 반박 가능한 추천 3개

1. **codex-resets v1을 전체 피드가 아니라 확정 리셋 보강 신호로 제한한다.** 전체 글·제외 결과가 없으므로 단독 원천으로 쓰면 공지, 예고, 일반 중요 글을 놓친다. 반박 조건은 제작자가 전체 글과 제외 판정을 제공하는 공식 엔드포인트를 공개하는 경우다.

2. **자체 파이프라인에 단계별 UTC 시각을 영속화한다.** 최소 `source_published_at`, `fetched_at`, `classified_at`, `persisted_at`, `sent_at`을 두면 원문 수집, 분류, 저장, Discord 중 어느 구간이 느린지 측정할 수 있다. 반박 조건은 외부 원천이 이미 신뢰할 수 있는 동일 단계의 타임스탬프와 전달 보장을 제공하는 경우다.

3. **1~2분 목표는 자체 원천 수집 구간에만 두고 v1 소비 경로에는 SLA로 약속하지 않는다.** 공개 list API의 공유 캐시 300초와 stale 300초는 소비자 폴링만으로 통제할 수 없다. v1은 ETag 조건부 요청과 late-arrival 재조회 창을 적용하고, 빠른 경로는 무료로 직접 운영 가능한 별도 원천에서 측정한다. 반박 조건은 codex-resets가 캐시 무효화·webhook·명시적 최신성 보장을 공개하는 경우다.

## 재현 명령

민감 정보나 인증 없이 실행했다.

```bash
curl -sS -D - https://codex-resets.com/api/v1/status -o /dev/null
curl -sS -D - 'https://codex-resets.com/api/v1/resets?limit=1' -o /dev/null
curl -sS https://codex-resets.com/api/openapi.json | jq .
curl -sS https://codex-resets.com/ko.md
curl -sS https://codex-resets.com/robots.txt
curl -sS https://t.me/s/codex_resets
```

배포 번들의 30초 값은 조사 시점 HTML이 연결한 다음 파일에서 확인했다.

```text
https://codex-resets.com/assets/index-CusWs7pC.js
refreshInterval:3e4
fetch(ce(), { cache: `no-store` })
```

## 불명확한 사항

- X 원문을 가져오는 공식·비공식 공급자와 비용
- webhook 이전에 존재할 수 있는 폴링 주기
- 확정 분류의 LLM·규칙·수동 검수 구성
- 모델, 프롬프트, confidence 임계값, 재분류 정책
- 번역 엔진과 번역 실패 처리
- 웹·API·Telegram·이메일·X 게시의 트랜잭션과 재시도
- 수치형 API rate limit
- API 캐시 purge 조건
- 4시간 48분 Telegram 이상치의 원인
- 공개되지 않은 전체 글·제외 판정 저장 여부
