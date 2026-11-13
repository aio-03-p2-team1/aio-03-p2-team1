-- 다시 만나: Supabase 문서 테이블 (prompt.md 11장)
-- 실행 위치: Supabase SQL Editor. 기존 테이블이 있으면 먼저 열·기본키 호환성을 확인한다.
-- 실행 후 Data API 설정의 Exposed schemas 에 aio-03-p2-team1-demo 를 추가해야 한다(PGRST106 방지).

create schema if not exists "aio-03-p2-team1-demo";

create table if not exists "aio-03-p2-team1-demo".documents (
    owner      text        not null,
    kind       text        not null check (kind in ('identity','thread','memory','saved','run','subscription','notification')),
    id         text        not null,
    data       jsonb       not null,
    updated_at timestamptz not null default now(),
    primary key (owner, kind, id)
);

create index if not exists documents_owner_kind_updated
    on "aio-03-p2-team1-demo".documents (owner, kind, updated_at desc);

-- RLS 를 켜고 공개 정책은 만들지 않는다. service_role 만 접근한다(브라우저는 FastAPI 를 거친다).
alter table "aio-03-p2-team1-demo".documents enable row level security;

revoke all on schema "aio-03-p2-team1-demo" from anon, authenticated;
revoke all on all tables in schema "aio-03-p2-team1-demo" from anon, authenticated;

grant usage on schema "aio-03-p2-team1-demo" to service_role;
grant select, insert, update, delete on "aio-03-p2-team1-demo".documents to service_role;
