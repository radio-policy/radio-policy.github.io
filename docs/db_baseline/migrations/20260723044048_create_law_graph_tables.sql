-- 20260723044048 create_law_graph_tables

-- 법령 관계도: 노드/엣지 테이블 (2026-07-23)
create table if not exists public.law_graph_nodes (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  node_type text not null check (node_type in ('topic','law','decree','rules','notice','etc')),
  description text,
  doc_name text,
  source text not null default 'seed' check (source in ('seed','citation','ai')),
  created_at timestamptz default now()
);

create table if not exists public.law_graph_edges (
  id uuid primary key default gen_random_uuid(),
  source_id uuid not null references public.law_graph_nodes(id) on delete cascade,
  target_id uuid not null references public.law_graph_nodes(id) on delete cascade,
  relation_type text not null,
  description text,
  source text not null default 'seed' check (source in ('family','citation','seed','ai')),
  weight int not null default 1,
  created_at timestamptz default now(),
  unique (source_id, target_id, relation_type)
);

create index if not exists idx_law_graph_edges_source on public.law_graph_edges(source_id);
create index if not exists idx_law_graph_edges_target on public.law_graph_edges(target_id);

alter table public.law_graph_nodes enable row level security;
alter table public.law_graph_edges enable row level security;

-- 대시보드(anon): 조회 + AI 생성 저장(insert/update). 삭제는 service_role 전용.
create policy law_graph_nodes_anon_select on public.law_graph_nodes for select to anon using (true);
create policy law_graph_nodes_anon_insert on public.law_graph_nodes for insert to anon with check (true);
create policy law_graph_nodes_anon_update on public.law_graph_nodes for update to anon using (true) with check (true);
create policy law_graph_edges_anon_select on public.law_graph_edges for select to anon using (true);
create policy law_graph_edges_anon_insert on public.law_graph_edges for insert to anon with check (true);
create policy law_graph_edges_anon_update on public.law_graph_edges for update to anon using (true) with check (true);;
