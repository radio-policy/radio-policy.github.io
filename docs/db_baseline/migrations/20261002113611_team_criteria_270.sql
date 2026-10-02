-- 20261002113611 team_criteria_270

-- #270 (2026-10-02, 운영자 결정 「키워드 + 500자 기준문을 받는다, 저장 칸부터」)
-- 팀별 뉴스 기준문·키워드·기사 예 — 팀당 1행. 지금은 저장만 한다(판정에 쓰는 코드 없음).
-- 쓰기 = 관리자만, 읽기 = 관리자 · 그 팀 승인 계정 · 그 실 실장. anon 권한 없음(사내 다리도 안 읽는다).
-- updated_by(계정 uuid)는 authenticated에 열지 않는다(#269 원칙) — 칸 단위 GRANT.

create table public.team_criteria (
  team_id    smallint primary key references public.teams(id) on delete cascade,
  criteria   text not null default '' check (char_length(criteria) <= 500),
  keywords   text[] not null default '{}' check (cardinality(keywords) <= 20),
  examples   text not null default '' check (char_length(examples) <= 1000),
  rev        integer not null default 1,
  updated_at timestamptz not null default now(),
  updated_by uuid
);
comment on table public.team_criteria is '#270 팀별 뉴스 기준문(500자)·키워드(≤20)·기사 예 — 관리자가 넣고 판 번호(rev)는 트리거가 올린다. 옛 판은 team_criteria_history';

create table public.team_criteria_history (
  id          bigint generated always as identity primary key,
  team_id     smallint not null,
  rev         integer not null,
  criteria    text not null,
  keywords    text[] not null,
  examples    text not null,
  updated_at  timestamptz not null,
  updated_by  uuid,
  replaced_at timestamptz not null default now(),
  unique (team_id, rev)
);
comment on table public.team_criteria_history is '#270 team_criteria의 바뀌기 전 판 — 트리거만 쓴다';

-- 정규화(NFC·앞뒤 공백, 키워드는 빈칸·중복 제거, 30자 상한) + 판 번호 + 옛 판 보관.
-- 내용이 그대로인 저장은 판·시각을 바꾸지 않는다. 클라이언트는 rev·updated_*·team_id(갱신 때)를 바꿀 수 없다.
create or replace function public.team_criteria_before()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
declare
  kw text[];
begin
  new.criteria := btrim(normalize(coalesce(new.criteria, ''), NFC));
  new.examples := btrim(normalize(coalesce(new.examples, ''), NFC));
  select coalesce(array_agg(w order by ord), '{}'::text[]) into kw
    from (select distinct on (w) w, ord
            from (select btrim(normalize(x, NFC)) as w, ord
                    from unnest(coalesce(new.keywords, '{}'::text[])) with ordinality as u(x, ord)) s
           where w <> ''
           order by w, ord) d;
  if exists (select 1 from unnest(kw) as k(w) where char_length(w) > 30) then
    raise exception 'TEAM_CRITERIA_KEYWORD_TOO_LONG' using errcode = '22001';
  end if;
  new.keywords := kw;
  if tg_op = 'INSERT' then
    new.rev := 1;
    new.updated_at := now();
    new.updated_by := auth.uid();
  elsif (new.criteria, new.keywords, new.examples) is distinct from (old.criteria, old.keywords, old.examples) then
    insert into public.team_criteria_history (team_id, rev, criteria, keywords, examples, updated_at, updated_by)
      values (old.team_id, old.rev, old.criteria, old.keywords, old.examples, old.updated_at, old.updated_by);
    new.team_id := old.team_id;
    new.rev := old.rev + 1;
    new.updated_at := now();
    new.updated_by := auth.uid();
  else
    new.team_id := old.team_id;
    new.rev := old.rev;
    new.updated_at := old.updated_at;
    new.updated_by := old.updated_by;
  end if;
  return new;
end
$function$;
revoke all on function public.team_criteria_before() from public, anon, authenticated;

create trigger team_criteria_before before insert or update on public.team_criteria
  for each row execute function public.team_criteria_before();

alter table public.team_criteria enable row level security;
alter table public.team_criteria_history enable row level security;

create policy team_criteria_sel on public.team_criteria as permissive for select to authenticated
  using ((select public.is_admin())
         or ((select public.is_approved_user()) and team_id = (select public.my_team()))
         or ((select public.is_approved_user()) and (select public.my_division()) is not null
             and team_id in (select t.id from public.teams t where t.division = (select public.my_division()))));
create policy team_criteria_ins on public.team_criteria as permissive for insert to authenticated
  with check ((select public.is_admin()));
create policy team_criteria_upd on public.team_criteria as permissive for update to authenticated
  using ((select public.is_admin()))
  with check ((select public.is_admin()));
create policy team_criteria_history_sel on public.team_criteria_history as permissive for select to authenticated
  using ((select public.is_admin()));

-- GRANT (#214 — service_role 포함, 역할별로). anon 없음. 삭제 권한 없음(비우려면 빈 글로 저장).
revoke all on public.team_criteria from public, anon, authenticated, service_role;
grant select (team_id, criteria, keywords, examples, rev, updated_at) on public.team_criteria to authenticated;
grant insert (team_id, criteria, keywords, examples) on public.team_criteria to authenticated;
grant update (team_id, criteria, keywords, examples) on public.team_criteria to authenticated;
grant all on public.team_criteria to service_role;

revoke all on public.team_criteria_history from public, anon, authenticated, service_role;
grant select (id, team_id, rev, criteria, keywords, examples, updated_at, replaced_at) on public.team_criteria_history to authenticated;
grant all on public.team_criteria_history to service_role;
revoke all on sequence public.team_criteria_history_id_seq from public, anon, authenticated, service_role;
grant usage, select on sequence public.team_criteria_history_id_seq to service_role;
;
