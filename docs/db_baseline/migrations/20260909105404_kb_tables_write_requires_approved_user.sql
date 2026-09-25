-- 20260909105404 kb_tables_write_requires_approved_user

-- #143 (2026-09-09) tech_terms·custom_knowledge·law_graph_nodes·law_graph_edges 쓰기를 승인 프로필로 한정.
-- 종전엔 넷 다 anon 포함 INSERT/UPDATE(custom_knowledge는 DELETE까지) 정책이 true — 인터넷 누구나 변조 가능했다.
-- 열람(SELECT)은 그대로 공개. 크롤러·05:00 용어 스크립트·17시 체인은 service_role이라 영향 없음.

-- tech_terms
drop policy if exists tech_terms_ins on public.tech_terms;
drop policy if exists tech_terms_upd on public.tech_terms;
create policy tech_terms_ins on public.tech_terms for insert to authenticated with check (public.is_approved_user());
create policy tech_terms_upd on public.tech_terms for update to authenticated using (public.is_approved_user()) with check (public.is_approved_user());

-- custom_knowledge (팀원 기여 창구 — 승인자 쓰기·수정·삭제)
drop policy if exists custom_k_ins on public.custom_knowledge;
drop policy if exists custom_k_upd on public.custom_knowledge;
drop policy if exists custom_k_del on public.custom_knowledge;
create policy custom_k_ins on public.custom_knowledge for insert to authenticated with check (public.is_approved_user());
create policy custom_k_upd on public.custom_knowledge for update to authenticated using (public.is_approved_user()) with check (public.is_approved_user());
create policy custom_k_del on public.custom_knowledge for delete to authenticated using (public.is_approved_user());

-- law_graph_nodes / law_graph_edges (자문 답변 말미 <lawmap> 자동 축적이 승인자 브라우저에서 돌므로 승인자까지 허용)
drop policy if exists law_graph_nodes_anon_insert on public.law_graph_nodes;
drop policy if exists law_graph_nodes_anon_update on public.law_graph_nodes;
create policy law_graph_nodes_ins on public.law_graph_nodes for insert to authenticated with check (public.is_approved_user());
create policy law_graph_nodes_upd on public.law_graph_nodes for update to authenticated using (public.is_approved_user()) with check (public.is_approved_user());
drop policy if exists law_graph_edges_anon_insert on public.law_graph_edges;
drop policy if exists law_graph_edges_anon_update on public.law_graph_edges;
create policy law_graph_edges_ins on public.law_graph_edges for insert to authenticated with check (public.is_approved_user());
create policy law_graph_edges_upd on public.law_graph_edges for update to authenticated using (public.is_approved_user()) with check (public.is_approved_user());;
