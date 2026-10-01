# Help Me Tibooo

![티보햄 Discord 봇 프로필](assets/tiboham-avatar.png)

Tibo의 공개 게시물과 답글에서 중요한 OpenAI 소식을 찾아 Discord 채널에 알리는 작은
감시 도구입니다. Codex 사용량 리셋, 한도 변경, 주요 출시, 요금제 변경, 중대한 장애와
복구를 규칙으로 분류합니다. 유료 X API나 언어 모델 API는 사용하지 않습니다.

## 운영 설정

Discord 서버에 실제 비공개 봇 `티보햄`을 초대해 사용합니다. 봇은 별도의 상시 서버에
접속하지 않으므로 멤버 목록에서 오프라인으로 보일 수 있지만, 예약 알림 전송에는
문제가 없습니다.

가장 간단한 설정 방법은 저장소 루트에서 설치 마법사를 실행하는 것입니다.

```bash
./scripts/setup-discord-bot.sh
```

마법사는 Discord Developer Portal을 열고 다음 절차를 차례로 안내합니다.

1. 이름이 `티보햄`인 비공개 Discord 애플리케이션과 봇을 만듭니다.
2. `assets/tiboham-avatar.png`를 봇 프로필 이미지로 등록합니다.
3. `채널 보기`, `메시지 보내기` 권한만 가진 봇을 개인 서버에 초대합니다.
4. Bot Token을 GitHub Secret `DISCORD_BOT_TOKEN`으로 등록합니다.
5. 알림 채널 ID를 GitHub Variable `DISCORD_CHANNEL_ID`로 등록합니다.
6. PR을 병합한 뒤 `Actions → Tibo watcher → Run workflow`에서 `test-bot`을 선택해
   연결을 확인합니다.

마법사는 Bot Token 발급 전에 GitHub CLI 로그인을 확인하며, Secret 등록에 성공해야
다음 단계로 진행합니다. 직접 설정하려면 Discord
Developer Portal에서 같은 봇을 만들고, GitHub 저장소의
`Settings → Secrets and variables → Actions`에 위 Secret과 Variable을 등록하면 됩니다.

운영 감시는 `watch-loop`로 실행합니다. 한 세션은 최대 10분 동안 2분 간격으로 수집하고,
마지막 상태 캐시 저장을 확인한 뒤 다음 세션을 직접 요청합니다. 별도 서버나 추가 토큰은
필요하지 않습니다. 매시 7분·37분 예약은 연결이 끊겼을 때 다시 시작하는 보조 수단입니다.
Actions의 작업량에 따라 세션 교체가 지연될 수 있고, 공개 피드가 원문을 늦게 제공하면
원문 업로드부터 Discord 도착까지 2분을 보장하지는 못합니다.

이 방식은 공개 저장소의 표준 runner를 하루 동안 계속 사용합니다. 비공개 저장소에서는
연결 감시를 실행하지 않습니다. 멈추려면 Actions에서 `Tibo watcher`를 비활성화하거나
저장소 Variable `WATCHER_PAUSED`를 `true`로 설정합니다. 이미 실행 중인 세션은 끝까지 상태를
저장합니다. 즉시 중지하려면 현재 및 대기 실행도 취소하세요. 재개할 때 workflow를 활성화하고 Variable을 제거한 뒤 `watch-loop`를 수동
실행합니다. `watch`는 이전처럼 한 번만 실행하며 다음 세션을 요청하지 않습니다. 운영 watch·watch-loop는
기본 브랜치에서만 실행됩니다. 대기 중인 감시는 수동 watch 때문에 취소되지 않습니다.

`watch-loop`는 운영 상태 파일이 없으면 수집 전에 실패합니다. 신규 설치에서만 `watch`를
먼저 한 번 실행해 최초 기준점을 생성하세요. 운영 중 cache가 유실되면 조용히 새 기준점으로
넘어가지 않고 중단하므로, 마지막 운영 상태를 복구한 뒤 재개해야 합니다.

Bot Token은 저장소 파일, 이슈, 로그에 붙여 넣지 마세요. 노출되었다면 Discord
Developer Portal의 Bot 화면에서 즉시 토큰을 재발급하세요.

## 로컬 확인

Python 3.12 이상이 필요합니다.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest -q
python -m help_me_tibooo smoke
```

`smoke`는 Discord에 메시지를 보내거나 감시 상태를 변경하지 않고, 세 공개 소스의 정상
여부와 게시물 개수 또는 안전한 오류 요약을 출력합니다. 전체 소식 수집이 불가능하면
종료 코드 1을 반환합니다. `smoke --scope resets`는 새 리셋 API의 접근만 검증합니다.
Actions 수동 실행의 `smoke-resets`도 같은 진단이며 Discord 자격 증명을 사용하지 않습니다.
실제 감시는 다음 명령으로 실행할 수 있습니다.

```bash
python -m help_me_tibooo watch --state-path .state/watcher.json
```

기존 상태를 사용해 반복 수집을 확인하려면 다음 명령을 사용합니다. 각 수집이 끝날 때
상태를 저장하고, 전송 실패는 다음 수집에서 이어서 재시도합니다. 로컬 명령 자체는
새 Actions 실행을 요청하지 않습니다.

```bash
python -m help_me_tibooo watch-loop \
  --state-path .state/watcher.json \
  --interval-seconds 120 --duration-seconds 600 \
  --metrics-path .observability/watch.jsonl
```

Actions의 반복 감시는 endpoint 관측과 전송 결과를 7일 보관하는
`watcher-diagnostics-<run_id>-<attempt>` artifact로 남깁니다. 진단의 measurement epoch는
세션마다 시작하며, 세션 간 최초 관측 시각을 뜻하지 않습니다.

`watch`와 `test-bot`에는 실행 환경의 `DISCORD_BOT_TOKEN`과 `DISCORD_CHANNEL_ID`가
필요합니다. 로컬 상태 파일과 Bot Token은 커밋하지 마세요.

발송 없이 endpoint별 수집 결과와 최초 관측 시각을 확인하려면 운영 상태와 분리된
디렉터리를 지정해 `observe`를 실행합니다.

```bash
python -m help_me_tibooo observe \
  --shadow-dir .observability/shadow \
  --production-state-path .state/watcher.json
```

`observe`는 Discord 자격 증명이 필요 없고 Discord나 watcher를 호출하지 않습니다.
`--production-state-path`는 운영 상태 파일을 읽기 위한 옵션이 아니라, 출력 경로가 운영
상태·임시 파일·잠금 파일과 심볼릭 링크나 하드 링크로 겹치지 않는지 검사하기 위한
옵션입니다. 지정한 shadow 디렉터리의 `metrics.jsonl`과 `observations.json`에 진단 데이터를
기록하고, 안정적인 잠금용 `.lock`과 원자 저장 중의 `.tmp` companion을 사용합니다.
출력 symlink는 검증된 shadow 내부 target으로 한 번 해석해 같은 잠금 identity를 유지합니다.
인덱스가 손상되어 있으면 과거 최초 관측 시각을 새로 만들지 않고 실패합니다.

기존 감시에 같은 진단을 선택적으로 기록하려면 다음처럼 실행합니다.

```bash
python -m help_me_tibooo watch \
  --state-path .state/watcher.json \
  --require-existing-state \
  --metrics-path .observability/watch.jsonl
```

이 경우 진단 인덱스는 `.observability/watch.observations.json`에 생성됩니다.
`--require-existing-state`는 상태 파일이 없거나 일반 파일이 아니면 수집·발송 전에
실패시킵니다. 상태 잠금은 읽기 전부터 수집·발송과 저장이 끝날 때까지 유지됩니다.
진단 기록 장애는 실제 전송 결과나 watcher 상태 저장을 실패로 바꾸지 않습니다.

## 동작 방식

`codex-reset.com/tibo`의 최신 글 목록을 기존 JSON 피드와 합쳐 수집합니다.
JSON 피드에 없는 최근 글도 기존 `reset` 소스의 기준점을 이어서 처리합니다.
JSON·HTML endpoint의 실패는 각각 진단에 남기되, 둘 중 정상인 endpoint의 게시물은
`reset` 수집 결과에 유지합니다. 두 endpoint 모두 실패하거나 정상 게시물이 없으면 해당
소스는 수집 실패로 처리합니다.

OpenAI·Codex·ChatGPT·GPT·Astra 관련 글은 리셋·한도·출시·요금제·장애 규칙으로
분류합니다. 그 밖의 `OpenAI 소식`은 기능 제공, 대상 사용자·사용 가능 상태, 용량·속도·안정성
개선처럼 본문에 정보가 있는 경우에 알립니다. 제품명·요금제 이름·숫자·이모지만 있는
반응은 알리지 않습니다. DevDay 행사명만 있는 짧은 답글은 기존 정책대로 알립니다.

요금제는 가입·가격·사용 권한의 변경이나 제공 조건을 함께 확인합니다. 일반적인 서버
`access` 언급은 요금제 근거로 쓰지 않습니다. 상류 피드의 `limits` 태그는 한도 표현이나
사용량·용량·속도·배율 문맥이 있을 때만 한도로 인정하며, credits 구매 질문만으로는
알리지 않습니다. 멘션과 URL 안의 단어는 본문 정보 근거에서 제외하지만, `@OpenAI` 등
제품 계정에 대한 구체적인 공지는 분류할 수 있습니다. 분류용 정리는 발송 원문을 바꾸지
않고, 답글 여부나 길이만으로 글을 제외하지 않습니다. 일반 잡담과 단순 리포스트는
제외합니다. 인용된 글·사진·링크 내용에만 관련성이 있고 본문에 단서가 없는 글은 현재
규칙으로 판별하지 못합니다.

실제 공개 피드와 기존 조사에서 보존한 원문은
`tests/fixtures/notification_classification_corpus.json`으로 재생 검증합니다. 동일 ID의
소스별 관측은 독립 표본이 아니며, 이 자료는 규칙 조정에 사용한 회귀 자료입니다.
별도 평가 자료에서 측정한 정확도·누락률을 뜻하지 않습니다.

각 공개 소스가 처음 정상 응답한 실행은 그 소스의 현재 게시물을 기준점으로 저장하고
과거 게시물은 알리지 않습니다. 따라서 한 소스만 먼저 정상화되어도 감시를 시작하고,
나중에 복구된 소스의 과거 글을 한꺼번에 보내지 않습니다. 그다음부터 새 게시물을 오래된
순서로 처리하며, 여러 소스에 같은 게시물이 있으면 한 번만 보냅니다.
`codex-resets.com/api/v1/resets`는 확정된 리셋 기록을 페이지 끝까지 수집합니다.
제공자의 관측 기록은 실제 X 원문 URL이 있으면 그 게시물 ID를 사용하고, 없으면
관측 ID와 제공자 사이트 링크를 유지합니다. 키워드 없는 확정 기록도 리셋으로 분류하지만,
예정 리셋과 AI 예측은 수집하지 않습니다. 상류 X 수집의 완전성이나 지연은 보장되지 않습니다.

전체 소식 소스인 `codex-reset.com`과 TwiScan이 모두 실패하거나 비어 있는 상태가
3회 연속 확인되면 감시 장애 알림을 보냅니다. 새 API만 정상이라면 리셋 수집은 계속하되
전체 소식 감시는 **부분 장애**로 표시합니다. 동일 장애는 시간을 이유로 반복 전송하지
않으며, 안전한 원인 요약 또는 감시 범위가 바뀌면 다시 알립니다.
알림 전송 실패는 다음 실행에서 재시도합니다. 실제 예약 실행이 지연될 수 있으므로
3회 실패 감지에 걸리는 시간은 보장되지 않습니다.

장애 알림 이후 전체 소식 소스 중 하나가 게시물 수집을 재개하면 복구 알림을 한 번 보냅니다.
리셋 API만 정상화된 것은 전체 감시 복구로 알리지 않습니다.
복구 알림 전송에 실패해도 게시물 처리는 계속하고 다음 정상 수집 실행에서 재시도합니다.
재시도 전에 전체 수집 장애가 재발하면 오래된 복구 알림은 취소하고 새 장애를 집계합니다.

장애·복구 알림에는 안전한 원인 요약과 유효한 경우 Actions 실행 로그 링크를 포함합니다.
콘솔의 실행 요약은 수집 성공 여부와 전송 완료한 게시물 알림 수를 구분합니다.
전체 소식 수집 실패와 부분 장애에서는 상태를 저장한 뒤 종료 코드 1을 반환하여
Actions도 실패로 표시합니다. 게시물·알림 전송과 소스 상태는 각각 로그로 확인합니다.

원문이 Discord Embed 한 장의 제한보다 길면 여러 카드로 이어 보내므로 본문을 잘라
버리지 않습니다. 중간 카드에서 전송이 실패하면 다음 실행에서 아직 보내지 못한 카드부터
재개합니다. 원문에 멘션 문법이 있어도 사용자나 역할 알림은 발생하지 않습니다.

응답 형식이 정상이더라도 게시물이 하나도 없으면 최신 기준점을 확인할 수 없으므로 해당
소스는 아직 초기화하지 않습니다. 모든 소스가 비어 있거나 실패한 실행도 연속 감시
실패로 기록합니다. 전체 이력 API인 리셋 소스의 빈 목록도 유효한 기준점을 만들 수 없어
실패로 처리합니다.

기존 버전의 상태 파일은 저장된 마지막 게시물 ID를 공통 기준점으로 사용해 자동
마이그레이션합니다. 최근 중복 확인용 ID는 500개로 제한하지만, 소스별 기준점은 별도로
보존하므로 오래된 게시물이 다시 나타나도 재전송하지 않습니다.
상태 버전 4는 마지막 성공한 장애 알림의 원인·범위와 복구 전송 대기도 저장합니다.
기존 장애 알림 상태는 같은 전체 장애의 중복 알림 없이 마이그레이션합니다.
리셋 기준점·전송 완료 ID는 일반 게시물을 읽은 ID와 별도로 보존하므로, 뒤늦게 확정된
과거 게시물도 한 번 알립니다. 새 리셋 소스의 첫 수집에서만 기존 기록 전체를 기준점으로
등록하고 과거 알림 폭주를 방지합니다. 리셋 API 전체 목록은 최대 10페이지(1,000건)이며
한도를 넘거나 중간 페이지가 실패하면 미수집 기록을 건너뛰지 않도록 소스 실패로 처리합니다.

GitHub Actions의 `watch`·`watch-loop` 실행만 `.state/watcher.json` 캐시를 복원하고 저장합니다.
`test-bot`과 `smoke`는 감시 상태를 읽거나 변경하지 않습니다.

진단 인덱스의 `measurement_epoch`는 해당 파일에서 측정을 시작한 시점입니다.
`first_observed_at`은 공개 소스나 X의 절대 최초 노출 시각이 아니라 이 도구가 처음 파싱한
시각입니다. 원문 시각 근거가 없으면 `origin_at`을 우리의 관측 시각으로 채우지 않으며,
음수 지연은 0으로 보정하지 않고 시각 불일치로 표시합니다. JSONL과 인덱스에는 원문
본문, 원시 응답, 자격 증명을 저장하지 않습니다.

진단 인덱스 v2는 선택한 `origin_at`의 근거를 `origin_time_basis`에 함께 저장합니다.
원문 필드, X ID에서 계산한 시각, 제공자 관측 시각, 근거 미상 순으로 우선하며 더 나은
근거가 들어올 때만 갱신합니다. 같은 우선순위에서는 먼저 선택한 시각을 유지합니다.
`origin_time_bases`는 지금까지 관측한 모든 근거의 목록이며 선택 근거와 구분합니다.
v1 파일은 최초 관측·버전 이력·membership·measurement epoch를 보존해 변환합니다.
v1에는 선택 근거가 없으므로 기존 시각의 근거를 `unknown`으로 두고 다음 관측으로
보강합니다. JSONL의 과거 관측 시각과 근거는 다시 쓰지 않습니다.

## 알려진 제약

- 비공식 공개 피드가 중단되거나 응답 형식이 바뀌면 일부 또는 모든 확인이 실패할 수
  있습니다.
- 규칙 기반 분류이므로 중요하지 않은 글을 알리거나 특이하게 표현된 소식을 놓칠 수
  있습니다.
- GitHub Actions 캐시가 유실되면 반복 감시는 중단됩니다. runner가 강제 종료되면
  마지막 원격 캐시 이후 최대 한 세션의 상태가 유실되어 재전송될 수 있습니다.
- 다음 세션 요청이나 Actions 시작이 지연될 수 있습니다. 연결이 끊기면 예약 실행이
  재시작을 요청하며, 그동안에는 장애·복구 알림도 보낼 수 없습니다.
- 공개 소스는 `curl_cffi`의 Chrome 호환 연결로 수집합니다. 2026-09-16 Actions
  비교에서 HTTPX는 세 소스 모두 Cloudflare 챌린지(403)를 받았고, Chrome 호환
  연결은 같은 실행에서 정상 응답을 받았습니다. Discord 전송은 HTTPX를 사용합니다.
  소스의 접근 정책이 바뀌면 다시 실패할 수 있으며 실제 Actions `smoke`로 확인해야 합니다.
- 첫 마일스톤은 야간 알림 억제를 지원하지 않습니다.
- 첫 마일스톤은 채널 하나만 지원하며 `/status` 같은 명령어를 제공하지 않습니다.
- 이번 관측 단계에서도 기존 watcher의 high-water 기준점과 알림 자격 정책을 그대로
  사용합니다. 후발 게시물 자격 처리와 SQLite 저장은 아직 구현하지 않았습니다.
- HTTP 304 재검증 캐시, VM 배포·120초 timer 전환도 후속 단계입니다. 현재 진단의
  membership overlap은 연속 정상 snapshot 사이에 공통 ID가 있는지만 보여 주며 전체
  타임라인 수집 완전성을 보장하지 않습니다.

## 문제 해결

- `DISCORD_BOT_TOKEN` 또는 `DISCORD_CHANNEL_ID` 환경 변수가 필요하다는 메시지가 나오면
  GitHub Secret과 Variable의 이름 및 저장 위치를 확인합니다.
- `test-bot`이 실패하면 Bot Token이 유효한지, Channel ID가 올바른지, 티보햄에게 해당
  채널의 보기·메시지 보내기 권한이 있는지 확인합니다.
- `smoke`에서 소스가 실패하면 잠시 뒤 다시 실행합니다. 실패가 계속되면 공개 피드의
  서비스 상태나 응답 형식 변경을 확인합니다.

## 라이선스

[MIT License](LICENSE)
