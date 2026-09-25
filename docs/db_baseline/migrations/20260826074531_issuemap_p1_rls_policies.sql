-- 20260826074531 issuemap_p1_rls_policies

-- 이슈맵 P1 RLS: 조회는 공개(브라우징 공개 원칙), 쓰기는 로그인 사용자만(#104 방향).
-- 승인 파이프·자동 연결은 service key(Edge/Python) 경유라 정책 불요.
create policy issues_sel on issues for select to anon, authenticated using (true);
create policy issues_ins on issues for insert to authenticated with check (true);
create policy issues_upd on issues for update to authenticated using (true) with check (true);

create policy issue_links_sel on issue_links for select to anon, authenticated using (true);
create policy issue_links_ins on issue_links for insert to authenticated with check (true);
create policy issue_links_upd on issue_links for update to authenticated using (true) with check (true);
create policy issue_links_del on issue_links for delete to authenticated using (true);

-- news_embeddings: match_news_semantic RPC(invoker)가 읽을 수 있게 select만 공개, 쓰기는 service 전용
create policy news_embeddings_sel on news_embeddings for select to anon, authenticated using (true);;
