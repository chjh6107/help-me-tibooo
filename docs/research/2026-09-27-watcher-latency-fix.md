# 2026-09-27 감시 실행 공백 수정

최근 `watch.yml` 예약 실행 30회를 GitHub CLI로 다시 조회했다. 29개 실행 간격은 최소
132.87분, 중앙 245.45분, 최대 359.47분이다. 전체 실행 소요 중앙은 19초다. 최신 실행은
세 소스 수집 정상·게시물 전송 0건이고 직전 상태 캐시를 복원·저장했다. 새 진단 코드는
배포됐지만 예약 cron은 그대로라 실제 수집 빈도가 바뀌지 않은 상태였다.

[조회 기록](evidence/2026-09-27-watch-runs.json),
[최신 조사 대상 실행](https://github.com/chjh6107/help-me-tibooo/actions/runs/36286311695).

예약 공백이 설정 주기의 두 배인 60분을 넘지 않는지 검사한 결과 assertion이 실패했다.
GitHub 내부에서 각각의 예약이 지연·누락된 이유와 외부 제공자의 최초 공개 시각까지
확정한 것은 아니다. [GitHub schedule 문서](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)는 부하에 따른 지연·누락 가능성을 명시한다.

서버가 없다는 사용자의 답변에 따라 `watch-loop`가 같은 runner에서 120초 간격으로
반복 수집하고, 최대 600초 세션 종료 후 상태 캐시를 확인하고 다음 실행을 요청하도록
변경했다. [GitHub workflow 트리거 문서](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow#triggering-a-workflow-from-a-workflow)의 GITHUB_TOKEN workflow_dispatch 예외를 사용하며 추가 PAT는 필요하지 않다.

상태 부재·예기치 않은 오류는 exit 2로 세션을 중단하고 연결하지 않는다. 수집·전송
실패는 다음 tick에서 재시도하고 완주한 세션은 exit 1로 Actions 실패를 유지한다.
캐시 저장이 확인되지 않으면 다음 실행을 만들지 않는다. 기본 브랜치 외 실행·비공개
저장소·workflow 비활성화에서는 연결하지 않는다. 예약은 연결이 끊겼을 때의 보조 수단이다.

초기 baseline은 pytest 258개 통과. polling/CLI 회귀 11개는 수정 전에 실패했고 구현 후
통과했다. 전체 pytest 269개와 Node 후속 연결 13개가 통과했다. 실제 비발송 smoke는
reset 16개, twiscan 9개, resets 55개를 수집했다.

이 변경은 runner 사용을 상시 사용으로 늘린다. 현재 공개 저장소의 표준 runner를 쓰며
비공개 변경 시 반복 감시를 중단한다. 서버·영속 상태 이전이 장기 운영의 대안이다.
원문→알림 2분이나 전송 exactly-once는 보장하지 않는다. 강제 runner 종료는 마지막
원격 cache 이후 한 세션의 기록을 잃을 수 있다. 상류 인덱싱과 후발 글 기준점 정책도
별도 문제로 남는다. 운영 적용 후 실제 tick 간격과 다음 실행 연결을 검증한다.

독립 리뷰의 feature-branch 중복 발송 경로를 운영 job 시작 조건으로 차단했다.
수동 watch가 pending successor를 대체하지 않도록 concurrency queue:max를 사용하고,
이미 대기 중인 loop가 있으면 새 successor를 추가하지 않는다. queue:max는
[GitHub 공식 concurrency 문서](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency#example-queueing-multiple-pending-runs)에 있는 설정이다. 현재 actionlint 배포판은 이 필드를 아직 인식하지 못해
그 한 개의 schema 진단만 제외하고 나머지 검사를 수행한다. GitHub에서 실제 feature
watch-loop가 skipped 되는지와 smoke/CI가 성공하는지 추가로 검증한다.
