-- 20260820115940 auth_rls_policies

-- RLS — 역할별 열람 범위 (본인 / 팀장=자기 팀 / admin=전체)
alter table public.profiles       enable row level security;
alter table public.teams          enable row level security;
alter table public.advisory_usage enable row level security;

-- profiles: 본인·팀장(자기 팀)·admin. INSERT 정책 없음(트리거가 definer로 생성),
-- DELETE 정책 없음(계정은 지우지 않고 active=false로 비활성화)
create policy profiles_sel_self   on public.profiles for select to authenticated
  using (user_id = auth.uid());
create policy profiles_sel_team   on public.profiles for select to authenticated
  using (public.is_leader() and team_id = public.my_team());
create policy profiles_sel_admin  on public.profiles for select to authenticated
  using (public.is_admin());
create policy profiles_upd_admin  on public.profiles for update to authenticated
  using (public.is_admin()) with check (public.is_admin());

-- teams: 로그인 사용자는 이름·한도 열람(한도 표시용), 수정은 admin
create policy teams_sel_auth  on public.teams for select to authenticated using (true);
create policy teams_upd_admin on public.teams for update to authenticated
  using (public.is_admin()) with check (public.is_admin());

-- advisory_usage: 읽기만 역할별로. 쓰기 정책은 두지 않는다 —
-- 차감·환불은 service_role 전용 RPC로만 이뤄져야 클라이언트가 한도를 조작할 수 없다.
create policy usage_sel_self  on public.advisory_usage for select to authenticated
  using (user_id = auth.uid());
create policy usage_sel_team  on public.advisory_usage for select to authenticated
  using (public.is_leader() and user_id in
         (select p.user_id from public.profiles p where p.team_id = public.my_team()));
create policy usage_sel_admin on public.advisory_usage for select to authenticated
  using (public.is_admin());

-- chat_logs: 본인 것 / 팀장은 팀 전체 / admin은 전부.
-- 텔레그램 행은 user_id가 null이라 admin에게만 보인다(요구사항 그대로).
create policy chat_logs_sel_scoped on public.chat_logs for select to authenticated
  using (
    user_id = auth.uid()
    or public.is_admin()
    or (public.is_leader() and user_id in
        (select p.user_id from public.profiles p where p.team_id = public.my_team()))
  );
create policy chat_logs_ins_auth on public.chat_logs for insert to authenticated
  with check (user_id = auth.uid());

-- answer_feedback: 피드백 탭이 비밀번호 RPC 대신 직접 조회로 전환 (admin 전용 유지)
create policy answer_feedback_sel_admin on public.answer_feedback for select to authenticated
  using (public.is_admin());;
