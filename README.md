# Help Me Tibooo

Tibo의 공개 게시물과 답글에서 중요한 OpenAI 소식을 찾아 Discord 채널에 알리는 작은
감시 도구입니다. Codex 사용량 리셋, 한도 변경, 주요 출시, 요금제 변경, 중대한 장애와
복구를 규칙으로 분류합니다. 유료 X API나 언어 모델 API는 사용하지 않습니다.

## 운영 설정

1. Discord에서 `서버 설정 → 연동 → 웹후크 → 새 웹후크`로 이동해 알림을 받을 채널을
   선택하고 웹후크를 만듭니다.
2. GitHub 저장소에서
   `Settings → Secrets and variables → Actions → New repository secret`로 이동합니다.
   Secret 이름을 `DISCORD_WEBHOOK_URL`로 지정하고 Discord에서 복사한 URL을 저장합니다.
3. `Actions → Tibo watcher → Run workflow`에서 `test-discord`를 선택해 연결을
   확인합니다. 테스트가 성공하면 `Help Me Tibooo 테스트 알림`이 한 번 전송됩니다.
4. 예약 실행은 10분마다 요청됩니다. GitHub Actions의 작업량이나 서비스 상태에 따라
   실제 시작 시각은 늦어질 수 있습니다.

웹후크 URL은 저장소 파일, 이슈, 로그에 붙여 넣지 마세요. 노출되었다면 Discord에서
해당 웹후크를 삭제하고 새로 만드세요.

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

`watch`와 `test-discord`에는 실행 환경의 `DISCORD_WEBHOOK_URL`이 필요합니다. 로컬 상태
파일과 웹후크 URL은 커밋하지 마세요.

## 동작 방식

각 공개 소스가 처음 정상 응답한 실행은 그 소스의 현재 게시물을 기준점으로 저장하고
과거 게시물은 알리지 않습니다. 따라서 한 소스만 먼저 정상화되어도 감시를 시작하고,
나중에 복구된 소스의 과거 글을 한꺼번에 보내지 않습니다. 그다음부터 새 게시물을 오래된
순서로 처리하며, 여러 소스에 같은 게시물이 있으면 한 번만 보냅니다. 모든 공개 소스가
3회 연속 실패하면 감시 장애 알림을 한 번 보냅니다.

기존 버전의 상태 파일은 저장된 마지막 게시물 ID를 공통 기준점으로 사용해 자동
마이그레이션합니다. 최근 중복 확인용 ID는 500개로 제한하지만, 소스별 기준점은 별도로
보존하므로 오래된 게시물이 다시 나타나도 재전송하지 않습니다.

GitHub Actions의 `watch` 실행만 `.state/watcher.json` 캐시를 복원하고 저장합니다.
`test-discord`와 `smoke`는 감시 상태를 읽거나 변경하지 않습니다.

## 알려진 제약

- 비공식 공개 피드가 중단되거나 응답 형식이 바뀌면 일부 또는 모든 확인이 실패할 수
  있습니다.
- 규칙 기반 분류이므로 중요하지 않은 글을 알리거나 특이하게 표현된 소식을 놓칠 수
  있습니다.
- GitHub Actions 캐시가 유실되면 다음 정상 실행에서 현재 게시물로 기준점을 다시
  설정합니다. 이때 과거 게시물은 다시 보내지 않습니다.
- 예약 작업은 10분보다 늦게 시작될 수 있습니다.
- 첫 마일스톤은 야간 알림 억제를 지원하지 않습니다.

## 문제 해결

- `DISCORD_WEBHOOK_URL 환경 변수가 필요합니다`가 나오면 GitHub Secret의 이름과 저장
  위치를 확인합니다.
- `test-discord`가 실패하면 Discord에서 웹후크가 삭제되거나 대상 채널 권한이 바뀌지
  않았는지 확인합니다.
- `smoke`에서 소스가 실패하면 잠시 뒤 다시 실행합니다. 실패가 계속되면 공개 피드의
  서비스 상태나 응답 형식 변경을 확인합니다.

## 라이선스

[MIT License](LICENSE)
