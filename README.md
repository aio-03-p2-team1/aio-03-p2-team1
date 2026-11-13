# 다시 만나

반려동물을 잃어버린 보호자가 구조동물 공고를 검색하고, 닮은 후보와 보호센터 위치를 확인하는 LangGraph 에이전트 서비스입니다.
AIO 3기 단위 프로젝트 2 · 1팀.

- 요구사항: [`prompt.md`](prompt.md) · 작업 규칙: [`AGENTS.md`](AGENTS.md) · 일정·산출물: [`docs/project-context.md`](docs/project-context.md)
- 아키텍처 설계서: [`docs/architecture.md`](docs/architecture.md)
- 시험 결과 보고서: [`docs/test-report.md`](docs/test-report.md)
- **배포 주소: https://dasi-manna.vercel.app** (예전 주소 `vibe-codeing-demo.vercel.app`·`meet-again-team1.vercel.app` 은 이 주소로 넘어갑니다)
- 처음 합류했다면 아래 [팀원용 시작 안내](#팀원용-시작-안내)부터 보세요.

## 팀원용 시작 안내

### 1. 준비물과 권한

| 항목 | 내용 |
| --- | --- |
| 도구 | Git, Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22+, Docker Desktop(로컬 Redis) |
| GitHub | `aio-03-p2-team1` 조직 초대를 수락하면 저장소에 push·PR 할 수 있습니다. |
| 배포·외부 서비스 | Render·Vercel·Supabase·카카오 콘솔은 배포 담당만 접근합니다. 설정 변경이 필요하면 담당자에게 요청합니다. |
| AI 도구 | Claude Code·Codex 등은 저장소의 `AGENTS.md`(Claude Code 는 `CLAUDE.md` 경유)를 자동으로 읽습니다. 따로 지침을 붙여넣지 않아도 됩니다. |

### 2. 처음 실행하기 (키 없이 샘플 데이터로)

```bash
git clone https://github.com/aio-03-p2-team1/aio-03-p2-team1.git
cd aio-03-p2-team1
cp .env.example .env          # 기본값(APP_MODE=local, STORAGE_BACKEND=sqlite) 그대로 두면 됩니다
uv sync
docker compose up -d redis    # 127.0.0.1:6380
uv run uvicorn backend.main:app --reload --port 8000
```

새 터미널에서:

```bash
cd frontend
npm ci
npm run dev                   # http://127.0.0.1:5173
```

- 화면 배지가 **샘플 데이터**로 보이면 정상입니다. 회원가입 후 `우리 아이 찾기`까지 동작합니다.
- 확인: http://127.0.0.1:5173/api/v1/health 가 JSON 을 돌려주면 백엔드 연결이 된 것입니다.

### 3. 실제 데이터로 실행하기 (선택)

| 보고 싶은 것 | 필요한 값 | 넣는 곳 |
| --- | --- | --- |
| 실제 구조동물 공고 | `ANIMAL_API_KEY` (공공데이터포털에서 각자 활용 신청) | 루트 `.env` |
| 보호센터 좌표 | `KAKAO_REST_API_KEY` | 루트 `.env` |
| 카카오 지도·주소 검색 | `VITE_KAKAO_JS_KEY` + 카카오 앱 JavaScript SDK 도메인에 `http://127.0.0.1:5173` 등록 | `frontend/.env.local` |
| LLM 특징 추출 | `APP_MODE=live` + `OPENAI_API_KEY` + Supabase 설정 | 루트 `.env` (보통 로컬에서는 쓰지 않음) |

- 키는 **채팅·노션·Git·문서에 붙여넣지 않습니다.** 공유가 꼭 필요하면 비밀번호 관리자 등 안전한 경로를 씁니다.
- 운영용 Supabase service role 키·OpenAI 키는 배포 서버에만 둡니다.
- 공공데이터 키는 끝에 `_Decoding` 같은 글자를 붙이지 말고 원문만 넣습니다(prompt.md 17장).

### 4. 작업 흐름

1. GitHub Issue 로 할 일을 만들고 담당자를 정합니다.
2. 최신 `main` 에서 브랜치를 만듭니다: `feat/<이슈번호>-<짧은설명>`, `fix/...`, `docs/...`, `test/...`
3. 커밋 메시지는 `feat:` · `fix:` · `docs:` · `test:` · `refactor:` · `chore:` + 한국어 설명.
4. PR 전에 `uv run pytest` 와 `cd frontend && npm test && npm run build` 를 통과시킵니다.
5. PR 양식(`.github/pull_request_template.md`)을 채워 올립니다. CI(`backend`·`frontend`)가 통과하고 **다른 팀원 1명이 승인**해야 병합됩니다. 자기 PR 은 스스로 승인할 수 없습니다.
6. `main` 에 병합되면 Vercel·Render 가 자동으로 다시 배포합니다.

- 상태 객체·도구 스키마·그래프 노드·환경변수 이름·API 계약은 함께 쓰는 부분입니다. 바꾸기 전에 관련 담당자와 이야기하고 `docs/architecture.md` 를 같이 고칩니다.
- 오류를 고치면 `docs/test-report.md` 의 수정 이력에 한 줄 남깁니다(필수 산출물 근거).
- AI 에게 맡길 때는 관련 상태·도구·노드, 수정 범위, 확인할 조건을 함께 알려 줍니다.

### 5. 처음 읽을 문서

1. [`docs/project-context.md`](docs/project-context.md): 일정·평가 기준·필수 산출물
2. [`AGENTS.md`](AGENTS.md): 작업 규칙
3. [`docs/architecture.md`](docs/architecture.md): 그래프·상태·API 구조
4. [`prompt.md`](prompt.md): 요구사항 원문(특히 17장 자주 발생한 오류)

### 6. 자주 막히는 곳

| 증상 | 확인할 것 |
| --- | --- |
| 회원가입·로그인 503 | Docker 의 Redis 가 떠 있는지(`docker compose ps`) |
| 로컬 회원가입 403 `origin_not_allowed` | `.env` 의 `CORS_ORIGINS` 에 `http://localhost:5173`·`http://127.0.0.1:5173` 둘 다 있는지 |
| 배포 화면에서 로그인 403 | 접속한 주소가 Render `CORS_ORIGINS` 에 있는지(새 도메인·Preview 주소는 따로 추가) |
| 지도가 안 뜸 | `VITE_KAKAO_JS_KEY`, 카카오 SDK 도메인 등록, 카카오맵 사용 설정 |
| 공고 API 403 | 공공데이터 키 원문 여부, 활용 신청 승인 여부 |

## 화면

| 경로 | 화면 | 디자인 원본 |
| --- | --- | --- |
| `/` | 전체 공고(카드 목록, 종류·지역·기간 필터) | `img/dasimanna-cards-board.html` |
| `/notices/:id` | 공고 상세(목록 또는 검색 결과에서 이동) | `img/dasimanna-cards-detail.html` |
| `/search` | 우리 아이 찾기(로그인 필요) | `img/dasimanna-cards-search.html` |
| `/login` | 로그인·회원가입 | `img/dasimanna-cards-auth.html` |

## 로컬 실행

필요: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22+, Docker(로컬 Redis).

```bash
cp .env.example .env                  # 값 채우기 (키가 없으면 샘플 데이터로 동작)
uv sync                               # 백엔드 의존성
docker compose up -d redis            # 로컬 Redis 127.0.0.1:6380
uv run uvicorn backend.main:app --reload --port 8000

cd frontend
npm ci
npm run dev                           # http://127.0.0.1:5173 (/api 는 8000 으로 프록시)
```

- `ANIMAL_API_KEY` 가 없으면 화면과 `/api/v1/health` 에 **샘플 데이터**로 표시됩니다. 키가 있으면 local 모드에서도 실제 API 를 조회합니다.
- 로컬 HTTP 에서 `APP_MODE=live` 로 실행하면 `.env` 에 `AUTH_COOKIE_SECURE=false` 를 넣어야 로그인 쿠키가 저장됩니다.
- 카카오 지도: `frontend/.env.local` 에 `VITE_KAKAO_JS_KEY` 를 넣고, 접속 origin 을 카카오 JavaScript SDK 도메인에 등록합니다.

## 시험

```bash
uv run pytest                          # 백엔드 (외부 API 는 모의 응답)
cd frontend && npm test && npm run build
```

## 환경변수

이름과 설명은 [`.env.example`](.env.example)(백엔드), [`frontend/.env.example`](frontend/.env.example)(프론트, 공개 변수)에 있습니다. 비밀 값은 저장소·문서·채팅에 쓰지 않습니다.

## 배포

| 대상 | 플랫폼 | 설정 |
| --- | --- | --- |
| 프론트엔드 | Vercel `aio-03-p2-team1` | Root `frontend`, Install `npm ci`, Build `npm run build`, Output `dist` |
| 백엔드 | Render `aio-03-p2-team1` (`https://aio-03-p2-team1.onrender.com`) | Python 3.12(`.python-version`), Build `pip install uv && uv sync --frozen --no-dev`, Start `uv run --no-sync uvicorn backend.main:app --host 0.0.0.0 --port $PORT`, Health `/api/v1/health` |

- 프론트 주소: `https://dasi-manna.vercel.app` (Vercel 이 `/api/v1/*` 를 Render 로 전달, `frontend/vercel.json`)
  - 예전 주소 `https://vibe-codeing-demo.vercel.app`·`https://meet-again-team1.vercel.app` 은 위 주소로 307 리다이렉트됩니다. Vercel 기본 주소 `https://aio-03-p2-team1-aio-03-p2-team1.vercel.app` 도 같은 배포를 가리킵니다.
- Render `CORS_ORIGINS` 와 카카오 JavaScript SDK 도메인에 프론트 주소를 같은 값으로 등록합니다. Preview·커스텀 도메인은 각각 추가합니다.

## 현재 구현 범위

- 구현: 회원가입·로그인(Redis 세션·HttpOnly 쿠키), 공고 목록·상세, 검색 그래프(질문·조회·정렬·검증·성찰·위치), 실행 이력, 저장 검색·동물 프로필 기억 API
- 미구현: 알림(구독·Discord DM), 사진 분석, 대화 요약, 성찰 전후 평가 실행

## 팀원별 역할과 기여

| 팀원 | 역할 | 기여 |
| --- | --- | --- |
| 변건형 | (작성 예정) | |
| 이서준 | (작성 예정) | |
| 이희래 | (작성 예정) | |
| 최영은 | (작성 예정) | |
