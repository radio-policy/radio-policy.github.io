-- 20260924175345 urgency_rules_table_216

-- #216 (2026-09-25) 뉴스 긴급도 공통 낱말 규칙 층
alter table public.news_feed add column if not exists urgency_rule text;   -- null = 규칙 미적중. authenticated 컬럼 UPDATE(8칸)에 넣지 않음
comment on column public.news_feed.urgency_rule is '적중한 긴급도 낱말 규칙 id(urgency_rules.id). 값이 안 바뀌어도 적중이면 기록 (#216)';

create table public.urgency_rules (
  id          text primary key check (id ~ '^[a-z0-9_]+$'),
  team_id     smallint references public.teams(id),
  position    int  not null default 100,
  mode        text not null check (mode in ('min','set')),
  level       text not null check (level in ('긴급','보통','참고')),
  any_words   jsonb not null check (jsonb_typeof(any_words) = 'array' and jsonb_array_length(any_words) > 0),
  and_any     jsonb not null default '[]' check (jsonb_typeof(and_any) = 'array'),
  none_words  jsonb not null default '[]' check (jsonb_typeof(none_words) = 'array'),
  note        text not null default '',
  enabled     boolean not null default true,
  updated_by  uuid,
  updated_at  timestamptz not null default now()
);
comment on table public.urgency_rules is '뉴스 긴급도 낱말 규칙(#216). team_id null = 공통. 삭제는 enabled=false만(행 삭제 없음), id 영구 불변';

-- updated_at·updated_by는 서버가 채운다(사내 「다르게」 사본이 원본 변경을 이 값으로 알아챈다)
create or replace function public.urgency_rules_touch() returns trigger
language plpgsql set search_path = public as $$
begin
  new.updated_at := now();
  new.updated_by := coalesce(auth.uid(), new.updated_by);
  return new;
end $$;
create trigger urgency_rules_touch before insert or update on public.urgency_rules
  for each row execute function public.urgency_rules_touch();

alter table public.urgency_rules enable row level security;
create policy urgency_rules_sel on public.urgency_rules for select to anon, authenticated using (true);
create policy urgency_rules_ins on public.urgency_rules for insert to authenticated
  with check (is_admin() or (team_id is not null and is_leader() and team_id = my_team()));
create policy urgency_rules_upd on public.urgency_rules for update to authenticated
  using (is_admin() or (team_id is not null and is_leader() and team_id = my_team()))
  with check (is_admin() or (team_id is not null and is_leader() and team_id = my_team()));
-- DELETE 정책 없음(삭제 = enabled=false만)

revoke all on public.urgency_rules from public, anon, authenticated;
grant select on public.urgency_rules to anon;
grant select, insert, update on public.urgency_rules to authenticated;
grant all on public.urgency_rules to service_role;
;
