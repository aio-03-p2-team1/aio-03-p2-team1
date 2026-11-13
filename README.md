# 다시 만나

반려동물을 잃어버린 보호자가 구조동물 공고를 검색하고, 닮은 후보와 보호센터 위치를 확인하는 LangGraph 에이전트 서비스입니다.
AIO 3기 단위 프로젝트 2 · 1팀.

- 요구사항: [`prompt.md`](prompt.md) · 작업 규칙: [`AGENTS.md`](AGENTS.md) · 일정·산출물: [`docs/project-context.md`](docs/project-context.md)
- 아키텍처 설계서: [`docs/architecture.md`](docs/architecture.md)
- 시험 결과 보고서: [`docs/test-report.md`](docs/test-report.md)

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
| 백엔드 | Render (서비스 확정 대기) | Python 3.12(`.python-version`), Build `pip install uv && uv sync --frozen --no-dev`, Start `uv run --no-sync uvicorn backend.main:app --host 0.0.0.0 --port $PORT`, Health `/api/v1/health` |

배포 주소가 확정되면 `frontend/vercel.json` 에 `/api/v1/:path*` → `https://<Render 주소>/api/v1/:path*` rewrite 를 **SPA fallback 보다 앞에** 추가하고, Render `CORS_ORIGINS` 와 카카오 SDK 도메인을 같은 값으로 맞춥니다.

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
