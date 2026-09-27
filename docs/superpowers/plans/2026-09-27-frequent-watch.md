# 반복 감시와 실행 연결 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement inline, followed by one independent review.

**Goal:** 서버가 없는 현재 환경에서 수시간 예약 공백을 줄인다.

**Architecture:** 기존 watch/state v4를 그대로 사용해 한 Actions job 안에서 120초 간격으로 600초 동안 수집한다. 상태 cache 저장을 API로 확인한 뒤 기본 브랜치의 다음 watch-loop를 workflow_dispatch로 요청한다. 예약은 연결이 끊겼을 때 재시작 수단이며 정시 실행을 보장하지 않는다.

**Tech Stack:** Python 3.12, pytest, GitHub Actions, github-script, 기존 캐시.

**Spec:** 이 문서의 다음 계약과 사용자의 지연 수정 요청.

## 계약과 범위

- 별도 서버·유료 API·추가 토큰을 요구하지 않는다. 공개 저장소의 표준 runner를 사용한다.
- 동시 watcher는 한 개이며 취소로 기존 writer를 중단하지 않는다.
- 시작 간격을 monotonic 시계로 계산한다. 느린 수집은 겹치거나 밀린 횟수만큼 연속 실행하지 않는다.
- 수집 장애와 Discord 전송 실패는 상태를 보존하고 다음 tick에서 재시도한다. 상태/잠금 등 예기치 않은 오류는 세션을 중단하고 후속 실행을 연결하지 않는다.
- watch-loop는 기존 운영 상태를 필수로 요구한다. 단발 watch는 기존 초기화 동작을 유지한다.
- 마지막 상태를 새 cache key로 저장한 사실을 확인한 뒤에만 다음 job을 요청한다.
- 수동 진단·feature branch·취소된 실행은 운영 연결을 생성하지 않는다. workflow 비활성화와 WATCHER_PAUSED=true로 중지할 수 있다.
- 각 수집의 상태는 로컬에 저장된다. runner가 강제 종료되면 마지막 원격 cache 이후 최대 한 세션의 전송 기록이 유실될 수 있다. 이 보장은 기존 JSON/Actions cache 범위를 넘지 않는다.
- 외부 소스의 인덱싱 지연과 후발 글 자격 정책은 별도이며 이번 실행 공백 수정으로 해결됐다고 주장하지 않는다.
- 24시간 runner 사용으로 전환된다. 저장소를 비공개로 바꾸면 실행 분량 과금/쿼터를 검토하고 연결 감시를 중지한다.

## 구현 및 검증

- [ ] 실제 최근 운영 기록의 공백 검사를 실행해 실패를 확인한다.
- [ ] polling/CLI 테스트: 0/120/240초, 느린 수집, 종료 경계, 실패 뒤 성공·중복 방지, fatal error·상태 부재.
- [ ] polling.py와 watch-loop CLI를 구현한다. 0=정상 세션, 1=완주했지만 실패 tick 존재, 2=미완주/설정 오류.
- [ ] 후속 실행 JS 테스트: cache 없음·잘못된 ref·비활성화·정상 요청. 실제 JS를 외부 API fake로 실행한다.
- [ ] workflow를 갱신한다. 기본 브랜치 checkout, job timeout, 최소 권한, cache→후속 요청 순서, 진단 artifact, pause switch.
- [ ] 전체 pytest, 실제 비발송 smoke, 독립 리뷰를 수행한다.
- [ ] 수정 PR과 검증 결과를 제공한다. 운영 적용 후 반복 수집과 후속 연결을 실제 Actions 기록으로 확인한다.

## 확인 결과

2026-09-27 최근 예약 30회: 간격 최소 132.87분, 중앙 245.45분, 최대 359.47분. 실행 소요 중앙 19초. 60분 이내 공백 assertion 실패. 기존 테스트 baseline은 실행 결과에 기록한다.
