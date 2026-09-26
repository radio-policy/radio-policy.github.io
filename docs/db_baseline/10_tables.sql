-- tables — tools_db_baseline.py가 실DB에서 생성(손으로 고치지 말 것), 비밀 마스킹됨

create table if not exists public._bak_superseded_emb_20260925 (
  id bigint,
  embedding vector(1024)
);
alter table public._bak_superseded_emb_20260925 enable row level security;

create table if not exists public.advisory_usage (
  user_id uuid not null,
  day date not null,
  kind text not null,
  count integer default 0 not null,
  constraint advisory_usage_pkey PRIMARY KEY (user_id, day, kind),
  constraint advisory_usage_kind_check CHECK ((kind = ANY (ARRAY['advisory'::text, 'general'::text])))
);
alter table public.advisory_usage enable row level security;

create table if not exists public.ai_usage_hour (
  user_id uuid not null,
  hour timestamp with time zone not null,
  count integer default 0 not null,
  constraint ai_usage_hour_pkey PRIMARY KEY (user_id, hour)
);
alter table public.ai_usage_hour enable row level security;

create table if not exists public.alert_suppress_log (
  id bigint generated always as identity not null,
  created_at timestamp with time zone default now() not null,
  article_title text not null,
  article_url text,
  matched_title text not null,
  shared_keywords text,
  constraint alert_suppress_log_pkey PRIMARY KEY (id)
);
alter table public.alert_suppress_log enable row level security;

create table if not exists public.answer_feedback (
  id bigint generated always as identity not null,
  log_id uuid,
  channel text not null,
  rating smallint not null,
  reason text,
  chat_id bigint,
  created_at timestamp with time zone default now() not null,
  updated_at timestamp with time zone default now() not null,
  constraint answer_feedback_log_id_key UNIQUE (log_id),
  constraint answer_feedback_pkey PRIMARY KEY (id),
  constraint answer_feedback_channel_check CHECK ((channel = ANY (ARRAY['telegram_ask'::text, 'telegram_law'::text, 'dashboard'::text]))),
  constraint answer_feedback_rating_check CHECK ((rating = ANY (ARRAY[1, '-1'::integer])))
);
alter table public.answer_feedback enable row level security;

create table if not exists public.api_usage (
  id bigint default nextval('api_usage_id_seq'::regclass) not null,
  ts timestamp with time zone default now() not null,
  host text default 'pc'::text not null,
  site text not null,
  model text,
  input_tokens integer default 0 not null,
  cache_read integer default 0 not null,
  cache_write integer default 0 not null,
  output_tokens integer default 0 not null,
  constraint api_usage_pkey PRIMARY KEY (id)
);
alter table public.api_usage enable row level security;

create table if not exists public.app_config (
  key text not null,
  value text not null,
  constraint app_config_pkey PRIMARY KEY (key)
);
alter table public.app_config enable row level security;

create table if not exists public.assembly_bills (
  id uuid default gen_random_uuid() not null,
  bill_id text not null,
  bill_no text,
  bill_name text not null,
  proposer text,
  committee text,
  proc_result text default '접수'::text,
  propose_dt text,
  proc_dt text,
  age integer default 22,
  matched_keywords text[],
  link_url text,
  prev_proc_result text,
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now(),
  summary text,
  notice_end_dt text,
  notice_url text,
  notice_alert_stage smallint default 0,
  notice_briefed_at timestamp with time zone,
  committee_dt text,
  cmt_present_dt text,
  cmt_proc_dt text,
  cmt_proc_result text,
  law_submit_dt text,
  law_present_dt text,
  law_proc_dt text,
  constraint assembly_bills_bill_id_key UNIQUE (bill_id),
  constraint assembly_bills_pkey PRIMARY KEY (id)
);
alter table public.assembly_bills enable row level security;

create table if not exists public.assembly_speeches (
  id uuid default gen_random_uuid() not null,
  speaker text not null,
  speaker_raw text,
  "position" text,
  party text,
  meeting_date date,
  confer_num text not null,
  chunk_seq integer not null,
  agenda text,
  topic text,
  summary text,
  source_url text,
  created_at timestamp with time zone default now() not null,
  constraint assembly_speeches_uniq UNIQUE (confer_num, speaker, chunk_seq),
  constraint assembly_speeches_pkey PRIMARY KEY (id)
);
alter table public.assembly_speeches enable row level security;

create table if not exists public.changes (
  id uuid default gen_random_uuid() not null,
  doc_name text not null,
  change_type text,
  description text,
  source_url text,
  detected_at timestamp with time zone default now(),
  constraint changes_pkey PRIMARY KEY (id),
  constraint changes_change_type_check CHECK ((change_type = ANY (ARRAY['개정'::text, '폐지'::text, '제정'::text, '예고'::text])))
);
alter table public.changes enable row level security;

create table if not exists public.chat_logs (
  id uuid default gen_random_uuid() not null,
  question text not null,
  answer text not null,
  category text,
  sources text,
  created_at timestamp with time zone default now(),
  channel text,
  chat_id bigint,
  chunk_ids jsonb,
  user_id uuid,
  cite_verdicts jsonb,
  search_meta jsonb,
  constraint chat_logs_pkey PRIMARY KEY (id)
);
alter table public.chat_logs enable row level security;

create table if not exists public.custom_knowledge (
  id bigint default nextval('custom_knowledge_id_seq'::regclass) not null,
  title text not null,
  content text not null,
  category text default '일반'::text,
  tags text[] default '{}'::text[],
  created_at timestamp with time zone default now(),
  is_active boolean default true,
  constraint custom_knowledge_pkey PRIMARY KEY (id)
);
alter table public.custom_knowledge enable row level security;

create table if not exists public.daily_briefings (
  id uuid default gen_random_uuid() not null,
  briefing_date date not null,
  content text not null,
  news_count integer default 0,
  terms_count integer default 0,
  created_at timestamp with time zone default now(),
  constraint daily_briefings_briefing_date_key UNIQUE (briefing_date),
  constraint daily_briefings_pkey PRIMARY KEY (id)
);
alter table public.daily_briefings enable row level security;

create table if not exists public.daily_briefings_backup (
  id bigint generated always as identity not null,
  briefing_date date not null,
  content text not null,
  news_count integer,
  terms_count integer,
  original_created_at timestamp with time zone,
  backed_up_at timestamp with time zone default now() not null,
  reason text,
  constraint daily_briefings_backup_pkey PRIMARY KEY (id)
);
alter table public.daily_briefings_backup enable row level security;

create table if not exists public.deleted_news (
  id bigint generated always as identity not null,
  url text,
  title text,
  deleted_at timestamp with time zone default now() not null,
  news_id uuid,
  constraint deleted_news_pkey PRIMARY KEY (id)
);
alter table public.deleted_news enable row level security;

create table if not exists public.document_chunks (
  id bigint default nextval('document_chunks_id_seq'::regclass) not null,
  doc_name text not null,
  doc_category text,
  chunk_index integer,
  content text not null,
  created_at timestamp with time zone default now(),
  notice_no text,
  article_no text,
  effective_date text,
  embedding vector(1024),
  file_path text,
  is_approved boolean default true not null,
  law_id text,
  law_mst text,
  status text default 'current'::text not null,
  constraint document_chunks_pkey PRIMARY KEY (id),
  constraint document_chunks_status_chk CHECK ((status = ANY (ARRAY['current'::text, 'pending'::text, 'superseded'::text])))
);
alter table public.document_chunks enable row level security;

create table if not exists public.documents (
  id uuid default gen_random_uuid() not null,
  name text not null,
  type text,
  version text,
  file_url text,
  file_path text,
  status text default '최신'::text,
  updated_at timestamp with time zone default now(),
  constraint documents_pkey PRIMARY KEY (id),
  constraint documents_status_check CHECK ((status = ANY (ARRAY['최신'::text, '업로드필요'::text, '개정예고'::text]))),
  constraint documents_type_check CHECK ((type = ANY (ARRAY['법령'::text, '고시'::text, 'ITU-R'::text, '전파법'::text, '전파법_시행령'::text, '전파법_시행규칙'::text, '전기통신사업법'::text, '전기통신사업법_시행령'::text, '방송통신발전기본법'::text, '방송통신발전기본법_시행령'::text, '기술기준'::text, '적합성평가'::text, '주파수할당'::text, '주파수분배표'::text, '전자파'::text, '정보통신망법'::text, '정보통신기반시설'::text, '방송통신설비'::text])))
);
alter table public.documents enable row level security;

create table if not exists public.feedback_rules (
  id integer not null,
  rules text,
  feedback_count integer default 0 not null,
  updated_at timestamp with time zone default now() not null,
  constraint feedback_rules_pkey PRIMARY KEY (id)
);
alter table public.feedback_rules enable row level security;

create table if not exists public.importance_feedback (
  id bigint generated always as identity not null,
  news_id uuid,
  title text,
  summary text,
  ai_importance text,
  user_importance text,
  created_at timestamp with time zone default now() not null,
  updated_at timestamp with time zone default now() not null,
  constraint importance_feedback_news_id_key UNIQUE (news_id),
  constraint importance_feedback_pkey PRIMARY KEY (id)
);
alter table public.importance_feedback enable row level security;

create table if not exists public.issue_links (
  id bigint generated always as identity not null,
  issue_id bigint not null,
  item_type text not null,
  item_id text not null,
  item_date date,
  title text,
  note text,
  added_by text default 'operator'::text,
  created_at timestamp with time zone default now(),
  constraint issue_links_issue_id_item_type_item_id_key UNIQUE (issue_id, item_type, item_id),
  constraint issue_links_pkey PRIMARY KEY (id)
);
alter table public.issue_links enable row level security;

create table if not exists public.issues (
  id bigint generated always as identity not null,
  title text not null,
  definition text,
  category text,
  state text default 'proposed'::text not null,
  stage text default '발생'::text not null,
  dormant boolean default false not null,
  stage_log jsonb default '[]'::jsonb,
  resolution_kind text,
  norm_key text,
  proposal_reason jsonb,
  source text default 'auto'::text,
  embedding vector(1024),
  impact_summary jsonb,
  impact_history jsonb default '[]'::jsonb,
  last_activity_at timestamp with time zone default now(),
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now(),
  constraint issues_pkey PRIMARY KEY (id)
);
alter table public.issues enable row level security;

create table if not exists public.kb_chunks (
  id bigint generated by default as identity not null,
  doc_id bigint not null,
  chunk_idx integer,
  content text not null,
  embedding vector(1024),
  created_at timestamp with time zone default now(),
  constraint kb_chunks_pkey PRIMARY KEY (id)
);
alter table public.kb_chunks enable row level security;

create table if not exists public.kb_documents (
  id bigint generated by default as identity not null,
  dedup_key text,
  title text not null,
  concept_type text,
  family text,
  law_type text,
  law_number text,
  enforcement_date text,
  competent_authority text,
  status text default 'current'::text not null,
  superseded_by text,
  path text not null,
  description text,
  body_md text,
  created_at timestamp with time zone default now(),
  constraint kb_documents_pkey PRIMARY KEY (id)
);
alter table public.kb_documents enable row level security;

create table if not exists public.kb_quality_ack (
  doc_name text not null,
  acked_at timestamp with time zone default now() not null,
  note text,
  constraint kb_quality_ack_pkey PRIMARY KEY (doc_name)
);
alter table public.kb_quality_ack enable row level security;

create table if not exists public.kmcc_press_verdict (
  url text not null,
  title text,
  relevant boolean not null,
  reason text,
  judged_at timestamp with time zone default now() not null,
  constraint kmcc_press_verdict_pkey PRIMARY KEY (url)
);
alter table public.kmcc_press_verdict enable row level security;

create table if not exists public.law_amendments (
  id uuid default gen_random_uuid() not null,
  law_id text not null,
  law_nm text not null,
  law_type text not null,
  ann_type text,
  public_dt text,
  enf_dt text,
  public_no text,
  matched_keywords text[],
  link_url text,
  prev_public_dt text,
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now(),
  summary text,
  constraint law_amendments_law_id_key UNIQUE (law_id),
  constraint law_amendments_pkey PRIMARY KEY (id)
);
alter table public.law_amendments enable row level security;

create table if not exists public.law_delegations (
  id bigint default nextval('law_delegations_id_seq'::regclass) not null,
  parent_law text not null,
  parent_article text not null,
  parent_title text,
  child_law text not null,
  child_article text not null,
  child_title text,
  child_kind text,
  synced_at timestamp with time zone default now() not null,
  constraint law_delegations_parent_law_parent_article_child_law_child_a_key UNIQUE (parent_law, parent_article, child_law, child_article),
  constraint law_delegations_pkey PRIMARY KEY (id)
);
alter table public.law_delegations enable row level security;

create table if not exists public.law_diffs (
  id bigint default nextval('law_diffs_id_seq'::regclass) not null,
  law_name text not null,
  law_id text,
  mst text,
  law_no text,
  enf_date text,
  diff_kind text not null,
  base_doc text not null,
  new_doc text not null,
  summary text,
  impact text,
  urgency text,
  articles jsonb default '[]'::jsonb not null,
  stats jsonb,
  model text,
  analyzed_at timestamp with time zone default now(),
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now(),
  origin text default 'gov'::text,
  constraint law_diffs_uniq UNIQUE (law_name, new_doc, diff_kind),
  constraint law_diffs_pkey PRIMARY KEY (id)
);
alter table public.law_diffs enable row level security;

create table if not exists public.law_graph_edges (
  id uuid default gen_random_uuid() not null,
  source_id uuid not null,
  target_id uuid not null,
  relation_type text not null,
  description text,
  source text default 'seed'::text not null,
  weight integer default 1 not null,
  created_at timestamp with time zone default now(),
  constraint law_graph_edges_source_id_target_id_relation_type_key UNIQUE (source_id, target_id, relation_type),
  constraint law_graph_edges_pkey PRIMARY KEY (id),
  constraint law_graph_edges_source_check CHECK ((source = ANY (ARRAY['family'::text, 'citation'::text, 'seed'::text, 'ai'::text, 'thdcmp'::text, 'delegation'::text])))
);
alter table public.law_graph_edges enable row level security;

create table if not exists public.law_graph_nodes (
  id uuid default gen_random_uuid() not null,
  name text not null,
  node_type text not null,
  description text,
  doc_name text,
  source text default 'seed'::text not null,
  created_at timestamp with time zone default now(),
  constraint law_graph_nodes_name_key UNIQUE (name),
  constraint law_graph_nodes_pkey PRIMARY KEY (id),
  constraint law_graph_nodes_node_type_check CHECK ((node_type = ANY (ARRAY['topic'::text, 'law'::text, 'decree'::text, 'rules'::text, 'notice'::text, 'etc'::text]))),
  constraint law_graph_nodes_source_check CHECK ((source = ANY (ARRAY['seed'::text, 'citation'::text, 'ai'::text])))
);
alter table public.law_graph_nodes enable row level security;

create table if not exists public.law_pending (
  id bigint default nextval('law_pending_id_seq'::regclass) not null,
  law_name text not null,
  law_id text,
  law_type_token text,
  api_target text default 'law'::text not null,
  watch_doc_name text,
  mst text not null,
  law_no text,
  enf_date text not null,
  doc_name text,
  sync_state text default 'detected'::text not null,
  note text,
  detected_at timestamp with time zone default now() not null,
  loaded_at timestamp with time zone,
  promoted_at timestamp with time zone,
  updated_at timestamp with time zone default now() not null,
  constraint law_pending_uniq UNIQUE (law_name, mst, enf_date),
  constraint law_pending_pkey PRIMARY KEY (id)
);
alter table public.law_pending enable row level security;

create table if not exists public.law_terms (
  id bigint generated by default as identity not null,
  term text not null,
  term_key text not null,
  term_alias text,
  law_name text not null,
  full_name text,
  law_type text default '기타'::text not null,
  doc_name text not null,
  doc_category text,
  article_no text not null,
  article_key text,
  item_no text not null,
  definition text not null,
  law_no text,
  effective_date text,
  synced_at timestamp with time zone default now() not null,
  constraint law_terms_uq UNIQUE (doc_name, article_no, item_no),
  constraint law_terms_pkey PRIMARY KEY (id)
);
alter table public.law_terms enable row level security;

create table if not exists public.law_watch (
  id bigint default nextval('law_watch_id_seq'::regclass) not null,
  doc_name text not null,
  law_name text,
  law_type_token text,
  api_target text,
  law_id text,
  registered_mst text,
  registered_law_no text,
  registered_enf text,
  latest_mst text,
  latest_law_no text,
  latest_enf text,
  pending_mst text,
  pending_law_no text,
  pending_enf text,
  watch_status text default 'watching'::text not null,
  sync_status text default 'unknown'::text not null,
  approved_at timestamp with time zone,
  approved_mst text,
  last_checked_at timestamp with time zone,
  note text,
  created_at timestamp with time zone default now() not null,
  updated_at timestamp with time zone default now() not null,
  constraint law_watch_doc_name_key UNIQUE (doc_name),
  constraint law_watch_pkey PRIMARY KEY (id),
  constraint law_watch_sync_status_chk CHECK ((sync_status = ANY (ARRAY['current'::text, 'outdated'::text, 'approved'::text, 'synced'::text, 'unknown'::text]))),
  constraint law_watch_watch_status_chk CHECK ((watch_status = ANY (ARRAY['watching'::text, 'unmatched'::text, 'excluded'::text])))
);
alter table public.law_watch enable row level security;

create table if not exists public.lawmap_proposals (
  id uuid default gen_random_uuid() not null,
  created_at timestamp with time zone default now() not null,
  created_by uuid default auth.uid(),
  requester text,
  origin text default 'advisory'::text not null,
  question text,
  topic text not null,
  description text,
  relations jsonb default '[]'::jsonb not null,
  gate jsonb,
  status text default 'pending'::text not null,
  decided_at timestamp with time zone,
  decided_by uuid,
  decision_note text,
  result jsonb,
  constraint lawmap_proposals_pkey PRIMARY KEY (id),
  constraint lawmap_proposals_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'approved'::text, 'rejected'::text])))
);
alter table public.lawmap_proposals enable row level security;

create table if not exists public.news_embeddings (
  news_id uuid not null,
  embedding vector(1024) not null,
  embedded_at timestamp with time zone default now(),
  constraint news_embeddings_pkey PRIMARY KEY (news_id)
);
alter table public.news_embeddings enable row level security;

create table if not exists public.news_feed (
  id uuid default gen_random_uuid() not null,
  title text not null,
  source text,
  category text,
  url text,
  is_read boolean default false,
  published_at timestamp with time zone,
  created_at timestamp with time zone default now(),
  content text,
  content_fetched_at timestamp with time zone,
  briefed_date date,
  summary text,
  importance text default '참고'::text,
  urgency text default '참고'::text,
  locked boolean default false not null,
  tags text[],
  event text,
  impact_analysis text,
  impact_analyzed_at timestamp with time zone,
  urgency_screen text,
  urgency_rule text,
  origin text,
  constraint news_feed_pkey PRIMARY KEY (id)
);
alter table public.news_feed enable row level security;

create table if not exists public.news_screen_cache (
  url text not null,
  title_hash text not null,
  criteria_hash text not null,
  judged_at timestamp with time zone default now() not null,
  created_at timestamp with time zone default now(),
  constraint news_screen_cache_pkey PRIMARY KEY (url)
);
alter table public.news_screen_cache enable row level security;

create table if not exists public.people (
  id bigint default nextval('people_id_seq'::regclass) not null,
  speaker_key text not null,
  name text not null,
  kind text default '의원'::text not null,
  party text,
  "position" text,
  terms text,
  is_22 boolean default false,
  speech_count integer default 0,
  first_speech date,
  last_speech date,
  stance_summary text,
  stance_updated_at timestamp with time zone,
  updated_at timestamp with time zone default now(),
  speaker_match text,
  speech_from date,
  speech_to date,
  constraint people_speaker_key_key UNIQUE (speaker_key),
  constraint people_pkey PRIMARY KEY (id)
);
alter table public.people enable row level security;

create table if not exists public.profiles (
  user_id uuid not null,
  name text default ''::text not null,
  team_id smallint,
  role text default 'member'::text not null,
  daily_limit integer default 10 not null,
  unlimited boolean default false not null,
  approved boolean default false not null,
  active boolean default true not null,
  created_at timestamp with time zone default now() not null,
  can_edit_issues boolean default false not null,
  constraint profiles_pkey PRIMARY KEY (user_id),
  constraint profiles_role_check CHECK ((role = ANY (ARRAY['admin'::text, 'leader'::text, 'member'::text])))
);
alter table public.profiles enable row level security;

create table if not exists public.subscriber_queue (
  id bigint default nextval('subscriber_queue_id_seq'::regclass) not null,
  topic text not null,
  html text not null,
  created_at timestamp with time zone default now() not null,
  news_url text,
  tags text[],
  constraint subscriber_queue_pkey PRIMARY KEY (id),
  constraint subscriber_queue_topic_check CHECK ((topic = ANY (ARRAY['urgent'::text, 'assembly'::text, 'kmcc'::text])))
);
alter table public.subscriber_queue enable row level security;

create table if not exists public.system_health (
  key text not null,
  updated_at timestamp with time zone default now() not null,
  note text,
  constraint system_health_pkey PRIMARY KEY (key)
);
alter table public.system_health enable row level security;

create table if not exists public.system_status (
  key text not null,
  value text,
  updated_at timestamp with time zone default now(),
  constraint system_status_pkey PRIMARY KEY (key)
);
alter table public.system_status enable row level security;

create table if not exists public.teams (
  id smallint default nextval('teams_id_seq'::regclass) not null,
  name text not null,
  daily_limit integer default 30 not null,
  unlimited boolean default false not null,
  created_at timestamp with time zone default now() not null,
  constraint teams_name_key UNIQUE (name),
  constraint teams_pkey PRIMARY KEY (id)
);
alter table public.teams enable row level security;

create table if not exists public.tech_terms (
  id uuid default gen_random_uuid() not null,
  term text not null,
  term_en text,
  category text default '기타'::text,
  definition text,
  description text,
  diagram_html text,
  source text,
  source_url text,
  related_terms text[],
  is_reviewed boolean default false,
  created_at timestamp without time zone default now(),
  updated_at timestamp without time zone default now(),
  constraint tech_terms_term_key UNIQUE (term),
  constraint tech_terms_pkey PRIMARY KEY (id)
);
alter table public.tech_terms enable row level security;

create table if not exists public.telegram_subscribers (
  chat_id bigint not null,
  username text,
  first_name text,
  active boolean default true not null,
  topic_briefing boolean default true not null,
  topic_urgent boolean default true not null,
  topic_assembly boolean default true not null,
  days text default 'daily'::text not null,
  briefing_hour smallint default 7 not null,
  last_briefing_sent_date date,
  ai_allowed boolean default false not null,
  ai_count_date date,
  ai_count smallint default 0 not null,
  created_at timestamp with time zone default now() not null,
  updated_at timestamp with time zone default now() not null,
  quiet_night boolean default true not null,
  last_urgent_sent_at timestamp with time zone,
  last_assembly_sent_at timestamp with time zone,
  tags text[] default '{}'::text[] not null,
  law_count integer default 0 not null,
  law_count_date date,
  end_hour integer default 22 not null,
  unlimited boolean default false not null,
  law_allowed boolean default false not null,
  topic_kmcc boolean default true not null,
  last_kmcc_sent_at timestamp with time zone,
  constraint telegram_subscribers_pkey PRIMARY KEY (chat_id),
  constraint telegram_subscribers_briefing_hour_check CHECK (((briefing_hour >= 6) AND (briefing_hour <= 12))),
  constraint telegram_subscribers_days_check CHECK ((days = ANY (ARRAY['daily'::text, 'weekday'::text])))
);
alter table public.telegram_subscribers enable row level security;

create table if not exists public.telegram_updates (
  update_id bigint not null,
  chat_id bigint,
  received_at timestamp with time zone default now() not null,
  constraint telegram_updates_pkey PRIMARY KEY (update_id)
);
alter table public.telegram_updates enable row level security;

create table if not exists public.telegram_usage (
  id bigint default nextval('telegram_usage_id_seq'::regclass) not null,
  chat_id bigint not null,
  command text not null,
  query text,
  ok boolean default true not null,
  result_note text,
  created_at timestamp with time zone default now() not null,
  constraint telegram_usage_pkey PRIMARY KEY (id)
);
alter table public.telegram_usage enable row level security;

create table if not exists public.urgency_rules (
  id text not null,
  team_id smallint,
  "position" integer default 100 not null,
  mode text not null,
  level text not null,
  any_words jsonb not null,
  and_any jsonb default '[]'::jsonb not null,
  none_words jsonb default '[]'::jsonb not null,
  note text default ''::text not null,
  enabled boolean default true not null,
  updated_by uuid,
  updated_at timestamp with time zone default now() not null,
  constraint urgency_rules_pkey PRIMARY KEY (id),
  constraint urgency_rules_and_any_check CHECK ((jsonb_typeof(and_any) = 'array'::text)),
  constraint urgency_rules_any_words_check CHECK (((jsonb_typeof(any_words) = 'array'::text) AND (jsonb_array_length(any_words) > 0))),
  constraint urgency_rules_id_check CHECK ((id ~ '^[a-z0-9_]+$'::text)),
  constraint urgency_rules_level_check CHECK ((level = ANY (ARRAY['긴급'::text, '보통'::text, '참고'::text]))),
  constraint urgency_rules_mode_check CHECK ((mode = ANY (ARRAY['min'::text, 'set'::text]))),
  constraint urgency_rules_none_words_check CHECK ((jsonb_typeof(none_words) = 'array'::text))
);
alter table public.urgency_rules enable row level security;

create table if not exists public.watchdog_targets (
  key text not null,
  thresh_h numeric not null,
  label text not null,
  active boolean default true not null,
  note text,
  created_at timestamp with time zone default now() not null,
  constraint watchdog_targets_pkey PRIMARY KEY (key)
);
alter table public.watchdog_targets enable row level security;
