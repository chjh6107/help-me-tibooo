# 수집 관측 1단계 검증 기록

## 범위

이 단계는 소스 응답과 최초 관측을 기록하고, 발송 없이 실행하는 `observe`와 선택형 watch 진단을 제공한다. Actions 실행 주기, 기존 high-water 판정, SQLite 후발 게시물 처리, VM 배포는 후속 단계다. 전체 알림 지연 문제가 해결됐다는 의미가 아니다.

## 실제 공개 소스 관측

스키마 검증 수정 코드 `931ae03`에서 Discord 환경 변수를 제거하고 임시 shadow 폴더에서 `observe`를 두 번 실행했다. 두 실행 모두 exit 0이며 stderr는 비어 있었다.

| 항목 | 결과 |
|---|---|
| reset / twiscan / resets 수집 | 각각 21 / 4 / 53개, 두 실행 동일 |
| 공통 canonical event | 76개 |
| 최초 관측 시각 유지 | 공통 event 76개와 event-version 78개 모두 유지 |
| measurement epoch | 두 실행 동일 |
| 원천 최초 노출 시각 | 알 수 없는 값은 null 유지 |
| source_fetched | 8개 모두 success |
| post_observed / classified | 각각 158개 |
| run_started / run_finished | 각각 2개, run ID 두 개 |
| 본문·자격증명 필드 | index/metrics에 text, body, token, authorization, raw_response, posts 키 없음 |

이 결과는 공개 소스 접근과 진단 저장 경로의 동작 검증이다. 두 번의 짧은 실행으로 인덱싱 지연의 분포나 개선 효과를 추정하지 않는다. 검증 후 임시 폴더를 제거했다. 실운영 상태를 읽거나 변경하지 않았으며 Discord 메시지를 발송하지 않았다.

## 검증 및 리뷰

- 기준 코드: `0e9dfca`; baseline 전체 193개 통과.
- 소스 snapshot: 신규 실패 테스트 7개 확인 후 focused 37개 및 기존 source 회귀 19개 통과. 실제 `smoke`도 기존과 동일한 21/4/53개 수집.
- runtime: 실제 프로세스 간 경합과 경로 별칭 테스트 12개 통과. 심볼릭 링크 출력의 lexical `.tmp`가 운영 상태 hardlink인 경우를 리뷰에서 발견해 차단하고 재검증했다.
- observe/CLI: 실패 테스트 후 focused 64개 통과. 심볼릭 링크 인덱스의 잠금·교체 대상이 실행마다 바뀌는 문제도 회귀 테스트로 고정했다.
- 최종 기능 수정 커밋 `3067c94`에서 부모가 전체 테스트를 직접 실행: **242 passed in 1.80s**.
- `git diff --check 0e9dfca..HEAD`: exit 0, 출력 없음.
- 소스·runtime·관측 명령 독립 리뷰 통과. 관측 명령 리뷰에서 기존 진단 파일의 알 수 없는 필드가 재저장되는 문제를 재현하고, 다섯 고정 스키마 계층에서 추가 필드를 거부하도록 수정했다. 다섯 회귀 테스트와 수정 재리뷰를 통과했다.
- 전체 브랜치 최종 리뷰는 빈 응답의 이전 정상 membership 보존과 미상 원문 시각의 후속 보강 문제 두 건을 재현했다. `3067c94`에서 둘 다 수정했다. 실패 재현 두 건을 확인한 뒤 회귀 테스트 세 건(빈 마지막 페이지의 정상 누적 포함)이 통과했다. 최종 재리뷰에서 두 건 모두 해결됐으며 직접 회귀가 없다고 확인했다.

## 구현 중 판단

- 전체 설계를 한 번에 이행하지 않고 첫 독립 단계인 관측부터 구현했다. 실행 주기와 후발 게시물 처리는 별도 구현이 남는다는 비용이 있다.
- Python에서는 기존 named function과 dataclass 관례를 유지했다. JavaScript용 arrow/interface 규칙을 Python에 번역하지 않았다. 선호가 다르면 스타일 수정이 필요하지만 동작 변경은 아니다.

## 결과물과 운영 상태

- 작업 브랜치: `codex/indexing-observability`.
- 운영 배포, Actions 스케줄 변경, 운영 상태 migration, 실제 Discord 발송은 수행하지 않았다.
- 원래 main checkout의 미추적 문서와 사용자 파일은 그대로 유지했다.
- 테스트와 리뷰의 주요 근거는 이 문서와 커밋 이력에 남기고, 해당 계획의 임시 SDD 작업 자료는 정리했다.
