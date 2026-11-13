# 다시 만나 · LangGraph 도구 목록과 선택 방식

작성일: 2026-11-13 · 기준 커밋: `main` 5c8f661 (PR #5 병합 시점)

- **규칙 라우팅**: 노드 코드가 상태를 보고 정해진 도구를 호출하거나, 조건부 엣지로 다음 노드를 정한다.
- **Function Calling**: LLM이 허용된 도구 목록(스키마)을 보고 하나를 고른다. 선택 결과는 규칙으로 다시 검사한다.

## 1. 도구 전체 표

| # | 도구 | 하는 일 | 호출 위치 | 구현 상태 | 선택 방식 | 이유 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `animal_regions` | 시도 이름 → 공식 코드 | `plan` | 구현됨 | 규칙 라우팅 | 지역 코드가 없을 때만 호출, 판단 여지 없음 |
| 2 | `animal_search` | 구조동물 공고 검색·페이지 순회 | `execute` | 구현됨 | 규칙 라우팅 | 인자는 정규화한 조건에서 생성. LLM이 인자를 만들면 코드 오류 위험 |
| 3 | 통신 재시도 (백오프) | 일시적 장애 시 제한된 재시도 | `execute` 내부 | 구현됨 | 규칙 라우팅 | 판단 문제가 아님. `retry_count`로 따로 집계 |
| 4 | `kakao_geocode` | 보호센터 주소 → 좌표 | `locate` | 구현됨 | 규칙 라우팅 | 상위 3개 후보에 항상 실행 |
| 5 | `llm_feature_extract` | 자유 서술에서 특징 추출 | `context` | 구현됨 | 규칙 라우팅 (내부에서 LLM 사용) | 서술이 있으면 호출 |
| 6 | `memory_lookup` | 확인된 동물 프로필 조회 | `context` | 구현됨 | 규칙 라우팅 | `profile_id`가 있으면 조회 |
| 7 | `memory_save` | 확인된 특징·조건 저장 | 종료 시 | 그래프 안 자동 저장은 확인 필요 (`PUT /memory` API는 있음) | 규칙 라우팅 | 사용자가 확인한 값만 저장 |
| 8 | `extract_photo_features` | 사진에서 특징 추출 (비전 모델) | `context` | 구현 필요 | 규칙 라우팅 | 사진이 있으면 호출. 결과는 추정값(출처=photo, 확인=false) |
| 9 | `check_conflict` | 서술과 사진 특징 충돌 비교 | `analyze` | 구현 필요 | 규칙 (도구 아님) | 두 목록 비교 계산 |
| 10 | `embed_text` + 유사도 | 텍스트 임베딩 기반 후보 정렬 | `rank` 내부 | 구현 필요 | 규칙 (도구 아님) | 점수는 코드로 계산해야 재현 가능 |
| 11 | `board_search` | 목격·보호 게시판 검색 | `plan` → `execute` | 구현 필요, 데이터 출처 미정으로 보류 | Function Calling 후보 | "필요 시" 호출하는 선택 도구 |
| 12 | `remap_region_code` | 지역 코드 재매핑 후 재조회 | `reflect` → `plan` | 규칙으로 구현됨 | Function Calling으로 전환 | 수정 전략 선택 |
| 13 | `rerank_candidates` | 중복 제거·재필터·재정렬 | `reflect` → `rank` | 규칙으로 구현됨 | Function Calling으로 전환 | 수정 전략 선택 |
| 14 | `refetch_pages` | 누락 페이지·필드 재조회 | `reflect` → `execute` | 구현 필요 (엣지만 있고 미사용) | Function Calling | 수정 전략 선택 |
| 15 | `ask_user` | 범위 확대·조건 충돌 사용자 확인 | `reflect` → `ask` | 규칙으로 구현됨 | Function Calling + 규칙 강제 | 범위 확대는 LLM 선택과 무관하게 질문으로 강제 |
| 16 | `stop_with_reason` | 복구 불가 오류로 종료 | `reflect` → `finalize` | 일부 구현 (인증 오류는 라우팅으로 바로 종료) | Function Calling + 규칙 강제 | 인증 오류는 LLM을 거치지 않고 종료 |

**정리:** Function Calling은 `reflect`의 수정 전략 선택(12~16)에 쓴다. 출처가 확정되면 `board_search`(11)도 대상이다. 나머지 도구와 오류 감지(`validate`)는 규칙 라우팅으로 둔다.

## 2. Function Calling 적용 시 안전장치 (`reflect`)

- `MAX_REFLECTIONS`를 넘으면 LLM을 호출하지 않고 바로 종료한다 (`route_after_validate`가 먼저 검사).
- 인증 오류는 LLM 선택과 무관하게 `stop_with_reason`으로 보낸다.
- 범위를 넓히는 선택은 반드시 `ask_user`를 거친다 (조건을 조용히 완화하지 않음).
- 허용 목록 밖의 도구나 잘못된 인자가 오면 `llm_response`로 기록하고 기존 `FIXES` 규칙표로 대신 결정한다. 키가 없는 local 모드도 같은 규칙표를 쓴다.
- LLM 호출도 `tool_calls`에 기록해 `MAX_TOOL_CALLS` 안에서 센다.

## 3. 검토 결과 (코드 정적 검토, 테스트 미실행)

### 제안 구조

- `reflect`에 LLM을 넣어도 반복 상한이 유지되어 무한 루프가 생기지 않는다.
- LLM 실패 시 규칙표로 대체하므로 그래프가 멈추지 않는다.
- 충돌 감지 → 질문 → `END(awaiting_input)` → 답 병합 후 재실행은 기존 `analyze`의 세션 조건 병합으로 처리된다.

### 현재 코드에서 발견한 문제

| # | 문제 | 영향 | 제안 |
| --- | --- | --- | --- |
| 1 | `pages_fetched`가 페이지 상한 도달 시 1 크게 기록됨 (`execute` 루프 끝의 `page += 1`) | 화면·시험 보고서의 조회 범위가 틀림. 기존 테스트가 이 값을 검사하지 않음 | 수정하고 테스트 추가 |
| 2 | `field_missing`이 감지만 되고 `FIXES`와 `finalize` 미해결 목록 어디에도 없음 | 결과가 `completed`로 조용히 넘어감 | `refetch_pages` 또는 부분 결과로 연결 |
| 3 | `rank`가 범위 밖 공고를 이미 걸러 `condition_violation`이 발생할 수 없음 | 성찰 전후 비교에서 이 경로를 보여줄 수 없음 | 실패 주입 시험 추가 |
| 4 | `reflect`가 한 번에 첫 번째 오류만 처리 | 오류 3개 + `MAX_REFLECTIONS=2`면 `partial`로 종료 | 의도라면 설계서에 명시 |
| 5 | 서술 특징 추출 LLM 실패 시 검색 전체가 실패 (`context` → `finalize`) | 선택 정보 실패로 핵심 검색까지 중단 | 특징 없이 계속하고 "특징 미적용" 표시할지 팀 결정 필요 |
