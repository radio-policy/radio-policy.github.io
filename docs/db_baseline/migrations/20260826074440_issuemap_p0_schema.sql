-- 20260826074440 issuemap_p0_schema

-- 이슈맵 P0: 이슈 본체 / 이슈-항목 연결 / 뉴스 임베딩 + 뉴스 시맨틱 검색 RPC
create table if not exists issues (
  id bigint generated always as identity primary key,
  title text not null,
  definition text,
  category text,
  state text not null default 'proposed',   -- proposed|active|rejected|archived
  stage text not null default '발생',        -- 발생|현안|해소 (3단계)
  dormant boolean not null default false,   -- 휴면 배지(30일 무활동, 가역)
  stage_log jsonb default '[]',             -- 자동 전환 이력 [{at, from, to, signal}]
  resolution_kind text,                     -- 해소 시: 법령 시행|처분 확정|자연 소멸|타 이슈 흡수
  norm_key text,                            -- 제안 중복억제 키(extract_keywords 정렬 join)
  proposal_reason jsonb,                    -- {cluster_size,urgent_count,days,sample_news_ids[]}
  source text default 'auto',               -- auto|manual
  embedding vector(1024),                   -- title+definition (이슈 매칭·유사사례 쿼리)
  impact_summary jsonb,                     -- {what,why,action,sources,model,generated_at}
  impact_history jsonb default '[]',
  last_activity_at timestamptz default now(),
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create index if not exists issues_state_idx on issues (state, last_activity_at desc);

create table if not exists issue_links (
  id bigint generated always as identity primary key,
  issue_id bigint not null references issues(id) on delete cascade,
  item_type text not null,   -- news|law|bill|diff|press_chunk|minutes|kb_case|briefing|stakeholder
  item_id text not null,
  item_date date,            -- 타임라인 정렬(연결 시 원본 날짜 복사)
  title text,                -- 표시 캐시(원본 삭제 후에도 잔존)
  note text,
  added_by text default 'operator',  -- operator|auto|ai
  created_at timestamptz default now(),
  unique (issue_id, item_type, item_id)
);
create index if not exists issue_links_issue_idx on issue_links (issue_id, item_date desc);

create table if not exists news_embeddings (
  news_id uuid primary key references news_feed(id) on delete cascade,
  embedding vector(1024) not null,
  embedded_at timestamptz default now()
);
create index if not exists news_embeddings_hnsw on news_embeddings using hnsw (embedding vector_cosine_ops);

-- RLS: 켜고 정책 0개(service 전용)로 시작 — P1에서 authenticated 정책 추가
alter table issues enable row level security;
alter table issue_links enable row level security;
alter table news_embeddings enable row level security;

create or replace function match_news_semantic(query_embedding vector(1024), match_count int default 8)
returns table (id uuid, title text, published_at timestamptz, url text, similarity float)
language sql stable as $$
  select n.id, n.title, n.published_at, n.url,
         1 - (ne.embedding <=> query_embedding) as similarity
  from news_embeddings ne join news_feed n on n.id = ne.news_id
  order by ne.embedding <=> query_embedding
  limit match_count;
$$;;
