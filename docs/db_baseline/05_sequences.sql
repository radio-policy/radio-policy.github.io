-- sequences — tools_db_baseline.py가 실DB에서 생성(손으로 고치지 말 것), 비밀 마스킹됨

create sequence if not exists public.api_usage_id_seq;

create sequence if not exists public.custom_knowledge_id_seq;

create sequence if not exists public.document_chunks_id_seq;

create sequence if not exists public.law_delegations_id_seq;

create sequence if not exists public.law_diffs_id_seq;

create sequence if not exists public.law_pending_id_seq;

create sequence if not exists public.law_watch_id_seq;

create sequence if not exists public.people_id_seq;

create sequence if not exists public.subscriber_queue_id_seq;

create sequence if not exists public.teams_id_seq;

create sequence if not exists public.telegram_usage_id_seq;
