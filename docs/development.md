# 개발 환경 및 운영 안내

이 문서는 저장소의 기술 스택, 환경변수, 로컬 실행, 배포 설정과 자주 발생하는 설정 오류를 안내한다.

- 에이전트 그래프·상태·도구·API 계약: [architecture.md](architecture.md)
- 일정·평가·필수 산출물: [project-context.md](project-context.md)
- 저장소 작업·협업 규칙: [../AGENTS.md](../AGENTS.md)
- 환경변수 이름과 로컬 기본값: [../.env.example](../.env.example), [../frontend/.env.example](../frontend/.env.example)

## 기술 스택

| 영역 | 기술 |
| --- | --- |
| 프론트엔드 | React 19, React Router 7, Vite 8, Node.js 22+, npm |
| 백엔드 | Python 3.12+, FastAPI, Uvicorn, Pydantic Settings |
| 에이전트·모델 | LangGraph, LangChain `langchain-openai` (`ChatOpenAI`, `OpenAIEmbeddings`; 기본 채팅 모델 `gpt-6-luna`) |
| 데이터 저장 | Supabase 문서 저장소, 로컬 SQLite 대체 저장소 |
| 세션·검색 캐시 | Redis |
| 외부 서비스 | 공공데이터포털 구조동물 API, 카카오 로컬 API·지도 SDK |
| 배포 | Vercel 프론트엔드, Render 백엔드·Redis |

의존성 목록은 백엔드 `pyproject.toml`과 `uv.lock`, 프론트엔드 `frontend/package.json`과 `frontend/package-lock.json`을 기준으로 한다.

## 환경변수

비밀 값은 `.env`(백엔드) 또는 `frontend/.env.local`(프론트엔드)에만 둔다. 실제 값은 문서·Git·로그·채팅에 기록하지 않는다. 프론트엔드의 `VITE_` 변수는 빌드 결과에 포함되어 공개되므로 비밀 키를 넣지 않는다.

### 백엔드

| 변수 | 용도·기본값 |
| --- | --- |
| `APP_MODE` | `local`은 규칙 기반 계획, `live`는 OpenAI·Supabase 연동 모드 |
| `STORAGE_BACKEND` | `sqlite` 또는 `supabase`; 기본 `sqlite` |
| `SQLITE_PATH` | 로컬 DB 경로; 기본 `.data/meet-again.db` |
| `SUPABASE_URL`, `SUPABASE_SCHEMA`, `SUPABASE_SERVICE_ROLE_KEY` | Supabase 주소·스키마·서버 전용 키. live 모드에서 Supabase 사용 시 설정 |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | OpenAI 연결; 모델 기본값 `gpt-6-luna` |
| `LANGSMITH_TRACING` | LangGraph·LangChain 실행 추적 여부; 기본 `false`. `true`면 API 키 필요 |
| `LANGSMITH_API_KEY` | LangSmith 서버 전용 API 키; 추적을 켤 때 설정 |
| `LANGSMITH_PROJECT` | 추적 프로젝트 이름; 기본 `dasimanna` |
| `LANGSMITH_ENDPOINT` | 선택 설정. LangSmith SaaS 외 별도 endpoint를 쓸 때 지정 |
| `ANIMAL_API_KEY` | 공공데이터포털 키. 별칭 `ANIMAL_API_SERVICE_KEY`도 지원하며 두 값이 있으면 이 변수가 우선 |
| `ANIMAL_API_BASE_URL` | 구조동물 API 주소 |
| `KAKAO_REST_API_KEY` | 보호센터 주소의 좌표 변환 |
| `REDIS_URL` | Redis 연결 URL. 로컬 기본 `redis://127.0.0.1:6380/0` |
| `AUTH_SESSION_TTL_SECONDS` | 세션 만료 시간(초); 기본 `86400` |
| `AUTH_COOKIE_SECURE` | 쿠키 Secure 설정. 미설정 시 local은 꺼지고 live는 켜짐 |
| `AUTH_COOKIE_SAMESITE` | 쿠키 SameSite 정책; 기본 `lax` |
| `CORS_ORIGINS` | 허용할 정확한 origin 목록(쉼표 구분, 와일드카드 금지) |
| `MAX_SEARCH_PAGES` | 이전 설정과의 호환용. 현재 검색량을 조절하지 않음 |
| `MAX_REFLECTIONS`, `MAX_TOOL_CALLS`, `REQUEST_TIMEOUT_SECONDS` | 성찰 횟수·도구 호출·요청 제한 설정 |
| `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USER_IDS` | Discord 알림용 이름만 예약되어 있음. 알림 발송 기능은 미구현 |

`APP_MODE=live`에서는 `STORAGE_BACKEND=supabase`, `SUPABASE_SERVICE_ROLE_KEY`, `OPENAI_API_KEY`, `ANIMAL_API_KEY`가 필요하다. 공공데이터 키가 설정되어 있으면 local 모드에서도 실제 공고 API를 호출하며, 키가 없을 때만 샘플 데이터를 사용한다. 외부 API 키가 잘못되었거나 호출에 실패한 경우 샘플 결과로 대체하지 않는다.

### 프론트엔드

| 변수 | 용도·기본값 |
| --- | --- |
| `VITE_API_BASE_URL` | API 기본 경로; 기본 `/api/v1` |
| `VITE_KAKAO_JS_KEY` | 카카오 지도 JavaScript SDK 키 |
| `DEV_API_TARGET` | Vite 개발 프록시의 백엔드 주소; 기본 `http://127.0.0.1:8000` |

## 로컬 실행

필요 도구: Git, Python 3.12+, uv, Node.js 22+, npm, Docker.

```bash
cp .env.example .env
uv sync
docker compose up -d redis
uv run uvicorn backend.main:app --reload --port 8000
```

별도 터미널에서 프론트엔드를 실행한다.

```bash
cd frontend
npm ci
npm run dev
```

화면은 `http://127.0.0.1:5173`, 백엔드는 `http://127.0.0.1:8000`에서 실행한다. Vite 개발 서버가 `/api` 요청을 백엔드로 전달한다. 로그인 기능을 쓰려면 Redis 컨테이너가 실행 중이어야 한다. 프론트엔드에서 `/api/v1/health`를 열어 JSON 응답을 확인할 수 있다.

로컬 검증 명령:

```bash
uv run ruff check backend
uv run pytest backend/tests
cd frontend && npm test && npm run build
```

실행한 검증만 완료했다고 보고한다. 외부 API 모의 검증과 실제 서비스 호출 검증을 구분한다.

### 실제 외부 서비스 연결

- 공공데이터포털 키는 발급된 값 그대로 `ANIMAL_API_KEY`에 설정한다. 키 문자열에 `_Decoding` 등을 덧붙이지 않는다.
- 카카오 REST 키는 백엔드 `.env`의 `KAKAO_REST_API_KEY`에 둔다.
- 카카오 지도 SDK 키는 `frontend/.env.local`의 `VITE_KAKAO_JS_KEY`에 둔다. 접속 origin을 카카오 앱의 JavaScript SDK 도메인에 등록한다.
- LangChain OpenAI 연동은 `OPENAI_API_KEY`가 필요하다. `APP_MODE=live`에서는 Supabase 환경변수도 설정한다. 채팅·사진 분석 클라이언트와 임베딩 클라이언트는 생성자에서 주입할 수 있어 외부 호출 없이 모의 클라이언트로 검증할 수 있다.
- LangSmith 추적은 기본 꺼져 있다. 켜려면 `LANGSMITH_TRACING=true`와 `LANGSMITH_API_KEY`를 설정하고, 필요하면 프로젝트 이름을 `LANGSMITH_PROJECT`로 지정한다. 그래프 입력·출력과 모델 입출력에 검색 서술·공고 데이터가 기록될 수 있으므로 실제 키는 로컬 `.env` 또는 배포 환경변수에만 보관하고 추적 프로젝트 접근 권한을 제한한다. 상세 동작과 데이터 범위는 [architecture.md](architecture.md#51-langsmith-추적)를 참고한다.
- 비밀 값은 팀 채팅이나 저장소에 공유하지 않는다. 운영 비밀 값은 배포 서비스의 환경변수 설정에만 둔다.

### 구조동물 털색 원자료 수집

`uv run python scripts/fetch_animal_color_groups.py`는 설정된 `ANIMAL_API_KEY`로 `abandonmentPublic_v2`를 비동기 조회해 구조일자 월별로 과거 공고를 포함한 고유 동물 최대 50,000건을 임시 SQLite(`/tmp/dasimanna-animal-colors.sqlite3`)에 저장한다. API 문서상 `numOfRows`는 최대 1,000이므로 페이지 요청은 동시 5개로 제한한다. `desertionNo`를 동물 식별자로 사용하며 이미 DB에 있는 ID는 삽입하지 않는다. 경로·수집 상한·시작 연도는 `--db`, `--limit`, `--first-year`로 바꿀 수 있다. CSV는 만들지 않는다.

공식 API 문서는 [공공데이터포털 구조동물 조회 서비스](https://www.data.go.kr/data/15098931/openapi.do)다. 응답 필드 `desertionNo`(유기번호), `colorCd`(털색)는 프로젝트의 실제 API 검증 기록 및 `backend/tools/animal_api.py` 정규화 매핑과 일치한다.

## 배포 설정

| 대상 | 플랫폼 설정 |
| --- | --- |
| 프론트엔드 | Vercel 프로젝트 `aio-03-p2-team1`, Root `frontend`, Install `npm ci`, Build `npm run build`, Output `dist` |
| 백엔드 | Render 서비스 `aio-03-p2-team1`, Python 3.12, `uv sync --frozen --no-dev`, 시작 시 `$PORT`로 Uvicorn 실행, Health Check `/api/v1/health` |
| Redis | Render Key Value. Render에서 제공하는 연결 URL을 `REDIS_URL`로 사용 |

- 프론트 주소는 `https://dasi-manna.vercel.app`, 백엔드 주소는 `https://aio-03-p2-team1.onrender.com`이다.
- 프론트의 `/api/v1/*` 요청은 `frontend/vercel.json`에서 백엔드로 전달한다. 프론트 API 기본 경로는 `/api/v1`로 둔다.
- Render의 `CORS_ORIGINS`와 카카오 JavaScript SDK 도메인에는 실제 프론트 origin을 정확히 등록한다. Preview·커스텀 도메인은 별도로 등록한다.
- 환경변수 변경 후에는 서비스를 재배포해야 반영된다. 배포 성공과 최신 코드·설정 반영 여부를 각각 확인한다.
- 운영은 Supabase와 Render Redis를 사용한다. 임시 파일시스템의 SQLite를 영속 저장소로 사용하지 않는다.

## 자주 발생하는 설정 오류

| 증상 | 확인·조치 |
| --- | --- |
| 공공데이터 API 403 | 키가 발급된 원문인지, 활용 신청이 승인되었는지 확인한다. `_Decoding` 같은 접미사를 붙이지 않는다. |
| 로컬 로그인·회원가입 CORS 403 | 실제 브라우저 origin이 `CORS_ORIGINS`에 있는지 확인한다. localhost와 127.0.0.1은 서로 다른 origin이다. |
| 로컬 로그인 쿠키가 저장되지 않음 | HTTP 로컬 실행에서 live 모드라면 로컬 `.env`에 `AUTH_COOKIE_SECURE=false`를 설정한다. |
| 로그인 API 503 | Redis가 실행 중인지, `REDIS_URL`이 접속 URL인지 확인한다. |
| Render 시작 실패 | 서비스 환경변수와 Render가 제공한 Redis 연결 URL을 확인하고 재배포한다. |
| 배포 화면에서 API 연결 실패 | Vercel rewrite, Render 주소, `CORS_ORIGINS`의 프론트 origin을 확인한다. |
| 카카오 지도 미표시 | `VITE_KAKAO_JS_KEY`, SDK 도메인 등록, 카카오맵 사용 설정을 확인한다. |
| Supabase `PGRST106` | Data API의 Exposed schemas에 지정 스키마가 포함되어 있는지 확인한다. |

