-- foreign_keys — tools_db_baseline.py가 실DB에서 생성(손으로 고치지 말 것), 비밀 마스킹됨

alter table public.advisory_usage add constraint advisory_usage_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

alter table public.ai_usage_hour add constraint ai_usage_hour_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

alter table public.answer_feedback add constraint answer_feedback_log_id_fkey FOREIGN KEY (log_id) REFERENCES chat_logs(id) ON DELETE SET NULL;

alter table public.chat_logs add constraint chat_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id);

alter table public.importance_feedback add constraint importance_feedback_team_id_fkey FOREIGN KEY (team_id) REFERENCES teams(id);

alter table public.issue_links add constraint issue_links_issue_id_fkey FOREIGN KEY (issue_id) REFERENCES issues(id) ON DELETE CASCADE;

alter table public.kb_chunks add constraint kb_chunks_doc_id_fkey FOREIGN KEY (doc_id) REFERENCES kb_documents(id) ON DELETE CASCADE;

alter table public.law_graph_edges add constraint law_graph_edges_source_id_fkey FOREIGN KEY (source_id) REFERENCES law_graph_nodes(id) ON DELETE CASCADE;

alter table public.law_graph_edges add constraint law_graph_edges_target_id_fkey FOREIGN KEY (target_id) REFERENCES law_graph_nodes(id) ON DELETE CASCADE;

alter table public.news_embeddings add constraint news_embeddings_news_id_fkey FOREIGN KEY (news_id) REFERENCES news_feed(id) ON DELETE CASCADE;

alter table public.profiles add constraint profiles_team_id_fkey FOREIGN KEY (team_id) REFERENCES teams(id);

alter table public.profiles add constraint profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

alter table public.team_urgency add constraint team_urgency_news_id_fkey FOREIGN KEY (news_id) REFERENCES news_feed(id) ON DELETE CASCADE;

alter table public.team_urgency add constraint team_urgency_team_id_fkey FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE;

alter table public.urgency_rule_verdicts add constraint urgency_rule_verdicts_news_id_fkey FOREIGN KEY (news_id) REFERENCES news_feed(id) ON DELETE CASCADE;

alter table public.urgency_rule_verdicts add constraint urgency_rule_verdicts_rule_id_fkey FOREIGN KEY (rule_id) REFERENCES urgency_rules(id);

alter table public.urgency_rule_verdicts add constraint urgency_rule_verdicts_team_id_fkey FOREIGN KEY (team_id) REFERENCES teams(id);

alter table public.urgency_rules add constraint urgency_rules_team_id_fkey FOREIGN KEY (team_id) REFERENCES teams(id);
