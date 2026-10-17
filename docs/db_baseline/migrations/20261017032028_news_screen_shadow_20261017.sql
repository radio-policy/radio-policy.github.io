-- 20261017032028 news_screen_shadow_20261017

-- #318 관련성 선별 Haiku 5.5 그림자 1주 기록(crawler._screen_shadow_*). service_role 전용 — anon·authenticated 권한 없음.
create table public.news_screen_shadow (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  batch_key text not null,
  kind text not null check (kind in ('batch', 'relevance', 'tags')),
  model text not null,
  criteria_hash text,
  host text,
  status text,
  prod_ok boolean,
  ms integer,
  detail text,
  n_items integer,
  n_prod integer,
  n_shadow integer,
  n_diff integer,
  n_tag_diff integer,
  url text,
  title text,
  summary text,
  prod_relevant boolean,
  shadow_relevant boolean,
  prod_tags text[],
  shadow_tags text[]
);
comment on table public.news_screen_shadow is '#318 관련성 선별 그림자(Haiku 5.5) — batch: 배치당 1행(status·건수), relevance: 4.5/5.5 관련·무관이 갈린 기사, tags: 둘 다 관련인데 태그 묶음이 다른 기사. 운영 판정에 쓰지 않는다.';
create index news_screen_shadow_created_at_idx on public.news_screen_shadow (created_at);
create index news_screen_shadow_kind_idx on public.news_screen_shadow (kind, id);
alter table public.news_screen_shadow enable row level security;
revoke all on public.news_screen_shadow from public, anon, authenticated, service_role;
grant select, insert, delete on public.news_screen_shadow to service_role;
revoke all on sequence public.news_screen_shadow_id_seq from public, anon, authenticated, service_role;
grant usage, select on sequence public.news_screen_shadow_id_seq to service_role;
;
