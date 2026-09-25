-- 20260617081914 report_draft_feature_tables

-- 보고서 초안 제안 기능: 테이블 3종 + RPC + RLS 정책
create table if not exists report_samples (
  id bigint generated always as identity primary key,
  title text not null,
  report_type text,
  content text not null,
  summary text,
  embedding vector(1024),
  created_at timestamptz default now()
);
create index if not exists report_samples_embedding_idx
  on report_samples using hnsw (embedding vector_cosine_ops);

create table if not exists report_style_rules (
  id int primary key default 1,
  rules text,
  sample_count int default 0,
  updated_at timestamptz default now()
);
insert into report_style_rules (id, rules, sample_count) values (1, null, 0)
  on conflict (id) do nothing;

create table if not exists report_feedback (
  id bigint generated always as identity primary key,
  request text,
  draft text,
  final text,
  rating smallint,
  created_at timestamptz default now()
);

create or replace function match_report_samples(
  query_embedding vector(1024),
  match_count int default 2,
  filter_type text default null
) returns table (id bigint, title text, report_type text, content text, similarity float)
language sql stable as $$
  select rs.id, rs.title, rs.report_type, rs.content,
         1 - (rs.embedding <=> query_embedding) as similarity
  from report_samples rs
  where rs.embedding is not null
    and (filter_type is null or rs.report_type = filter_type)
  order by rs.embedding <=> query_embedding
  limit match_count;
$$;

alter table report_samples     enable row level security;
alter table report_style_rules enable row level security;
alter table report_feedback    enable row level security;

-- report_samples: anon 4종
create policy report_samples_sel on report_samples for select to anon using (true);
create policy report_samples_ins on report_samples for insert to anon with check (true);
create policy report_samples_upd on report_samples for update to anon using (true) with check (true);
create policy report_samples_del on report_samples for delete to anon using (true);

-- report_style_rules: anon 4종 (upsert에 update 필요)
create policy report_style_sel on report_style_rules for select to anon using (true);
create policy report_style_ins on report_style_rules for insert to anon with check (true);
create policy report_style_upd on report_style_rules for update to anon using (true) with check (true);
create policy report_style_del on report_style_rules for delete to anon using (true);

-- report_feedback: anon 4종
create policy report_fb_sel on report_feedback for select to anon using (true);
create policy report_fb_ins on report_feedback for insert to anon with check (true);
create policy report_fb_upd on report_feedback for update to anon using (true) with check (true);
create policy report_fb_del on report_feedback for delete to anon using (true);;
