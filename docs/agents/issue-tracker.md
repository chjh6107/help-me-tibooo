# 이슈 트래커: GitHub

이 저장소의 이슈와 명세는 GitHub Issues에서 관리한다. 모든 작업에는 `gh` CLI를
사용한다.

## 기본 명령

- 생성: `gh issue create --title "..." --body "..."`
- 조회: `gh issue view <number> --comments`
- 목록: `gh issue list --state open`
- 댓글: `gh issue comment <number> --body "..."`
- 라벨 추가·제거: `gh issue edit <number> --add-label "..."` /
  `--remove-label "..."`
- 종료: `gh issue close <number> --comment "..."`
- 저장소는 현재 clone의 `git remote -v`에서 판별한다.

## Pull Request triage

PR은 triage 요청 표면으로 사용하지 않는다.

## 스킬 연동

- “이슈 트래커에 게시”는 GitHub Issue 생성을 뜻한다.
- “관련 티켓 조회”는 해당 GitHub Issue의 본문·댓글·라벨 조회를 뜻한다.

## Wayfinding 운영

- 지도는 `wayfinder:map` 라벨을 가진 단일 GitHub Issue다.
- 결정 티켓은 지도의 sub-issue로 연결한다.
- 티켓에는 `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`,
  `wayfinder:task` 중 하나를 적용한다.
- sub-issue 기능을 사용할 수 없으면 지도에 task list를 만들고 티켓 본문에
  `Part of #<map>`을 기록한다.
- 티켓 간 차단 관계는 GitHub의 native issue dependencies를 사용한다.
- native dependencies를 사용할 수 없으면 티켓 본문에
  `Blocked by: #<number>`를 기록한다.
- 열린 차단 티켓과 담당자가 없는 첫 번째 티켓이 현재 frontier다.
- 티켓을 시작할 때 `gh issue edit <number> --add-assignee @me`로 먼저 claim한다.
- 해결할 때 답을 댓글로 기록하고 티켓을 닫은 뒤, 지도 `Decisions so far`에
  제목·링크·한 줄 결론을 추가한다.
