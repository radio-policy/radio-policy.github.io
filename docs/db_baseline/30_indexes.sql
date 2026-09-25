-- indexes — tools_db_baseline.py가 실DB에서 생성(손으로 고치지 말 것), 비밀 마스킹됨

CREATE INDEX idx_answer_feedback_channel ON public.answer_feedback USING btree (channel, rating);

CREATE INDEX api_usage_ts_idx ON public.api_usage USING btree (ts DESC);

CREATE INDEX assembly_bills_proc_result_idx ON public.assembly_bills USING btree (proc_result);

CREATE INDEX assembly_bills_propose_dt_idx ON public.assembly_bills USING btree (propose_dt DESC);

CREATE INDEX idx_assembly_bills_notice_briefed ON public.assembly_bills USING btree (notice_end_dt) WHERE (notice_briefed_at IS NULL);

CREATE INDEX assembly_speeches_date_idx ON public.assembly_speeches USING btree (meeting_date DESC);

CREATE INDEX assembly_speeches_speaker_idx ON public.assembly_speeches USING btree (speaker);

CREATE INDEX idx_chat_logs_user ON public.chat_logs USING btree (user_id);

CREATE INDEX document_chunks_category_idx ON public.document_chunks USING btree (doc_category);

CREATE INDEX document_chunks_content_trgm_idx ON public.document_chunks USING gin (content gin_trgm_ops);

CREATE INDEX document_chunks_doc_name_idx ON public.document_chunks USING btree (doc_name);

CREATE INDEX document_chunks_embedding_hnsw_idx ON public.document_chunks USING hnsw (embedding vector_cosine_ops) WITH (m='16', ef_construction='64');

CREATE INDEX document_chunks_embedding_null_idx ON public.document_chunks USING btree (id) WHERE (embedding IS NULL);

CREATE INDEX idx_document_chunks_law ON public.document_chunks USING btree (law_id, status);

CREATE INDEX idx_document_chunks_status ON public.document_chunks USING btree (status);

CREATE INDEX issue_links_issue_idx ON public.issue_links USING btree (issue_id, item_date DESC);

CREATE INDEX issues_state_idx ON public.issues USING btree (state, last_activity_at DESC);

CREATE INDEX kb_chunks_content_trgm_idx ON public.kb_chunks USING gin (content gin_trgm_ops);

CREATE INDEX kb_chunks_doc_id_idx ON public.kb_chunks USING btree (doc_id);

CREATE INDEX kb_chunks_embedding_hnsw_idx ON public.kb_chunks USING hnsw (embedding vector_cosine_ops) WITH (m='16', ef_construction='64');

CREATE INDEX kb_chunks_embedding_null_idx ON public.kb_chunks USING btree (id) WHERE (embedding IS NULL);

CREATE INDEX kb_documents_dedup_key_idx ON public.kb_documents USING btree (dedup_key);

CREATE UNIQUE INDEX kb_documents_path_uidx ON public.kb_documents USING btree (path);

CREATE INDEX kb_documents_status_idx ON public.kb_documents USING btree (status);

CREATE INDEX law_amendments_law_type_idx ON public.law_amendments USING btree (law_type);

CREATE INDEX law_amendments_public_dt_idx ON public.law_amendments USING btree (public_dt);

CREATE INDEX law_delegations_child_idx ON public.law_delegations USING btree (child_law, child_article);

CREATE INDEX law_delegations_parent_idx ON public.law_delegations USING btree (parent_law, parent_article);

CREATE INDEX law_diffs_recent_idx ON public.law_diffs USING btree (analyzed_at DESC);

CREATE INDEX idx_law_graph_edges_source ON public.law_graph_edges USING btree (source_id);

CREATE INDEX idx_law_graph_edges_target ON public.law_graph_edges USING btree (target_id);

CREATE INDEX law_pending_law_idx ON public.law_pending USING btree (law_name, enf_date);

CREATE INDEX law_pending_state_idx ON public.law_pending USING btree (sync_state, enf_date);

CREATE INDEX law_terms_doc_idx ON public.law_terms USING btree (doc_name);

CREATE INDEX law_terms_law_type_idx ON public.law_terms USING btree (law_type);

CREATE INDEX law_terms_synced_idx ON public.law_terms USING btree (synced_at);

CREATE INDEX law_terms_term_key_idx ON public.law_terms USING btree (term_key);

CREATE INDEX idx_law_watch_sync ON public.law_watch USING btree (sync_status);

CREATE INDEX idx_law_watch_watch ON public.law_watch USING btree (watch_status);

CREATE INDEX lawmap_proposals_status_idx ON public.lawmap_proposals USING btree (status, created_at DESC);

CREATE INDEX news_embeddings_hnsw ON public.news_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE INDEX idx_news_feed_locked ON public.news_feed USING btree (locked) WHERE (locked = true);

CREATE INDEX idx_news_feed_published_at ON public.news_feed USING btree (published_at DESC NULLS LAST);

CREATE UNIQUE INDEX idx_news_feed_url_unique ON public.news_feed USING btree (url);

CREATE INDEX news_feed_created_at_idx ON public.news_feed USING btree (created_at DESC);

CREATE INDEX news_screen_cache_judged_at_idx ON public.news_screen_cache USING btree (judged_at);

CREATE INDEX idx_profiles_team ON public.profiles USING btree (team_id);

CREATE INDEX subscriber_queue_created_idx ON public.subscriber_queue USING btree (created_at);

CREATE INDEX tech_terms_category_idx ON public.tech_terms USING btree (category);

CREATE INDEX tech_terms_content_idx ON public.tech_terms USING gin (to_tsvector('simple'::regconfig, ((((term || ' '::text) || COALESCE(definition, ''::text)) || ' '::text) || COALESCE(description, ''::text))));

CREATE INDEX tech_terms_term_idx ON public.tech_terms USING btree (term);

CREATE INDEX idx_telegram_updates_received ON public.telegram_updates USING btree (received_at);

CREATE INDEX telegram_usage_chat_idx ON public.telegram_usage USING btree (chat_id, created_at DESC);

CREATE INDEX telegram_usage_created_idx ON public.telegram_usage USING btree (created_at DESC);
