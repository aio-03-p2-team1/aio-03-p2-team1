# Supabase 설정 및 운영 안내

이 문서는 로컬·운영 Supabase 연결, 문서 저장소, 게시글 음성 Storage, 품종 데이터 초기화·갱신 절차를 한 곳에 정리한다. 운영은 **Supabase + Render 백엔드·Redis** 기준이다. 품종 자동 갱신 코드 기준 파일은 `backend/main.py`, `backend/tools/kinds.py`, `scripts/refresh_kinds.py`, `.github/workflows/refresh-kinds.yml`이다.

## 0. 로컬 백엔드에서 Supabase 사용

저장소 루트의 `.env`(Git 제외)에 다음 항목을 설정한다. 실제 값은 채팅·문서·저장소에 적지 않는다.

```dotenv
APP_MODE=local
STORAGE_BACKEND=supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SCHEMA=aio-03-p2-team1-demo
SUPABASE_SERVICE_ROLE_KEY=<server-only-key>
```

`SUPABASE_SERVICE_ROLE_KEY`는 FastAPI 서버에만 둔다. 프런트엔드의 `VITE_` 변수로 만들거나 브라우저에 전달하지 않는다. Supabase Dashboard에서 API Exposed schemas에 `SUPABASE_SCHEMA`를 추가하고 2절의 SQL을 실행한다. 로컬 개발을 SQLite로 유지하려면 `STORAGE_BACKEND=sqlite`를 쓰며 음성 파일은 `POST_AUDIO_LOCAL_DIR` 아래에 저장된다.

## 1. 배포만 했는데 품종이 없는 이유

**현재 배포·서버 시작 과정에서는 품종 초기화 스크립트를 자동 실행하지 않는다.**

| 실행 시점 | 실제 동작 |
| --- | --- |
| 백엔드 시작 | 품종 초기화·별도 메모리 적재 없음. 요청 시 공통 캐시 조회 |
| 품종 목록 API 호출 | DB 목록을 조회하고 Redis에 1일 캐시 |
| 품종 갱신 작업 실행 | 마지막 성공 후 7일이 지났거나 성공 기록이 없을 때 외부 API 조회 → DB upsert → Redis 목록 캐시 무효화 |
| 사진 분석 | 셀렉트 API와 동일한 축종별 Redis 목록으로 프롬프트 구성·품종 코드 검증 |

DB 테이블이 없거나 접근할 수 없으면 품종 목록·사진 분석 요청이 오류로 응답한다. 테이블은 있지만 활성 데이터가 없으면 빈 목록이 조회된다. **서버 재시작만으로 빈 DB에 품종이 채워지지는 않는다.**

최초 설정 순서는 **DB 스키마 준비 → 설정값 등록 → 동기화 수동 실행 → DB 확인 → API·화면 확인**이다.

## 2. Supabase 테이블 준비

1. 운영 백엔드가 사용하는 Supabase 프로젝트를 연다.
2. [bootstrap_schema.sql](../scripts/bootstrap_schema.sql)을 SQL Editor에서 검토하고 실행한다. 기존 테이블이 있으면 열·기본키 호환성과 권한 변경 내용을 먼저 확인한다.
3. `kinds`, `kind_aliases` 테이블과 private `post-audio` Storage bucket이 준비됐는지 확인한다. bootstrap SQL은 bucket을 비공개로 설정하고 파일당 10 MiB 및 허용 MIME 목록을 지정한다.
4. Supabase API 설정의 **Exposed schemas**에 백엔드의 `SUPABASE_SCHEMA`와 같은 스키마를 추가한다. [Supabase 공식 안내](https://supabase.com/docs/guides/api/using-custom-schemas)

저장소 bootstrap SQL의 스키마 이름은 `aio-03-p2-team1-demo`로 명시되어 있다. 운영의 `SUPABASE_SCHEMA`가 다르면 SQL의 스키마 식별자를 실제 운영 스키마와 일치시킨 뒤 적용한다. 환경변수만 바꿔도 SQL 안의 스키마 이름이 자동 변경되지는 않는다.

SQL은 서버 전용 `service_role`에 필요한 권한을 부여한다. 브라우저에 서비스 역할 키를 넣거나 익명 사용자에게 품종 테이블 쓰기 권한을 추가하지 않는다.

## 3. 실행 환경별 설정 등록

실제 값은 각 서비스 설정 화면 또는 관리자 PC의 Git에서 제외된 `.env`에만 보관한다. 문서·채팅·소스코드·로그에 키와 Redis 접속 URL을 붙여 넣지 않는다.

### Render 백엔드

백엔드 서비스의 환경변수를 확인한다. 기존 운영 설정은 [development.md](development.md)를 따른다.

| 이름 | 설정 기준 |
| --- | --- |
| `STORAGE_BACKEND` | `supabase` |
| `SUPABASE_URL` | 운영 Supabase 프로젝트 URL |
| `SUPABASE_SCHEMA` | 2절에서 준비한 스키마 이름 |
| `SUPABASE_SERVICE_ROLE_KEY` | 같은 프로젝트의 서버 전용 서비스 역할 키 |
| `ANIMAL_API_KEY` | 구조동물 조회 서비스 사용 권한이 있는 공공데이터 API 키 |
| `REDIS_URL` | 백엔드가 접속할 운영 Redis 연결 URL |

백엔드가 `APP_MODE=live`이면 기존 설정대로 `OPENAI_API_KEY`도 필요하다. 설정값을 변경한 경우 재배포 또는 재시작하여 반영한다.

### GitHub Actions

**Render 환경변수는 GitHub Actions로 자동 전달되지 않는다.** 정기 갱신을 GitHub에서 실행하려면 별도로 등록한다.

1. 저장소의 **Settings → Secrets and variables → Actions → Secrets**를 연다.
2. **New repository secret**으로 다음 5개를 등록한다. 현재 워크플로는 `secrets`에서 읽으므로 일반 Actions Variables에만 등록하면 동작하지 않는다. [GitHub 공식 안내](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)

| Secret 이름 | 넣을 값 |
| --- | --- |
| `ANIMAL_API_KEY` | 운영에서 사용할 공공데이터 API 키 |
| `SUPABASE_URL` | 운영 백엔드와 같은 Supabase 프로젝트 URL |
| `SUPABASE_SCHEMA` | 운영 백엔드와 같은 스키마 이름 |
| `SUPABASE_SERVICE_ROLE_KEY` | 해당 프로젝트의 서버 전용 서비스 역할 키 |
| `REDIS_URL` | 운영 백엔드와 **같은 Redis 인스턴스·DB**로 연결되는 외부 접근용 URL |

워크플로에는 `APP_MODE=local`, `STORAGE_BACKEND=supabase`가 이미 지정되어 있다. 여기서 `local`은 동기화 작업에 OpenAI 설정을 요구하지 않기 위한 값이다. 저장 대상은 위에서 지정한 실제 운영 Supabase다. 이 작업에는 OpenAI 키가 필요하지 않다.

**Redis 연결 구분:** Render 내부 연결 URL은 Render의 같은 사설망에서 사용한다. GitHub 호스팅 실행기는 그 내부 주소에 접속할 수 없으므로, 외부 연결 URL과 해당 실행 환경을 허용하는 접근 설정이 필요하다. Render Key Value의 외부 접근 지원 여부·접근 제어를 확인한다. 외부 접속이 불가능한 환경이면 해당 사설망 안에서 같은 갱신 명령을 실행하도록 운영해야 한다. [Render 공식 안내](https://render.com/docs/key-value)

## 4. 최초 동기화 실행

아래 두 방법 중 **한 가지**를 사용한다.

### 방법 A: GitHub에서 실행

1. [.github/workflows/refresh-kinds.yml](../.github/workflows/refresh-kinds.yml)이 기본 브랜치인 `main`에 반영되어 있는지 확인한다.
2. 저장소 **Actions → Refresh public kinds → Run workflow**를 연다.
3. 실행 브랜치를 `main`으로 선택하고 실행한다.
4. 작업이 성공했는지 확인한 뒤 5절의 DB 건수까지 확인한다.

워크플로 수동 실행에는 저장소 쓰기 권한이 필요하며, `workflow_dispatch`를 사용하는 파일이 기본 브랜치에 있어야 한다. [GitHub 공식 안내](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)

`Validate required configuration`에서 실패하면 출력된 **변수 이름**의 Secret 등록 여부를 확인한다. 값 자체를 로그에 출력하지 않는다.

### 방법 B: 백엔드 실행 환경 또는 관리자 PC에서 실행

운영 DB·Redis·API에 연결할 수 있는 환경에서 저장소 루트로 이동한다. 앞의 설정값을 환경변수나 Git에서 제외된 `.env`에 준비하고 실행한다.

```bash
uv sync --frozen --no-dev
APP_MODE=local STORAGE_BACKEND=supabase uv run --no-sync python -m scripts.refresh_kinds
```

위 환경변수 지정 문법은 bash 기준이다. 관리자 PC에서 실행할 때도 Redis는 운영과 같은 인스턴스·DB여야 하며, 외부 연결이 가능해야 한다.

**주의: 성공 종료가 항상 새 데이터 조회를 뜻하지는 않는다.** `meet-again:kinds:last-refresh`에 최근 7일 이내 성공 기록이 있으면 작업은 동기화를 생략하고 정상 종료한다. 현재 스크립트에는 생략·성공 건수를 출력하는 안내가 없으므로 DB 건수와 갱신 시각을 확인한다. 수동 실행도 이 7일 조건을 따른다.

## 5. DB와 API·화면 확인

Supabase SQL Editor에서 아래를 실행한다. 스키마가 다르면 식별자를 실제 값으로 변경한다.

```sql
select
    species,
    count(*) filter (where active) as active_count,
    max(source_updated_at) as source_updated_at
from "aio-03-p2-team1-demo".kinds
group by species
order by species;
```

축종은 DB에서 `dog`, `cat`, `other`로 저장된다. 웹 API의 `etc`는 DB의 `other`에 대응한다. 기대 건수는 외부 원본에 따라 달라지므로 고정 숫자로 판정하지 않는다. 요청한 축종의 활성 건수가 0이면 초기화 대상·원본 응답·스키마 설정부터 확인한다.

동기화 성공으로 Redis 목록 캐시가 무효화되면 다음 목록 조회·사진 분석에 갱신된 품종이 반영된다. **데이터 반영을 위한 백엔드 재시작은 필요하지 않다.** 이 공통 Redis 캐시 변경 코드의 최초 반영에는 배포가 필요하다.

이후 운영 API에서 목록을 확인한다. 아래 주소는 [development.md](development.md)에 기록된 백엔드 주소이며, 실제 운영 주소가 다르면 바꾼다.

```bash
curl --fail-with-body 'https://aio-03-p2-team1.onrender.com/api/v1/kinds?species=dog'
curl --fail-with-body 'https://aio-03-p2-team1.onrender.com/api/v1/kinds?species=cat'
curl --fail-with-body 'https://aio-03-p2-team1.onrender.com/api/v1/kinds?species=etc'
```

각 응답의 `kinds` 목록에 `kind_code`, `name`, `species`가 있는지 확인한다. 이 API는 로그인 없이 조회할 수 있다.

마지막으로 브라우저 페이지를 새로고침하고 축종을 고른다. 프론트도 품종 목록을 1일간 메모리 캐시하므로, 초기화 전에 빈 목록을 받았던 열린 화면은 새로고침이 필요하다. 화면에는 품종명만 표시되고 검색 요청에는 `criteria.breed_code`가 전송된다.

## 6. 정기 갱신 동작

| 항목 | 현재 설정 |
| --- | --- |
| 워크플로 | `Refresh public kinds` |
| cron | `0 18 * * *` — UTC 매일 18:00, 한국 시간 다음 날 03:00 |
| 실제 데이터 갱신 조건 | 마지막 성공 후 7일 이상 경과 또는 성공 기록 없음 |
| API·DB 재요청 | 최대 3회 재시도, 대기 0.5초 → 1초 → 2초 |
| DB 저장 | 코드 기준 upsert, 원본에서 사라진 품종은 비활성화 |
| 성공 후 처리 | Redis 축종별 목록 캐시 삭제, 마지막 성공 시각 기록 |
| 사진 분석 갱신 | 셀렉트와 같은 Redis 무효화로 다음 요청부터 반영. 재시작 불필요 |

GitHub 예약 실행은 기본 브랜치의 최신 커밋으로 실행되며, 혼잡 시 지연될 수 있다. **매주 특정 요일에 무조건 실행되는 설정이 아니라, 매일 확인하여 7일이 지났을 때 갱신하는 설정**이다. [GitHub 예약 실행 안내](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

## 7. 최근 성공 기록 때문에 초기화가 생략되는 경우

DB가 비어 있거나 복구한 상태인데 최근 성공 기록이 남아 있는 경우에만 아래 절차를 사용한다. 먼저 실행 대상이 운영 DB·Redis인지 확인하고, 다른 갱신 작업이 진행 중이지 않을 때 실행한다.

저장소 루트에서 다음 명령을 실행하면 **품종 마지막 성공 기록 하나만 제거한 뒤** 일반 갱신 작업을 실행한다. 세션·검색 캐시는 삭제하지 않는다.

```bash
APP_MODE=local STORAGE_BACKEND=supabase uv run --no-sync python - <<'PY'
import asyncio
from backend.config import Settings
from redis.asyncio import from_url
from scripts.refresh_kinds import refresh

async def main():
    settings = Settings()
    redis = from_url(settings.redis_url)
    try:
        await redis.delete("meet-again:kinds:last-refresh")
        updated = await refresh(settings, redis)
        print("품종 동기화 실행 완료" if updated else "품종 동기화 생략")
    finally:
        await redis.aclose()

asyncio.run(main())
PY
```

완료 후에는 5절대로 DB 확인 → API 조회 → 브라우저 새로고침을 진행한다.

## 8. 증상별 확인 순서

| 증상 | 확인·조치 |
| --- | --- |
| `kinds_unavailable` | 대상 스키마에 두 품종 테이블이 있는지, Data API 노출과 service_role 권한이 맞는지 확인 |
| `PGRST106` | `SUPABASE_SCHEMA`와 Exposed schemas 일치 확인 |
| `kinds: []` | 해당 축종의 active 건수, 운영 DB·스키마가 실행 환경마다 같은지 확인 |
| 작업 성공인데 데이터가 없음 | 7일 조건으로 생략됐는지 확인. 필요한 경우 7절 수행 |
| DB에는 있는데 API는 빈 목록 | Redis에 이전 빈 목록이 남을 수 있음. 7절 갱신을 통해 무효화하고 API 재확인 |
| API에는 있는데 화면에는 없음 | 브라우저 새로고침 후 축종 재선택 |
| 셀렉트는 정상인데 사진 코드가 반영되지 않음 | 공통 Redis 캐시 변경 코드가 배포됐는지, 사진의 적합성·코드 확신 기준을 통과했는지 확인 |
| Redis 연결 실패 | GitHub에서는 외부 URL·접근 제어 확인. Render에서는 인스턴스·DB 일치와 내부 연결 확인 |
| 공공 API 403 또는 `ANIMAL_API_KEY` 관련 실패 | 사용 신청 승인·키 원문·대상 서비스 확인 |
| `Run workflow`가 보이지 않음 | 기본 브랜치 반영 여부와 Actions 실행 권한 확인 |

`scripts/init_kinds_supabase.py`를 직접 실행하는 별도 경로도 있지만, 이 스크립트 자체는 Redis 무효화와 성공 시각 기록을 하지 않는다. 운영에서는 이 문서의 `scripts.refresh_kinds` 경로를 사용한다.

## 9. 완료 확인표

- [ ] 운영 스키마에 `kinds`, `kind_aliases`가 있다.
- [ ] private `post-audio` bucket이 있고 백엔드 코드의 버킷 상수와 이름이 일치한다.
- [ ] 스키마가 Data API에 노출되어 있고 서비스 역할 권한이 맞다.
- [ ] 백엔드와 갱신 작업이 같은 DB·스키마·Redis DB를 사용한다.
- [ ] GitHub Secrets 5개가 등록되어 있다.
- [ ] 수동 갱신 작업 성공과 DB 활성 건수·갱신 시각을 확인했다.
- [ ] 사진·셀렉트 공통 Redis 캐시 코드가 배포되어 있다.
- [ ] 품종 API와 새로고침한 프론트 셀렉트에서 목록을 확인했다.
- [ ] 정기 실행 결과를 Actions에서 확인할 담당자가 정해져 있다.

이 문서는 설정 절차를 제공한다. 실제 운영 Secrets 등록·동기화·재시작·외부 API 검증을 실행했다는 기록은 아니다.
