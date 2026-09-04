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

예약 실행은 10분마다 요청됩니다. GitHub Actions의 작업량이나 서비스 상태에 따라
실제 시작 시각은 늦어질 수 있습니다.

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

`smoke`는 Discord에 메시지를 보내거나 감시 상태를 변경하지 않고, 두 공개 소스의 정상
여부와 게시물 개수만 출력합니다. 실제 감시는 다음 명령으로 실행할 수 있습니다.

```bash
python -m help_me_tibooo watch --state-path .state/watcher.json
```

`watch`와 `test-bot`에는 실행 환경의 `DISCORD_BOT_TOKEN`과 `DISCORD_CHANNEL_ID`가
필요합니다. 로컬 상태 파일과 Bot Token은 커밋하지 마세요.

## 동작 방식

각 공개 소스가 처음 정상 응답한 실행은 그 소스의 현재 게시물을 기준점으로 저장하고
과거 게시물은 알리지 않습니다. 따라서 한 소스만 먼저 정상화되어도 감시를 시작하고,
나중에 복구된 소스의 과거 글을 한꺼번에 보내지 않습니다. 그다음부터 새 게시물을 오래된
순서로 처리하며, 여러 소스에 같은 게시물이 있으면 한 번만 보냅니다. 모든 공개 소스가
3회 연속 실패하면 감시 장애 알림을 한 번 보냅니다.

원문이 Discord Embed 한 장의 제한보다 길면 여러 카드로 이어 보내므로 본문을 잘라
버리지 않습니다. 원문에 멘션 문법이 있어도 사용자나 역할 알림은 발생하지 않습니다.

응답 형식이 정상이더라도 게시물이 하나도 없으면 최신 기준점을 확인할 수 없으므로 해당
소스는 아직 초기화하지 않습니다. 모든 소스가 비어 있거나 실패한 실행도 연속 감시
실패로 기록합니다.

기존 버전의 상태 파일은 저장된 마지막 게시물 ID를 공통 기준점으로 사용해 자동
마이그레이션합니다. 최근 중복 확인용 ID는 500개로 제한하지만, 소스별 기준점은 별도로
보존하므로 오래된 게시물이 다시 나타나도 재전송하지 않습니다.

GitHub Actions의 `watch` 실행만 `.state/watcher.json` 캐시를 복원하고 저장합니다.
`test-bot`과 `smoke`는 감시 상태를 읽거나 변경하지 않습니다.

## 알려진 제약

- 비공식 공개 피드가 중단되거나 응답 형식이 바뀌면 일부 또는 모든 확인이 실패할 수
  있습니다.
- 규칙 기반 분류이므로 중요하지 않은 글을 알리거나 특이하게 표현된 소식을 놓칠 수
  있습니다.
- GitHub Actions 캐시가 유실되면 다음 정상 실행에서 현재 게시물로 기준점을 다시
  설정합니다. 이때 과거 게시물은 다시 보내지 않습니다.
- 예약 작업은 10분보다 늦게 시작될 수 있습니다.
- 첫 마일스톤은 야간 알림 억제를 지원하지 않습니다.
- 첫 마일스톤은 채널 하나만 지원하며 `/status` 같은 명령어를 제공하지 않습니다.

## 문제 해결

- `DISCORD_BOT_TOKEN` 또는 `DISCORD_CHANNEL_ID` 환경 변수가 필요하다는 메시지가 나오면
  GitHub Secret과 Variable의 이름 및 저장 위치를 확인합니다.
- `test-bot`이 실패하면 Bot Token이 유효한지, Channel ID가 올바른지, 티보햄에게 해당
  채널의 보기·메시지 보내기 권한이 있는지 확인합니다.
- `smoke`에서 소스가 실패하면 잠시 뒤 다시 실행합니다. 실패가 계속되면 공개 피드의
  서비스 상태나 응답 형식 변경을 확인합니다.

## 라이선스

[MIT License](LICENSE)
