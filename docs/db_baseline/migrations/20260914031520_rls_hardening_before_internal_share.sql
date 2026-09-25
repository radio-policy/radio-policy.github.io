-- 20260914031520 rls_hardening_before_internal_share

-- #1 RLS 없이 노출되던 백업 사본 제거 (코드 참조 0건 확인)
--    CREATE TABLE AS SELECT 로 뜬 사본에는 RLS가 따라오지 않는다.
drop table if exists public.law_graph_edges_bak_20260914;
drop table if exists public.law_graph_nodes_bak_20260914;

-- #1b ai_usage_hour: user_id 가 anon 에게 노출되고 있었다. RLS 켜고 관리자만 열람.
--     charge_ai_usage 는 SECURITY DEFINER 라 권한 회수의 영향을 받지 않는다.
revoke all on public.ai_usage_hour from anon;
revoke all on public.ai_usage_hour from authenticated;
alter table public.ai_usage_hour enable row level security;
grant select on public.ai_usage_hour to authenticated;
create policy ai_usage_hour_sel_admin on public.ai_usage_hour
  for select to authenticated using (is_admin());

-- #2 이슈 쓰기 정책의 리터럴 true -> 승인 회원만.
--    가입이 셀프서비스라, 승인 전 계정도 이슈·링크를 고치고 지울 수 있었다.
alter policy issues_ins on public.issues with check (is_approved_user());
alter policy issues_upd on public.issues using (is_approved_user()) with check (is_approved_user());
alter policy issue_links_ins on public.issue_links with check (is_approved_user());
alter policy issue_links_upd on public.issue_links using (is_approved_user()) with check (is_approved_user());
alter policy issue_links_del on public.issue_links using (is_approved_user());

-- #3 사문화된 anon 수정 정책 제거 (GRANT 에 UPDATE 가 없어 지금은 안 열리지만,
--    나중에 권한 한 줄이면 전면 개방되는 지뢰라 정책 자체를 없앤다)
drop policy if exists news_feed_upd_anon on public.news_feed;;
