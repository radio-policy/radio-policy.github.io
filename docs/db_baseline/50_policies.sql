-- policies — tools_db_baseline.py가 실DB에서 생성(손으로 고치지 말 것), 비밀 마스킹됨

create policy usage_sel_admin on public.advisory_usage as PERMISSIVE for SELECT to authenticated
  using (is_admin());

create policy usage_sel_self on public.advisory_usage as PERMISSIVE for SELECT to authenticated
  using ((user_id = auth.uid()));

create policy usage_sel_team on public.advisory_usage as PERMISSIVE for SELECT to authenticated
  using ((is_leader() AND (user_id IN ( SELECT p.user_id
   FROM profiles p
  WHERE (p.team_id = my_team())))));

create policy ai_usage_hour_sel_admin on public.ai_usage_hour as PERMISSIVE for SELECT to authenticated
  using (is_admin());

create policy alert_suppress_log_sel on public.alert_suppress_log as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy answer_feedback_sel_admin on public.answer_feedback as PERMISSIVE for SELECT to authenticated
  using (is_admin());

create policy api_usage_admin_select on public.api_usage as PERMISSIVE for SELECT to authenticated
  using (is_admin());

create policy app_config_ins_admin on public.app_config as PERMISSIVE for INSERT to authenticated
  with check (is_admin());

create policy app_config_sel on public.app_config as PERMISSIVE for SELECT to anon, authenticated
  using ((key <> 'system_prompt'::text));

create policy app_config_upd_admin on public.app_config as PERMISSIVE for UPDATE to authenticated
  using (is_admin())
  with check (is_admin());

create policy assembly_bills_sel on public.assembly_bills as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy assembly_speeches_sel on public.assembly_speeches as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy chat_logs_ins_auth on public.chat_logs as PERMISSIVE for INSERT to authenticated
  with check (((user_id = auth.uid()) AND is_approved_user()));

create policy chat_logs_sel_scoped on public.chat_logs as PERMISSIVE for SELECT to authenticated
  using (((user_id = auth.uid()) OR is_admin() OR (is_leader() AND (user_id IN ( SELECT p.user_id
   FROM profiles p
  WHERE (p.team_id = my_team()))))));

create policy custom_k_del on public.custom_knowledge as PERMISSIVE for DELETE to authenticated
  using (is_approved_user());

create policy custom_k_ins on public.custom_knowledge as PERMISSIVE for INSERT to authenticated
  with check (is_approved_user());

create policy custom_k_sel on public.custom_knowledge as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy custom_k_upd on public.custom_knowledge as PERMISSIVE for UPDATE to authenticated
  using (is_approved_user())
  with check (is_approved_user());

create policy daily_briefings_sel on public.daily_briefings as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy daily_briefings_upd on public.daily_briefings as PERMISSIVE for UPDATE to authenticated
  using (is_approved_user())
  with check (is_approved_user());

create policy deleted_news_ins on public.deleted_news as PERMISSIVE for INSERT to authenticated
  with check (is_admin());

create policy deleted_news_sel on public.deleted_news as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy "Allow anon read" on public.document_chunks as PERMISSIVE for SELECT to public
  using (true);

create policy doc_chunks_ins_approved on public.document_chunks as PERMISSIVE for INSERT to authenticated
  with check (((COALESCE(is_approved, false) = false) AND is_approved_user()));

create policy feedback_rules_sel on public.feedback_rules as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy imp_fb_ins on public.importance_feedback as PERMISSIVE for INSERT to authenticated
  with check (is_admin());

create policy imp_fb_sel on public.importance_feedback as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy imp_fb_upd on public.importance_feedback as PERMISSIVE for UPDATE to authenticated
  using (is_admin())
  with check (is_admin());

create policy issue_links_del on public.issue_links as PERMISSIVE for DELETE to authenticated
  using (is_issue_editor());

create policy issue_links_ins on public.issue_links as PERMISSIVE for INSERT to authenticated
  with check (is_issue_editor());

create policy issue_links_sel on public.issue_links as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy issue_links_upd on public.issue_links as PERMISSIVE for UPDATE to authenticated
  using (is_issue_editor())
  with check (is_issue_editor());

create policy issues_ins on public.issues as PERMISSIVE for INSERT to authenticated
  with check (is_issue_editor());

create policy issues_sel on public.issues as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy issues_upd on public.issues as PERMISSIVE for UPDATE to authenticated
  using (is_issue_editor())
  with check (is_issue_editor());

create policy kb_chunks_anon_select on public.kb_chunks as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy kb_documents_anon_select on public.kb_documents as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy kb_quality_ack_ins_admin on public.kb_quality_ack as PERMISSIVE for INSERT to authenticated
  with check (is_admin());

create policy kb_quality_ack_sel on public.kb_quality_ack as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy law_amendments_sel on public.law_amendments as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy "law_delegations anon select" on public.law_delegations as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy "anon read law_diffs" on public.law_diffs as PERMISSIVE for SELECT to public
  using (true);

create policy law_graph_edges_anon_select on public.law_graph_edges as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy law_graph_edges_ins on public.law_graph_edges as PERMISSIVE for INSERT to authenticated
  with check (is_admin());

create policy law_graph_edges_upd on public.law_graph_edges as PERMISSIVE for UPDATE to authenticated
  using (is_admin())
  with check (is_admin());

create policy law_graph_nodes_anon_select on public.law_graph_nodes as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy law_graph_nodes_ins on public.law_graph_nodes as PERMISSIVE for INSERT to authenticated
  with check (is_admin());

create policy law_graph_nodes_upd on public.law_graph_nodes as PERMISSIVE for UPDATE to authenticated
  using (is_admin())
  with check (is_admin());

create policy law_pending_read on public.law_pending as PERMISSIVE for SELECT to public
  using (true);

create policy law_terms_sel on public.law_terms as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy law_watch_anon_select on public.law_watch as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy lawmap_proposals_del on public.lawmap_proposals as PERMISSIVE for DELETE to authenticated
  using (is_admin());

create policy lawmap_proposals_ins on public.lawmap_proposals as PERMISSIVE for INSERT to authenticated
  with check ((is_approved_user() AND (created_by = auth.uid())));

create policy lawmap_proposals_ins_anon on public.lawmap_proposals as PERMISSIVE for INSERT to anon
  with check (((origin = 'request'::text) AND (status = 'pending'::text) AND (created_by IS NULL) AND (COALESCE(relations, '[]'::jsonb) = '[]'::jsonb) AND (COALESCE(gate, '[]'::jsonb) = '[]'::jsonb) AND (decided_at IS NULL) AND (decided_by IS NULL) AND (decision_note IS NULL) AND (result IS NULL) AND (description IS NULL) AND ((char_length(topic) >= 2) AND (char_length(topic) <= 30)) AND (COALESCE(char_length(question), 0) <= 300) AND (COALESCE(char_length(requester), 0) <= 40)));

create policy lawmap_proposals_sel on public.lawmap_proposals as PERMISSIVE for SELECT to authenticated
  using ((is_admin() OR (created_by = auth.uid())));

create policy lawmap_proposals_upd on public.lawmap_proposals as PERMISSIVE for UPDATE to authenticated
  using (is_admin())
  with check (is_admin());

create policy news_embeddings_sel on public.news_embeddings as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy news_feed_del on public.news_feed as PERMISSIVE for DELETE to authenticated
  using (is_admin());

create policy news_feed_sel on public.news_feed as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy news_feed_upd_auth on public.news_feed as PERMISSIVE for UPDATE to authenticated
  using (is_approved_user())
  with check (is_approved_user());

create policy people_sel on public.people as PERMISSIVE for SELECT to public
  using (true);

create policy people_upd on public.people as PERMISSIVE for UPDATE to authenticated
  using (is_admin())
  with check (is_admin());

create policy profiles_sel_admin on public.profiles as PERMISSIVE for SELECT to authenticated
  using (is_admin());

create policy profiles_sel_self on public.profiles as PERMISSIVE for SELECT to authenticated
  using ((user_id = auth.uid()));

create policy profiles_sel_team on public.profiles as PERMISSIVE for SELECT to authenticated
  using ((is_leader() AND (team_id = my_team())));

create policy profiles_upd_admin on public.profiles as PERMISSIVE for UPDATE to authenticated
  using (is_admin())
  with check (is_admin());

create policy system_health_anon_select on public.system_health as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy teams_sel_auth on public.teams as PERMISSIVE for SELECT to authenticated
  using (true);

create policy teams_upd_admin on public.teams as PERMISSIVE for UPDATE to authenticated
  using (is_admin())
  with check (is_admin());

create policy tech_terms_ins on public.tech_terms as PERMISSIVE for INSERT to authenticated
  with check (is_admin());

create policy tech_terms_sel on public.tech_terms as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy tech_terms_upd on public.tech_terms as PERMISSIVE for UPDATE to authenticated
  using (is_admin())
  with check (is_admin());

create policy urgency_rules_ins on public.urgency_rules as PERMISSIVE for INSERT to authenticated
  with check ((is_admin() OR ((team_id IS NOT NULL) AND is_leader() AND (team_id = my_team()))));

create policy urgency_rules_sel on public.urgency_rules as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy urgency_rules_upd on public.urgency_rules as PERMISSIVE for UPDATE to authenticated
  using ((is_admin() OR ((team_id IS NOT NULL) AND is_leader() AND (team_id = my_team()))))
  with check ((is_admin() OR ((team_id IS NOT NULL) AND is_leader() AND (team_id = my_team()))));

create policy watchdog_targets_sel on public.watchdog_targets as PERMISSIVE for SELECT to anon, authenticated
  using (true);

create policy uploads_del_admin on storage.objects as PERMISSIVE for DELETE to authenticated
  using (((bucket_id = 'uploads'::text) AND is_admin()));

create policy uploads_ins_approved on storage.objects as PERMISSIVE for INSERT to authenticated
  with check (((bucket_id = 'uploads'::text) AND is_approved_user()));

create policy uploads_sel_all on storage.objects as PERMISSIVE for SELECT to anon, authenticated
  using ((bucket_id = 'uploads'::text));
