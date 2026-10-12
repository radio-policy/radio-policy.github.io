-- 20261012050809 issue_link_excludes_20261012

-- #296 (2026-10-12) 이슈맵 — 세션·대시보드가 해제한 연결을 기억하는 표. 자동 제안(issue_suggest.py)·과거 기사 보강
-- (news-archive-search)은 이 쌍을 다시 붙이지 않는다. 사람이 다시 붙이면(ihelp.link_news·대시보드 연결) 그 행을 지운다.
create table public.issue_link_excludes (
  issue_id bigint not null references public.issues(id) on delete cascade,
  item_type text not null,
  item_id text not null,
  reason text,
  excluded_by text,
  created_at timestamptz not null default now(),
  primary key (issue_id, item_type, item_id)
);
comment on table public.issue_link_excludes is '이슈맵 연결 해제 기억(#296) — 자동 연결 경로는 이 (이슈, 항목) 쌍을 다시 넣지 않는다';
alter table public.issue_link_excludes enable row level security;

-- 권한(#214·#295): anon 없음(공개 화면이 볼 필요 없음), 편집자만 읽기·쓰기·지우기, service_role 전부. 시퀀스 없음(복합 PK).
revoke all on public.issue_link_excludes from public, anon, authenticated, service_role;
grant select, insert, delete on public.issue_link_excludes to authenticated;
grant all on public.issue_link_excludes to service_role;

create policy issue_link_excludes_sel on public.issue_link_excludes for select to authenticated using (is_issue_editor());
create policy issue_link_excludes_ins on public.issue_link_excludes for insert to authenticated with check (is_issue_editor());
create policy issue_link_excludes_del on public.issue_link_excludes for delete to authenticated using (is_issue_editor());
;
