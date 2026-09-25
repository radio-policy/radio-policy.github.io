-- grants — tools_db_baseline.py가 실DB에서 생성(손으로 고치지 말 것), 비밀 마스킹됨

revoke all on public._bak_superseded_emb_20260925 from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public._bak_superseded_emb_20260925 to service_role;

revoke all on public.advisory_usage from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.advisory_usage to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.advisory_usage to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.advisory_usage to service_role;

revoke all on public.ai_usage_hour from public, anon, authenticated, service_role;
grant SELECT on public.ai_usage_hour to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.ai_usage_hour to service_role;

revoke all on public.alert_suppress_log from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.alert_suppress_log to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.alert_suppress_log to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.alert_suppress_log to service_role;

revoke all on sequence public.alert_suppress_log_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.alert_suppress_log_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.alert_suppress_log_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.alert_suppress_log_id_seq to service_role;

revoke all on public.answer_feedback from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.answer_feedback to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.answer_feedback to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.answer_feedback to service_role;

revoke all on sequence public.answer_feedback_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.answer_feedback_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.answer_feedback_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.answer_feedback_id_seq to service_role;

revoke all on public.api_usage from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.api_usage to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.api_usage to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.api_usage to service_role;

revoke all on sequence public.api_usage_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.api_usage_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.api_usage_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.api_usage_id_seq to service_role;

revoke all on public.app_config from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.app_config to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.app_config to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.app_config to service_role;

revoke all on public.assembly_bills from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.assembly_bills to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.assembly_bills to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.assembly_bills to service_role;

revoke all on public.assembly_speeches from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.assembly_speeches to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.assembly_speeches to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.assembly_speeches to service_role;

revoke all on public.changes from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.changes to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.changes to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.changes to service_role;

revoke all on public.chat_logs from public, anon, authenticated, service_role;
grant MAINTAIN, REFERENCES, SELECT, TRIGGER on public.chat_logs to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.chat_logs to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.chat_logs to service_role;

revoke all on public.custom_knowledge from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.custom_knowledge to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.custom_knowledge to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.custom_knowledge to service_role;

revoke all on sequence public.custom_knowledge_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.custom_knowledge_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.custom_knowledge_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.custom_knowledge_id_seq to service_role;

revoke all on public.daily_briefings from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.daily_briefings to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.daily_briefings to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.daily_briefings to service_role;

revoke all on public.daily_briefings_backup from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.daily_briefings_backup to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.daily_briefings_backup to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.daily_briefings_backup to service_role;

revoke all on sequence public.daily_briefings_backup_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.daily_briefings_backup_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.daily_briefings_backup_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.daily_briefings_backup_id_seq to service_role;

revoke all on public.deleted_news from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.deleted_news to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.deleted_news to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.deleted_news to service_role;

revoke all on sequence public.deleted_news_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.deleted_news_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.deleted_news_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.deleted_news_id_seq to service_role;

revoke all on public.document_chunks from public, anon, authenticated, service_role;
grant MAINTAIN, REFERENCES, SELECT, TRIGGER on public.document_chunks to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.document_chunks to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.document_chunks to service_role;

revoke all on sequence public.document_chunks_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.document_chunks_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.document_chunks_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.document_chunks_id_seq to service_role;

revoke all on public.documents from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.documents to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.documents to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.documents to service_role;

revoke all on public.feedback_rules from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.feedback_rules to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.feedback_rules to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.feedback_rules to service_role;

revoke all on public.importance_feedback from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.importance_feedback to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.importance_feedback to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.importance_feedback to service_role;

revoke all on sequence public.importance_feedback_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.importance_feedback_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.importance_feedback_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.importance_feedback_id_seq to service_role;

revoke all on public.issue_links from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.issue_links to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.issue_links to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.issue_links to service_role;

revoke all on sequence public.issue_links_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.issue_links_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.issue_links_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.issue_links_id_seq to service_role;

revoke all on public.issues from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.issues to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.issues to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.issues to service_role;

revoke all on sequence public.issues_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.issues_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.issues_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.issues_id_seq to service_role;

revoke all on public.kb_chunks from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kb_chunks to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kb_chunks to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kb_chunks to service_role;

revoke all on sequence public.kb_chunks_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.kb_chunks_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.kb_chunks_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.kb_chunks_id_seq to service_role;

revoke all on public.kb_documents from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kb_documents to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kb_documents to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kb_documents to service_role;

revoke all on sequence public.kb_documents_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.kb_documents_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.kb_documents_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.kb_documents_id_seq to service_role;

revoke all on public.kb_quality_ack from public, anon, authenticated, service_role;
grant MAINTAIN, REFERENCES, SELECT, TRIGGER on public.kb_quality_ack to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kb_quality_ack to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kb_quality_ack to service_role;

revoke all on public.kb_quality_article_parse from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kb_quality_article_parse to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kb_quality_article_parse to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kb_quality_article_parse to service_role;

revoke all on public.kb_quality_low_docs from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kb_quality_low_docs to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kb_quality_low_docs to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kb_quality_low_docs to service_role;

revoke all on public.kmcc_press_verdict from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kmcc_press_verdict to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kmcc_press_verdict to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.kmcc_press_verdict to service_role;

revoke all on public.law_amendments from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_amendments to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_amendments to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_amendments to service_role;

revoke all on public.law_delegations from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_delegations to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_delegations to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_delegations to service_role;

revoke all on sequence public.law_delegations_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.law_delegations_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.law_delegations_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.law_delegations_id_seq to service_role;

revoke all on public.law_diffs from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_diffs to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_diffs to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_diffs to service_role;

revoke all on sequence public.law_diffs_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.law_diffs_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.law_diffs_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.law_diffs_id_seq to service_role;

revoke all on public.law_graph_edges from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_graph_edges to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_graph_edges to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_graph_edges to service_role;

revoke all on public.law_graph_nodes from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_graph_nodes to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_graph_nodes to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_graph_nodes to service_role;

revoke all on public.law_pending from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_pending to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_pending to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_pending to service_role;

revoke all on sequence public.law_pending_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.law_pending_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.law_pending_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.law_pending_id_seq to service_role;

revoke all on public.law_terms from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_terms to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_terms to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_terms to service_role;

revoke all on sequence public.law_terms_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.law_terms_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.law_terms_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.law_terms_id_seq to service_role;

revoke all on public.law_watch from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_watch to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_watch to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.law_watch to service_role;

revoke all on sequence public.law_watch_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.law_watch_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.law_watch_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.law_watch_id_seq to service_role;

revoke all on public.lawmap_proposals from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.lawmap_proposals to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.lawmap_proposals to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.lawmap_proposals to service_role;

revoke all on public.news_embeddings from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.news_embeddings to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.news_embeddings to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.news_embeddings to service_role;

revoke all on public.news_feed from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE on public.news_feed to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE on public.news_feed to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.news_feed to service_role;

revoke all on public.news_screen_cache from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.news_screen_cache to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.news_screen_cache to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.news_screen_cache to service_role;

revoke all on public.people from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.people to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.people to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.people to service_role;

revoke all on sequence public.people_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.people_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.people_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.people_id_seq to service_role;

revoke all on public.profiles from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.profiles to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.profiles to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.profiles to service_role;

revoke all on public.subscriber_queue from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.subscriber_queue to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.subscriber_queue to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.subscriber_queue to service_role;

revoke all on sequence public.subscriber_queue_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.subscriber_queue_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.subscriber_queue_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.subscriber_queue_id_seq to service_role;

revoke all on public.system_health from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.system_health to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.system_health to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.system_health to service_role;

revoke all on public.system_status from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.system_status to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.system_status to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.system_status to service_role;

revoke all on public.teams from public, anon, authenticated, service_role;
grant MAINTAIN, REFERENCES, SELECT, TRIGGER on public.teams to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.teams to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.teams to service_role;

revoke all on sequence public.teams_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.teams_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.teams_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.teams_id_seq to service_role;

revoke all on public.tech_terms from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.tech_terms to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.tech_terms to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.tech_terms to service_role;

revoke all on public.telegram_subscribers from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.telegram_subscribers to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.telegram_subscribers to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.telegram_subscribers to service_role;

revoke all on public.telegram_updates from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.telegram_updates to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.telegram_updates to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.telegram_updates to service_role;

revoke all on public.telegram_usage from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.telegram_usage to service_role;

revoke all on sequence public.telegram_usage_id_seq from public, anon, authenticated, service_role;
grant SELECT, UPDATE, USAGE on sequence public.telegram_usage_id_seq to anon;
grant SELECT, UPDATE, USAGE on sequence public.telegram_usage_id_seq to authenticated;
grant SELECT, UPDATE, USAGE on sequence public.telegram_usage_id_seq to service_role;

revoke all on public.urgency_rules from public, anon, authenticated, service_role;
grant SELECT on public.urgency_rules to anon;
grant INSERT, SELECT, UPDATE on public.urgency_rules to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.urgency_rules to service_role;

revoke all on public.watchdog_targets from public, anon, authenticated, service_role;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.watchdog_targets to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.watchdog_targets to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.watchdog_targets to service_role;

revoke all on function public.admin_delete_chat_log(p_id uuid) from public, anon, authenticated, service_role;
grant EXECUTE on function public.admin_delete_chat_log(p_id uuid) to anon;
grant EXECUTE on function public.admin_delete_chat_log(p_id uuid) to authenticated;
grant EXECUTE on function public.admin_delete_chat_log(p_id uuid) to public;
grant EXECUTE on function public.admin_delete_chat_log(p_id uuid) to service_role;

revoke all on function public.admin_delete_chat_log_v2(p_id uuid) from public, anon, authenticated, service_role;
grant EXECUTE on function public.admin_delete_chat_log_v2(p_id uuid) to anon;
grant EXECUTE on function public.admin_delete_chat_log_v2(p_id uuid) to authenticated;
grant EXECUTE on function public.admin_delete_chat_log_v2(p_id uuid) to public;
grant EXECUTE on function public.admin_delete_chat_log_v2(p_id uuid) to service_role;

revoke all on function public.admin_delete_custom_file(p_doc_name text) from public, anon, authenticated, service_role;
grant EXECUTE on function public.admin_delete_custom_file(p_doc_name text) to anon;
grant EXECUTE on function public.admin_delete_custom_file(p_doc_name text) to authenticated;
grant EXECUTE on function public.admin_delete_custom_file(p_doc_name text) to public;
grant EXECUTE on function public.admin_delete_custom_file(p_doc_name text) to service_role;

revoke all on function public.admin_delete_kb_document(p_doc_name text) from public, anon, authenticated, service_role;
grant EXECUTE on function public.admin_delete_kb_document(p_doc_name text) to anon;
grant EXECUTE on function public.admin_delete_kb_document(p_doc_name text) to authenticated;
grant EXECUTE on function public.admin_delete_kb_document(p_doc_name text) to public;
grant EXECUTE on function public.admin_delete_kb_document(p_doc_name text) to service_role;

revoke all on function public.admin_get_chat_log(p_id uuid) from public, anon, authenticated, service_role;
grant EXECUTE on function public.admin_get_chat_log(p_id uuid) to anon;
grant EXECUTE on function public.admin_get_chat_log(p_id uuid) to authenticated;
grant EXECUTE on function public.admin_get_chat_log(p_id uuid) to public;
grant EXECUTE on function public.admin_get_chat_log(p_id uuid) to service_role;

revoke all on function public.admin_insert_kb_chunks(p_doc_id bigint, p_contents text[], p_embeddings text[]) from public, anon, authenticated, service_role;
grant EXECUTE on function public.admin_insert_kb_chunks(p_doc_id bigint, p_contents text[], p_embeddings text[]) to anon;
grant EXECUTE on function public.admin_insert_kb_chunks(p_doc_id bigint, p_contents text[], p_embeddings text[]) to authenticated;
grant EXECUTE on function public.admin_insert_kb_chunks(p_doc_id bigint, p_contents text[], p_embeddings text[]) to public;
grant EXECUTE on function public.admin_insert_kb_chunks(p_doc_id bigint, p_contents text[], p_embeddings text[]) to service_role;

revoke all on function public.admin_list_answer_feedback() from public, anon, authenticated, service_role;
grant EXECUTE on function public.admin_list_answer_feedback() to anon;
grant EXECUTE on function public.admin_list_answer_feedback() to authenticated;
grant EXECUTE on function public.admin_list_answer_feedback() to public;
grant EXECUTE on function public.admin_list_answer_feedback() to service_role;

revoke all on function public.admin_list_chat_logs(p_limit integer) from public, anon, authenticated, service_role;
grant EXECUTE on function public.admin_list_chat_logs(p_limit integer) to anon;
grant EXECUTE on function public.admin_list_chat_logs(p_limit integer) to authenticated;
grant EXECUTE on function public.admin_list_chat_logs(p_limit integer) to public;
grant EXECUTE on function public.admin_list_chat_logs(p_limit integer) to service_role;

revoke all on function public.admin_set_kb_approval(p_doc_name text, p_approved boolean) from public, anon, authenticated, service_role;
grant EXECUTE on function public.admin_set_kb_approval(p_doc_name text, p_approved boolean) to anon;
grant EXECUTE on function public.admin_set_kb_approval(p_doc_name text, p_approved boolean) to authenticated;
grant EXECUTE on function public.admin_set_kb_approval(p_doc_name text, p_approved boolean) to public;
grant EXECUTE on function public.admin_set_kb_approval(p_doc_name text, p_approved boolean) to service_role;

revoke all on function public.admin_update_chunk_embeddings(p_ids bigint[], p_embeddings text[]) from public, anon, authenticated, service_role;
grant EXECUTE on function public.admin_update_chunk_embeddings(p_ids bigint[], p_embeddings text[]) to anon;
grant EXECUTE on function public.admin_update_chunk_embeddings(p_ids bigint[], p_embeddings text[]) to authenticated;
grant EXECUTE on function public.admin_update_chunk_embeddings(p_ids bigint[], p_embeddings text[]) to public;
grant EXECUTE on function public.admin_update_chunk_embeddings(p_ids bigint[], p_embeddings text[]) to service_role;

revoke all on function public.admin_upsert_kb_document(p_dedup_key text, p_title text, p_concept_type text, p_family text, p_law_type text, p_law_number text, p_enforcement_date text, p_competent_authority text, p_path text, p_description text, p_body_md text) from public, anon, authenticated, service_role;
grant EXECUTE on function public.admin_upsert_kb_document(p_dedup_key text, p_title text, p_concept_type text, p_family text, p_law_type text, p_law_number text, p_enforcement_date text, p_competent_authority text, p_path text, p_description text, p_body_md text) to anon;
grant EXECUTE on function public.admin_upsert_kb_document(p_dedup_key text, p_title text, p_concept_type text, p_family text, p_law_type text, p_law_number text, p_enforcement_date text, p_competent_authority text, p_path text, p_description text, p_body_md text) to authenticated;
grant EXECUTE on function public.admin_upsert_kb_document(p_dedup_key text, p_title text, p_concept_type text, p_family text, p_law_type text, p_law_number text, p_enforcement_date text, p_competent_authority text, p_path text, p_description text, p_body_md text) to public;
grant EXECUTE on function public.admin_upsert_kb_document(p_dedup_key text, p_title text, p_concept_type text, p_family text, p_law_type text, p_law_number text, p_enforcement_date text, p_competent_authority text, p_path text, p_description text, p_body_md text) to service_role;

revoke all on function public.batch_update_embeddings(p_ids bigint[], p_embeddings text[]) from public, anon, authenticated, service_role;
grant EXECUTE on function public.batch_update_embeddings(p_ids bigint[], p_embeddings text[]) to service_role;

revoke all on function public.charge_ai_usage(p_user uuid, p_kind text) from public, anon, authenticated, service_role;
grant EXECUTE on function public.charge_ai_usage(p_user uuid, p_kind text) to service_role;

revoke all on function public.chat_logs_month_count() from public, anon, authenticated, service_role;
grant EXECUTE on function public.chat_logs_month_count() to anon;
grant EXECUTE on function public.chat_logs_month_count() to authenticated;
grant EXECUTE on function public.chat_logs_month_count() to public;
grant EXECUTE on function public.chat_logs_month_count() to service_role;

revoke all on function public.check_ai_usage_burst() from public, anon, authenticated, service_role;
grant EXECUTE on function public.check_ai_usage_burst() to service_role;

revoke all on function public.check_briefing_health() from public, anon, authenticated, service_role;
grant EXECUTE on function public.check_briefing_health() to service_role;

revoke all on function public.check_news_health() from public, anon, authenticated, service_role;
grant EXECUTE on function public.check_news_health() to service_role;

revoke all on function public.dispatch_github_workflow(p_workflow text) from public, anon, authenticated, service_role;
grant EXECUTE on function public.dispatch_github_workflow(p_workflow text) to service_role;

revoke all on function public.doc_sections(p_doc text, p_ymd text) from public, anon, authenticated, service_role;
grant EXECUTE on function public.doc_sections(p_doc text, p_ymd text) to anon;
grant EXECUTE on function public.doc_sections(p_doc text, p_ymd text) to authenticated;
grant EXECUTE on function public.doc_sections(p_doc text, p_ymd text) to service_role;

revoke all on function public.fetch_pending_articles(p_pairs jsonb, p_limit integer) from public, anon, authenticated, service_role;
grant EXECUTE on function public.fetch_pending_articles(p_pairs jsonb, p_limit integer) to anon;
grant EXECUTE on function public.fetch_pending_articles(p_pairs jsonb, p_limit integer) to authenticated;
grant EXECUTE on function public.fetch_pending_articles(p_pairs jsonb, p_limit integer) to public;
grant EXECUTE on function public.fetch_pending_articles(p_pairs jsonb, p_limit integer) to service_role;

revoke all on function public.get_my_quota() from public, anon, authenticated, service_role;
grant EXECUTE on function public.get_my_quota() to anon;
grant EXECUTE on function public.get_my_quota() to authenticated;
grant EXECUTE on function public.get_my_quota() to public;
grant EXECUTE on function public.get_my_quota() to service_role;

revoke all on function public.gh_api_get(p_path text) from public, anon, authenticated, service_role;
grant EXECUTE on function public.gh_api_get(p_path text) to service_role;

revoke all on function public.handle_new_user() from public, anon, authenticated, service_role;
grant EXECUTE on function public.handle_new_user() to anon;
grant EXECUTE on function public.handle_new_user() to authenticated;
grant EXECUTE on function public.handle_new_user() to public;
grant EXECUTE on function public.handle_new_user() to service_role;

revoke all on function public.insert_kb_chunks(p_doc_id bigint, p_contents text[], p_embeddings text[]) from public, anon, authenticated, service_role;
grant EXECUTE on function public.insert_kb_chunks(p_doc_id bigint, p_contents text[], p_embeddings text[]) to anon;
grant EXECUTE on function public.insert_kb_chunks(p_doc_id bigint, p_contents text[], p_embeddings text[]) to authenticated;
grant EXECUTE on function public.insert_kb_chunks(p_doc_id bigint, p_contents text[], p_embeddings text[]) to public;
grant EXECUTE on function public.insert_kb_chunks(p_doc_id bigint, p_contents text[], p_embeddings text[]) to service_role;

revoke all on function public.is_admin() from public, anon, authenticated, service_role;
grant EXECUTE on function public.is_admin() to anon;
grant EXECUTE on function public.is_admin() to authenticated;
grant EXECUTE on function public.is_admin() to public;
grant EXECUTE on function public.is_admin() to service_role;

revoke all on function public.is_approved_user() from public, anon, authenticated, service_role;
grant EXECUTE on function public.is_approved_user() to anon;
grant EXECUTE on function public.is_approved_user() to authenticated;
grant EXECUTE on function public.is_approved_user() to public;
grant EXECUTE on function public.is_approved_user() to service_role;

revoke all on function public.is_issue_editor() from public, anon, authenticated, service_role;
grant EXECUTE on function public.is_issue_editor() to anon;
grant EXECUTE on function public.is_issue_editor() to authenticated;
grant EXECUTE on function public.is_issue_editor() to public;
grant EXECUTE on function public.is_issue_editor() to service_role;

revoke all on function public.is_leader() from public, anon, authenticated, service_role;
grant EXECUTE on function public.is_leader() to anon;
grant EXECUTE on function public.is_leader() to authenticated;
grant EXECUTE on function public.is_leader() to public;
grant EXECUTE on function public.is_leader() to service_role;

revoke all on function public.kb_doc_names(p_status text, p_category text) from public, anon, authenticated, service_role;
grant EXECUTE on function public.kb_doc_names(p_status text, p_category text) to service_role;

revoke all on function public.law_track_recent(p_days integer, p_limit integer) from public, anon, authenticated, service_role;
grant EXECUTE on function public.law_track_recent(p_days integer, p_limit integer) to anon;
grant EXECUTE on function public.law_track_recent(p_days integer, p_limit integer) to authenticated;
grant EXECUTE on function public.law_track_recent(p_days integer, p_limit integer) to public;
grant EXECUTE on function public.law_track_recent(p_days integer, p_limit integer) to service_role;

revoke all on function public.lawmap_snapshot() from public, anon, authenticated, service_role;
grant EXECUTE on function public.lawmap_snapshot() to anon;
grant EXECUTE on function public.lawmap_snapshot() to authenticated;
grant EXECUTE on function public.lawmap_snapshot() to public;
grant EXECUTE on function public.lawmap_snapshot() to service_role;

revoke all on function public.limit_anon_lawmap_request() from public, anon, authenticated, service_role;
grant EXECUTE on function public.limit_anon_lawmap_request() to anon;
grant EXECUTE on function public.limit_anon_lawmap_request() to authenticated;
grant EXECUTE on function public.limit_anon_lawmap_request() to public;
grant EXECUTE on function public.limit_anon_lawmap_request() to service_role;

revoke all on function public.list_kb_documents() from public, anon, authenticated, service_role;
grant EXECUTE on function public.list_kb_documents() to anon;
grant EXECUTE on function public.list_kb_documents() to authenticated;
grant EXECUTE on function public.list_kb_documents() to public;
grant EXECUTE on function public.list_kb_documents() to service_role;

revoke all on function public.list_kb_guide_docs() from public, anon, authenticated, service_role;
grant EXECUTE on function public.list_kb_guide_docs() to anon;
grant EXECUTE on function public.list_kb_guide_docs() to authenticated;
grant EXECUTE on function public.list_kb_guide_docs() to public;
grant EXECUTE on function public.list_kb_guide_docs() to service_role;

revoke all on function public.match_chunks_semantic(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) from public, anon, authenticated, service_role;
grant EXECUTE on function public.match_chunks_semantic(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) to anon;
grant EXECUTE on function public.match_chunks_semantic(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) to authenticated;
grant EXECUTE on function public.match_chunks_semantic(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) to public;
grant EXECUTE on function public.match_chunks_semantic(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) to service_role;

revoke all on function public.match_chunks_semantic_exact(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) from public, anon, authenticated, service_role;
grant EXECUTE on function public.match_chunks_semantic_exact(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) to anon;
grant EXECUTE on function public.match_chunks_semantic_exact(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) to authenticated;
grant EXECUTE on function public.match_chunks_semantic_exact(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) to public;
grant EXECUTE on function public.match_chunks_semantic_exact(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) to service_role;

revoke all on function public.match_chunks_semantic_in_doc(query_embedding vector, p_doc_name text, match_count integer) from public, anon, authenticated, service_role;
grant EXECUTE on function public.match_chunks_semantic_in_doc(query_embedding vector, p_doc_name text, match_count integer) to anon;
grant EXECUTE on function public.match_chunks_semantic_in_doc(query_embedding vector, p_doc_name text, match_count integer) to authenticated;
grant EXECUTE on function public.match_chunks_semantic_in_doc(query_embedding vector, p_doc_name text, match_count integer) to public;
grant EXECUTE on function public.match_chunks_semantic_in_doc(query_embedding vector, p_doc_name text, match_count integer) to service_role;

revoke all on function public.match_kb_chunks_semantic(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) from public, anon, authenticated, service_role;
grant EXECUTE on function public.match_kb_chunks_semantic(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) to anon;
grant EXECUTE on function public.match_kb_chunks_semantic(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) to authenticated;
grant EXECUTE on function public.match_kb_chunks_semantic(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) to public;
grant EXECUTE on function public.match_kb_chunks_semantic(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) to service_role;

revoke all on function public.match_law_articles_semantic(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) from public, anon, authenticated, service_role;
grant EXECUTE on function public.match_law_articles_semantic(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) to anon;
grant EXECUTE on function public.match_law_articles_semantic(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) to authenticated;
grant EXECUTE on function public.match_law_articles_semantic(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) to public;
grant EXECUTE on function public.match_law_articles_semantic(query_embedding vector, match_threshold double precision, match_count integer, only_current boolean) to service_role;

revoke all on function public.match_news_semantic(query_embedding vector, match_count integer) from public, anon, authenticated, service_role;
grant EXECUTE on function public.match_news_semantic(query_embedding vector, match_count integer) to anon;
grant EXECUTE on function public.match_news_semantic(query_embedding vector, match_count integer) to authenticated;
grant EXECUTE on function public.match_news_semantic(query_embedding vector, match_count integer) to public;
grant EXECUTE on function public.match_news_semantic(query_embedding vector, match_count integer) to service_role;

revoke all on function public.minutes_index() from public, anon, authenticated, service_role;
grant EXECUTE on function public.minutes_index() to anon;
grant EXECUTE on function public.minutes_index() to authenticated;
grant EXECUTE on function public.minutes_index() to service_role;

revoke all on function public.my_team() from public, anon, authenticated, service_role;
grant EXECUTE on function public.my_team() to anon;
grant EXECUTE on function public.my_team() to authenticated;
grant EXECUTE on function public.my_team() to public;
grant EXECUTE on function public.my_team() to service_role;

revoke all on function public.news_feed_edit_guard() from public, anon, authenticated, service_role;
grant EXECUTE on function public.news_feed_edit_guard() to anon;
grant EXECUTE on function public.news_feed_edit_guard() to authenticated;
grant EXECUTE on function public.news_feed_edit_guard() to public;
grant EXECUTE on function public.news_feed_edit_guard() to service_role;

revoke all on function public.news_known_items(p_urls text[], p_titles text[], p_include_deleted boolean) from public, anon, authenticated, service_role;
grant EXECUTE on function public.news_known_items(p_urls text[], p_titles text[], p_include_deleted boolean) to service_role;

revoke all on function public.news_screen_cache_lookup(p_urls text[], p_criteria_hash text) from public, anon, authenticated, service_role;
grant EXECUTE on function public.news_screen_cache_lookup(p_urls text[], p_criteria_hash text) to service_role;

revoke all on function public.norm_article_key(a text) from public, anon, authenticated, service_role;
grant EXECUTE on function public.norm_article_key(a text) to anon;
grant EXECUTE on function public.norm_article_key(a text) to authenticated;
grant EXECUTE on function public.norm_article_key(a text) to public;
grant EXECUTE on function public.norm_article_key(a text) to service_role;

revoke all on function public.notify_lawmap_request() from public, anon, authenticated, service_role;
grant EXECUTE on function public.notify_lawmap_request() to anon;
grant EXECUTE on function public.notify_lawmap_request() to authenticated;
grant EXECUTE on function public.notify_lawmap_request() to public;
grant EXECUTE on function public.notify_lawmap_request() to service_role;

revoke all on function public.ops_ai_usage_today() from public, anon, authenticated, service_role;
grant EXECUTE on function public.ops_ai_usage_today() to anon;
grant EXECUTE on function public.ops_ai_usage_today() to authenticated;
grant EXECUTE on function public.ops_ai_usage_today() to public;
grant EXECUTE on function public.ops_ai_usage_today() to service_role;

revoke all on function public.ops_system_prompt_hash() from public, anon, authenticated, service_role;
grant EXECUTE on function public.ops_system_prompt_hash() to authenticated;
grant EXECUTE on function public.ops_system_prompt_hash() to service_role;

revoke all on function public.pending_versions_for_docs(p_docs text[]) from public, anon, authenticated, service_role;
grant EXECUTE on function public.pending_versions_for_docs(p_docs text[]) to anon;
grant EXECUTE on function public.pending_versions_for_docs(p_docs text[]) to authenticated;
grant EXECUTE on function public.pending_versions_for_docs(p_docs text[]) to public;
grant EXECUTE on function public.pending_versions_for_docs(p_docs text[]) to service_role;

revoke all on function public.press_index() from public, anon, authenticated, service_role;
grant EXECUTE on function public.press_index() to anon;
grant EXECUTE on function public.press_index() to authenticated;
grant EXECUTE on function public.press_index() to service_role;

revoke all on function public.refund_ai_usage(p_user uuid, p_kind text) from public, anon, authenticated, service_role;
grant EXECUTE on function public.refund_ai_usage(p_user uuid, p_kind text) to service_role;

revoke all on function public.search_chunks_keywords(p_keywords text[], p_per_kw integer) from public, anon, authenticated, service_role;
grant EXECUTE on function public.search_chunks_keywords(p_keywords text[], p_per_kw integer) to anon;
grant EXECUTE on function public.search_chunks_keywords(p_keywords text[], p_per_kw integer) to authenticated;
grant EXECUTE on function public.search_chunks_keywords(p_keywords text[], p_per_kw integer) to public;
grant EXECUTE on function public.search_chunks_keywords(p_keywords text[], p_per_kw integer) to service_role;

revoke all on function public.search_chunks_trgm(query_text text, match_threshold double precision, match_count integer, only_current boolean) from public, anon, authenticated, service_role;
grant EXECUTE on function public.search_chunks_trgm(query_text text, match_threshold double precision, match_count integer, only_current boolean) to anon;
grant EXECUTE on function public.search_chunks_trgm(query_text text, match_threshold double precision, match_count integer, only_current boolean) to authenticated;
grant EXECUTE on function public.search_chunks_trgm(query_text text, match_threshold double precision, match_count integer, only_current boolean) to public;
grant EXECUTE on function public.search_chunks_trgm(query_text text, match_threshold double precision, match_count integer, only_current boolean) to service_role;

revoke all on function public.search_documents_by_keywords(keywords text[], match_count integer) from public, anon, authenticated, service_role;
grant EXECUTE on function public.search_documents_by_keywords(keywords text[], match_count integer) to anon;
grant EXECUTE on function public.search_documents_by_keywords(keywords text[], match_count integer) to authenticated;
grant EXECUTE on function public.search_documents_by_keywords(keywords text[], match_count integer) to public;
grant EXECUTE on function public.search_documents_by_keywords(keywords text[], match_count integer) to service_role;

revoke all on function public.search_kb_chunks_trgm(query_text text, match_threshold double precision, match_count integer, only_current boolean) from public, anon, authenticated, service_role;
grant EXECUTE on function public.search_kb_chunks_trgm(query_text text, match_threshold double precision, match_count integer, only_current boolean) to anon;
grant EXECUTE on function public.search_kb_chunks_trgm(query_text text, match_threshold double precision, match_count integer, only_current boolean) to authenticated;
grant EXECUTE on function public.search_kb_chunks_trgm(query_text text, match_threshold double precision, match_count integer, only_current boolean) to public;
grant EXECUTE on function public.search_kb_chunks_trgm(query_text text, match_threshold double precision, match_count integer, only_current boolean) to service_role;

revoke all on function public.search_law_articles_kw(p_keywords text[], p_title_limit integer, p_content_limit integer) from public, anon, authenticated, service_role;
grant EXECUTE on function public.search_law_articles_kw(p_keywords text[], p_title_limit integer, p_content_limit integer) to anon;
grant EXECUTE on function public.search_law_articles_kw(p_keywords text[], p_title_limit integer, p_content_limit integer) to authenticated;
grant EXECUTE on function public.search_law_articles_kw(p_keywords text[], p_title_limit integer, p_content_limit integer) to public;
grant EXECUTE on function public.search_law_articles_kw(p_keywords text[], p_title_limit integer, p_content_limit integer) to service_role;

revoke all on function public.speaker_index() from public, anon, authenticated, service_role;
grant EXECUTE on function public.speaker_index() to anon;
grant EXECUTE on function public.speaker_index() to authenticated;
grant EXECUTE on function public.speaker_index() to service_role;

revoke all on function public.submit_answer_feedback(p_log_id uuid, p_rating smallint, p_reason text) from public, anon, authenticated, service_role;
grant EXECUTE on function public.submit_answer_feedback(p_log_id uuid, p_rating smallint, p_reason text) to anon;
grant EXECUTE on function public.submit_answer_feedback(p_log_id uuid, p_rating smallint, p_reason text) to authenticated;
grant EXECUTE on function public.submit_answer_feedback(p_log_id uuid, p_rating smallint, p_reason text) to public;
grant EXECUTE on function public.submit_answer_feedback(p_log_id uuid, p_rating smallint, p_reason text) to service_role;

revoke all on function public.trigger_admin_report() from public, anon, authenticated, service_role;
grant EXECUTE on function public.trigger_admin_report() to service_role;

revoke all on function public.trigger_briefing_if_missing() from public, anon, authenticated, service_role;
grant EXECUTE on function public.trigger_briefing_if_missing() to service_role;

revoke all on function public.trigger_subscriber_briefing() from public, anon, authenticated, service_role;
grant EXECUTE on function public.trigger_subscriber_briefing() to service_role;

revoke all on function public.update_tech_terms_updated_at() from public, anon, authenticated, service_role;
grant EXECUTE on function public.update_tech_terms_updated_at() to anon;
grant EXECUTE on function public.update_tech_terms_updated_at() to authenticated;
grant EXECUTE on function public.update_tech_terms_updated_at() to public;
grant EXECUTE on function public.update_tech_terms_updated_at() to service_role;

revoke all on function public.urgency_rules_touch() from public, anon, authenticated, service_role;
grant EXECUTE on function public.urgency_rules_touch() to anon;
grant EXECUTE on function public.urgency_rules_touch() to authenticated;
grant EXECUTE on function public.urgency_rules_touch() to public;
grant EXECUTE on function public.urgency_rules_touch() to service_role;

revoke all on function public.watchdog_scan(p_dry_run boolean) from public, anon, authenticated, service_role;
grant EXECUTE on function public.watchdog_scan(p_dry_run boolean) to service_role;
