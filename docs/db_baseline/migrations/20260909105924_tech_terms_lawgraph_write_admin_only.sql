-- 20260909105924 tech_terms_lawgraph_write_admin_only

-- #144 (2026-09-09) tech_terms·law_graph_nodes·law_graph_edges 쓰기를 관리자(is_admin)로 한정. custom_knowledge는 승인 프로필 유지(팀원 기여 창구).
-- tech_terms: 추출·백필은 service_role(05:00 스크립트)이라 무관. 화면 쓰기는 관리자 '↺ 재생성'뿐.
-- law_graph: 자문 말미 <lawmap> 자동 축적은 app.js에서 관리자 자문에만 남긴다(과제 1 '제안→승인' 도입 시 승인자용 RPC로 재개방).
drop policy if exists tech_terms_ins on public.tech_terms;
drop policy if exists tech_terms_upd on public.tech_terms;
create policy tech_terms_ins on public.tech_terms for insert to authenticated with check (public.is_admin());
create policy tech_terms_upd on public.tech_terms for update to authenticated using (public.is_admin()) with check (public.is_admin());

drop policy if exists law_graph_nodes_ins on public.law_graph_nodes;
drop policy if exists law_graph_nodes_upd on public.law_graph_nodes;
create policy law_graph_nodes_ins on public.law_graph_nodes for insert to authenticated with check (public.is_admin());
create policy law_graph_nodes_upd on public.law_graph_nodes for update to authenticated using (public.is_admin()) with check (public.is_admin());

drop policy if exists law_graph_edges_ins on public.law_graph_edges;
drop policy if exists law_graph_edges_upd on public.law_graph_edges;
create policy law_graph_edges_ins on public.law_graph_edges for insert to authenticated with check (public.is_admin());
create policy law_graph_edges_upd on public.law_graph_edges for update to authenticated using (public.is_admin()) with check (public.is_admin());;
