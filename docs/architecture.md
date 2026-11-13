# 에이전트 아키텍처 설계서 (초안 v0.1)

> 코드 기준: `backend/agent/graph.py`, `backend/agent/state.py`, `backend/agent/runner.py`
> 노드·상태 필드·도구 스키마가 바뀌면 이 문서를 함께 고친다(AGENTS.md 7).

## 1. 전체 구성

```text
React(Vite) ──/api/v1──▶ FastAPI ──▶ LangGraph 검색 그래프 ──▶ 도구(구조동물 API · 카카오 · OpenAI)
                           │                     │
                           ├─ Redis: 세션·호출 제한   └─ 저장소(SQLite | Supabase documents)
```

| 화면(라우트) | 디자인 원본 | 사용하는 API |
| --- | --- | --- |
| `/` 전체 공고 | `img/dasimanna-cards-board.html` | `GET /notices`, `GET /regions` |
| `/notices/:id` 공고 상세 | `img/dasimanna-cards-detail.html` | `GET /notices/{id}` 또는 `GET /runs/{run_id}` + 위치 API |
| `/search` 우리 아이 찾기(로그인) | `img/dasimanna-cards-search.html` | `POST /photo-analysis`, `POST /searches`, `GET /runs`, `GET /runs/{id}`. 실종 지역은 카카오 지도 모달에서 고른 위치의 시·도를 `/regions` 공식 이름으로 맞춰 `region` 으로, 주소를 `lost_place` 로 보낸다(브라우저 카카오 SDK, `VITE_KAKAO_JS_KEY`) |
| `/my` 마이페이지(로그인) | `img/dasimanna-cards-my.html` | `GET /auth/me`(내 정보: 이름·이메일), `GET /runs?limit=50`(검색 기록). 기록을 누르면 `/search?run=<run_id>` 로 이동해 `GET /runs/{id}` 결과를 다시 보여 준다. 새 API 없음 |
| `/login` 로그인·회원가입 | `img/dasimanna-cards-auth.html` | `/auth/*` |

## 2. StateGraph

```mermaid
flowchart TD
  S([START]) --> A[analyze<br/>요청 분석·입력 검증·세션 조건 병합]
  A -- 필수 누락·입력 오류 --> Q[ask<br/>추가 질문]
  A -- 충분 --> C[context<br/>장기 기억·LLM 특징 추출]
  C -- LLM 오류 --> F
  C --> P[plan<br/>지역 코드 매핑·조회 계획]
  P -- 인자 매핑 실패 --> V
  P --> E[execute<br/>공고 조회·통신 재시도]
  E --> R[rank<br/>필터·점수·정렬]
  R --> V[validate<br/>규칙 기반 검증]
  V -- 문제 있음·성찰 활성·한도 이내 --> X[reflect<br/>원인 분류·수정 전략]
  X -- 재매핑 --> P
  X -- 중복 제거·재정렬 --> R
  X -- 사용자 확인 필요 --> Q
  V -- 통과 --> L[locate<br/>상위 3개 보호센터 좌표]
  V -- 수정 불가·성찰 비활성·한도 초과 --> F
  L --> F[finalize<br/>상위 10개·범위·종료 상태]
  Q --> END1([END awaiting_input])
  F --> END2([END completed / partial / failed])
```

### 노드 입출력과 전이 조건

| 노드 | 읽는 상태 | 갱신 상태 | 다음 노드 |
| --- | --- | --- | --- |
| `analyze` | `request`(+세션 조건) | `criteria`, `missing`, `input_errors`, `questions`, `context_summary.origin` | 누락·오류 → `ask`, 아니면 `context` |
| `ask` | `criteria`, `raw_items` | `status=awaiting_input`, `scope` | END |
| `context` | `criteria`, `profile_id` | 기억으로 선택 항목 보완, `memory_used`, `llm_features`, `error`(LLM) | 오류 → `finalize`, 아니면 `plan` |
| `plan` | `criteria`, `pending_fix` | `criteria.region_code`, `plan`, `issues(arg_mapping)` | 매핑 실패 → `validate`, 아니면 `execute` |
| `execute` | `criteria`, 한도 설정 | `raw_items`, `total_count`, `pages_fetched`, `retry_count`, `error` | `rank` |
| `rank` | `raw_items`, `criteria`, `llm_features`, `pending_fix.dedupe` | `candidates` | `validate` |
| `validate` | `candidates`, `issues`, `error` | `issues` | 아래 표 |
| `reflect` | `issues`, `reflection_count` | `reflections`, `reflection_count`, `pending_fix`, `questions` | `pending_fix.next` |
| `locate` | `candidates[:3]` | `candidates[].location` | `finalize` |
| `finalize` | 전체 | `candidates[:10]`, `scope`, `status`, `end_reason`, `partial` | END |

`validate` 이후: 수정 가능한 문제(`FIXES`)가 없으면 `locate`(오류가 있으면 `finalize`), 성찰이 꺼져 있거나 `reflection_count ≥ MAX_REFLECTIONS` 이면 `finalize`, 그 밖에는 `reflect`.

## 3. 도구 선택 정책

| 상황 | 선택 | 근거 기록 |
| --- | --- | --- |
| 필수 조건(종류·지역·기간) 누락·오류 | 도구 호출 없이 질문 | `questions` |
| 지역이 '전체'가 아님 | `animal_regions` → 공식 시도 코드 매핑 | `tool_calls[].reason` |
| 조건 충분 | `animal_search` 를 페이지 단위로 `MAX_SEARCH_PAGES` 까지 | 페이지·건수 |
| live 모드 + 자유 서술 있음 | `llm_feature_extract` (특징만 구조화) | 모델·프롬프트 버전 |
| 검증 통과 + 카카오 키 + 주소 | 상위 3개만 `kakao_geocode` | 후보 ID |
| 로그인 사용자가 사진 선택 | `photo_analyze` (Pillow 검증 후 OpenAI 비전) | 적합성 판정·특징 JSON |

호출 한도 `MAX_TOOL_CALLS` 를 넘으면 `tool_budget` 으로 멈춘다. 상세·보호센터 전용 공공 API 는 없으므로 검색 응답 필드에서 정규화한다(만들어내지 않음).

### Function Calling 시퀀스 (live 모드)

```mermaid
sequenceDiagram
  participant U as 사용자
  participant API as FastAPI /searches
  participant G as Graph
  participant LLM as OpenAI
  participant AN as 구조동물 API
  participant K as 카카오
  U->>API: 조건 입력
  API->>G: run_search(owner, criteria, thread_id)
  G->>G: analyze (누락이면 질문 후 종료)
  G->>LLM: 서술 → {colors, breed, sex, marks} (JSON)
  LLM-->>G: 특징(설명에 없는 품종은 폐기)
  G->>AN: sido_v2 (지역 코드)
  G->>AN: abandonmentPublic_v2 page 1..N
  AN-->>G: 공고 목록
  G->>G: rank → validate → (reflect)
  G->>K: 상위 3개 보호센터 주소
  K-->>G: 좌표 또는 사유 코드
  G-->>API: run (후보·근거·범위·성찰 기록)
  API-->>U: 결과
```

## 4. 상태 필드

| 이름 | 의미 | 타입 | 초기값 | 갱신 노드 | 영속 |
| --- | --- | --- | --- | --- | --- |
| `run_id` / `thread_id` / `owner` | 실행·세션·소유자 키 | str | runner | runner | run, thread |
| `profile_id` | 장기 기억 동물 프로필 | str \| None | 요청 | — | — |
| `request` | 원 입력 + 세션 조건 | dict | runner | — | — |
| `criteria` | 정규화 조건 | `Criteria` | — | analyze, context, plan | run, thread(기억 출처 제외) |
| `missing` / `input_errors` / `questions` | 누락·오류·질문 | list | [] | analyze, reflect | run, thread |
| `memory_used` | 장기 기억에서 채운 값 | dict | {} | context | run |
| `llm_features` | LLM 추출 특징 | dict | — | context | run |
| `context_summary` | 값 출처, 모델 입력 필드 | dict | — | analyze, context | run |
| `plan` | 조회 계획 | list | — | plan | run |
| `tool_calls` | 도구 호출 기록(누적) | list | [] | plan, execute, context, locate | run |
| `raw_items` / `total_count` / `pages_fetched` / `fetched_at` / `data_source` | 조회 결과·범위 | | — | execute | run(scope) |
| `retry_count` | 통신 실패 재시도 수 | int | 0 | execute | run |
| `candidates` | 후보(점수·근거·위치) | list | — | rank, locate, finalize | run |
| `issues` | 검증 문제 | list | — | plan, validate, reflect, finalize | run |
| `reflection_enabled` | 성찰 사용 여부(평가 변수) | bool | True | — | run |
| `reflection_count` / `reflections` | 판단 오류 수정 횟수·기록(누적) | int / list | 0 / [] | reflect | run |
| `pending_fix` | 다음 수정 지시 | dict \| None | — | reflect, plan, rank, execute | — |
| `status` / `end_reason` / `partial` / `scope` / `error` | 종료 정보 | | — | ask, finalize | run |
| `trace` | 거친 노드 순서(누적) | list | [] | 모든 노드 | run |

## 5. 기억·컨텍스트

- 적용 순서: 현재 요청 → 같은 세션(`thread` 문서) → 장기 기억(`memory` 문서, 선택 특징만) → 기본값. 출처는 `context_summary.origin` 에 남긴다.
- 장기 기억은 사용자가 `PUT /memory` 로 확인한 특징만 저장한다. 검색 범위(종류·지역·기간)는 저장하지 않는다. LLM 추정값은 저장하지 않는다.
- 모델 입력은 자유 서술(최대 1,000자)뿐이다. 이메일·연락처·키는 넣지 않는다.
- 체크포인트: 한 요청 안에서 그래프가 끝까지 실행되고, 추가 질문 상태는 `thread` 문서에 저장되므로 재시작 후 같은 `thread_id` 로 이어 간다.
- 요약 전략(토큰 예산·요약 임계값)은 **미구현**. 현재 LLM 입력은 단일 서술이라 요약이 필요하지 않다. 대화형 입력을 늘리면 추가한다.

## 6. 자가 성찰 (Activity)

```mermaid
flowchart LR
  D[검증에서 문제 감지] --> C{분류}
  C -- arg_mapping --> M[공식 시도 이름으로 재매핑] --> P[plan 재실행]
  C -- arg_mapping 재실패 --> U[사용자에게 지역 질문]
  C -- duplicates --> DD[중복 공고 제거] --> RR[rank 재실행]
  C -- condition_violation --> RF[필터 재적용] --> RR
  C -- empty_narrow --> W[범위 확대 동의 질문]
  C -- tool_error --> STOP[재시도 중단·원인 안내]
  P --> V[같은 검증 반복]
  RR --> V
```

- 통신 실패(타임아웃·네트워크·서버 오류·호출 제한)는 `execute` 안에서 0.5초·1초 백오프로 최대 2회 재시도하고 `retry_count` 로 센다. 판단 오류 수정은 `reflection_count` 로 따로 센다.
- 인증 오류는 재시도하지 않는다. 실패를 샘플 데이터로 덮지 않는다.
- 조건을 조용히 완화하지 않는다. 빈 결과에서 지역 확대는 사용자 확인을 받는다.

## 7. 후보 정렬 규칙

`backend/agent/ranking.py`: 품종 3 · 털색 3 · 성별 2 · 특징 키워드 1(최대 3). 누락 필드는 `unknown`, 다른 값은 `mismatched`. 동점은 점수 → 실종일과 가까운 발견일 → 공고 ID. 상위 10개를 보여 준다. 점수는 같은 동물일 확률이 아니다.

## 8. 백엔드 API 계약 (요약)

| 경로 | 인증 | 주요 오류 코드 |
| --- | --- | --- |
| `GET /health` | 없음 | — |
| `GET /regions` | 없음 | `animal_*` |
| `GET /notices` · `GET /notices/{id}` | 없음 | `animal_*`, `notice_not_cached` (화면 설계로 추가한 조회 전용 경로) |
| `POST /auth/register` · `login` · `GET /auth/me` · `POST /auth/logout` | 쿠키 | `email_taken`, `invalid_credentials`, `login_rate_limited`, `auth_unavailable` |
| `POST /searches` | 필요 | `not_authenticated`, `invalid_request` |
| `POST /photo-analysis` | 필요 | `photo_analysis_not_configured`, `photo_analysis_rate_limited`, `invalid_photo`, `photo_too_large`, `photo_too_many_pixels`, `unsupported_photo_format`, `llm_*` |
| `GET /runs` · `GET /runs/{id}` | 필요(소유자) | `run_not_found` |
| `GET /runs/{id}/candidates/{cid}/location` | 필요(소유자) | `candidate_not_found`, `location_*`(502), `location_rate_limited` |
| `GET/POST /saved-searches` · `DELETE /saved-searches/{key}` | 필요 | `saved_search_not_found` |
| `GET /memory/{pid}` · `PUT /memory` · `DELETE /memory/{pid}` | 필요 | `memory_not_found` |
| `/subscriptions`, `/notifications` | — | **미구현** |

모든 변경 요청은 Origin 을 검사해 `403 origin_not_allowed` 로 막고, 응답에는 `Cache-Control: no-store` 를 붙인다.

## 9. 미구현·미확정

- 알림(구독·Discord DM·발송 이력), 브라우저 푸시
- 대화 요약 전략
- 배포 주소(Render 서비스 URL, Vercel 도메인)와 `vercel.json` API rewrite, 운영 `CORS_ORIGINS`
- 구조동물 API 응답 필드는 문서 기준으로 정규화했고, 실제 키 응답 확인이 필요하다(`docs/test-report.md`).

### 사진 분석 흐름

- 브라우저에서 JPG·PNG·WEBP, 8MB 이하 파일을 고르고 base64 JSON으로 `POST /photo-analysis`에 보낸다. 서버는 인증 사용자별 분당 5회로 제한한다.
- `backend/agent/photo.py`가 Pillow로 실제 포맷·파일 무결성을 확인하고, 픽셀 수가 2,000만을 넘으면 거부한다. 파일은 처리 후 저장하지 않는다.
- `backend/agent/llm.py`의 `PHOTO_SYSTEM_PROMPT`가 동물 존재, 외형 식별 가능 여부, 특정 동물의 중심·구분 가능 여부를 각각 판단한다. 세 조건과 각 자동 입력 특징 신뢰도가 0.8 이상인 값만 반환한다.
- 분석 특징은 검색 폼에 입력되고 사용자가 수정할 수 있다. 낮은 신뢰도·분석 오류는 업로드 영역 아래에 표시한다. 폼 입력에 성공하면 `PhotoFeedbackPopup`이 하단 중앙에 나타난다(데스크톱 50vw, 모바일 80vw). 좋아요·싫어요 값은 현재 화면 상태에만 반영하고 서버에 저장하지 않는다.
- 사진 분석에는 `OPENAI_API_KEY`가 필요하며, local 모드에서도 키가 설정된 경우 사용할 수 있다. 설정이 없으면 503 오류를 반환한다.
