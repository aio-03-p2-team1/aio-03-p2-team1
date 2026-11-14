# 다시 만나

반려동물을 잃어버린 보호자가 구조동물 공고를 검색하고, 닮은 후보와 보호센터 위치를 확인하는 LangGraph 에이전트 서비스입니다.
AIO 3기 단위 프로젝트 2 · 1팀.

- 개발 환경·기술 스택·환경변수·배포: [`docs/development.md`](docs/development.md) · 작업 규칙: [`AGENTS.md`](AGENTS.md) · 일정·산출물: [`docs/project-context.md`](docs/project-context.md)
- 아키텍처 설계서: [`docs/architecture.md`](docs/architecture.md)
- 시험 결과 보고서: [`docs/test-report.md`](docs/test-report.md)
- **배포 주소: https://dasi-manna.vercel.app** (예전 주소 `vibe-codeing-demo.vercel.app`·`meet-again-team1.vercel.app` 은 이 주소로 넘어갑니다)
- 처음 합류했다면 아래 [팀원용 시작 안내](#팀원용-시작-안내)부터 보세요.

## 팀원용 시작 안내

- 개발 도구, 키 없는 로컬 실행, 실제 API 연결, 배포와 문제 해결: [`docs/development.md`](docs/development.md)
- 브랜치·PR·리뷰와 AI 작업 규칙: [`AGENTS.md`](AGENTS.md)
- 일정·평가 기준·필수 산출물: [`docs/project-context.md`](docs/project-context.md)
- 처음에는 키 없이 샘플 데이터로 실행할 수 있다. 상세 절차와 설정은 개발 안내를 따른다.

## 화면

| 경로 | 화면 | 디자인 원본 |
| --- | --- | --- |
| `/` | 전체 공고(카드 목록, 종류·지역·기간 필터) | `img/dasimanna-cards-board.html` |
| `/notices/:id` | 공고 상세(목록 또는 검색 결과에서 이동) | `img/dasimanna-cards-detail.html` |
| `/search` | 우리 아이 찾기(로그인 필요) | `img/dasimanna-cards-search.html` |
| `/my` | 마이페이지(로그인 필요) | `img/dasimanna-cards-my.html` |
| `/board` · `/board/:postId` | 실종 정보 게시판·상세 | `img/dasimanna-cards-board.html` · `img/dasimanna-cards-post-detail.html` |
| `/login` | 로그인·회원가입 | `img/dasimanna-cards-auth.html` |

## 현재 구현 범위

- 구현: 회원가입·로그인(Redis 세션·HttpOnly 쿠키), 공고 목록·상세, 검색 그래프(질문·조회·정렬·검증·성찰·위치), 사진 분석, 실종 정보 게시판, 실행 이력, 저장 검색·동물 프로필 기억 API
- 미구현: 알림(구독·Discord DM), 대화 요약, 성찰 전후 평가 실행

## 팀원별 역할과 기여

| 팀원 | 역할 | 기여 |
| --- | --- | --- |
| 변건형 | (작성 예정) | |
| 이서준 | (작성 예정) | |
| 이희래 | (작성 예정) | |
| 최영은 | (작성 예정) | |

맞춤 검색의 캐시·임베딩 정렬·페이지네이션 동작은 [아키텍처 설계서](docs/architecture.md#10-조건-캐시rrf페이지네이션-v02)에 기록한다.
