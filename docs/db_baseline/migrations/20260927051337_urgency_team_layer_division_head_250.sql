-- 20260927051337 urgency_team_layer_division_head_250

-- 긴급도 2단계 세션 A 보강 — 실장(팀 없음, 실마다 1명) (2026-09-27 운영자 결정) · Fable 재검토
-- 실장 화면의 등급 = 자기 실 팀들의 팀 등급 중 가장 높은 것(「실 안 각 팀이 고른 중요 뉴스」). 보기만, 고치기·규칙 없음.
alter table public.profiles add column if not exists division text;
comment on column public.profiles.division is '실장 계정의 실(team_id 없음). 값이 있으면 그 실 모든 팀의 팀 등급을 읽는다(보기 전용). team_id가 있는 계정은 쓰지 않음 (#250)';

create or replace function public.my_division() returns text
language sql stable security definer set search_path = public as $$
  select case when team_id is null then division end from profiles where user_id = auth.uid()
$$;

drop policy if exists team_urgency_sel on public.team_urgency;
create policy team_urgency_sel on public.team_urgency for select to authenticated
  using ((select public.is_admin())
    or ((select public.is_approved_user()) and team_id = (select public.my_team()))
    or ((select public.is_approved_user()) and (select public.my_division()) is not null
        and team_id in (select t.id from public.teams t where t.division = (select public.my_division()))));
;
