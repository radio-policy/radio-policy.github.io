-- 20260801185959 create_law_diffs

create table if not exists public.law_diffs (
  id           bigserial primary key,
  law_name     text not null,
  law_id       text,
  mst          text,
  law_no       text,
  enf_date     text,
  diff_kind    text not null,
  base_doc     text not null,
  new_doc      text not null,
  summary      text,
  impact       text,
  urgency      text,
  articles     jsonb not null default '[]',
  stats        jsonb,
  model        text,
  analyzed_at  timestamptz default now(),
  created_at   timestamptz default now(),
  updated_at   timestamptz default now(),
  constraint law_diffs_uniq unique (law_name, new_doc, diff_kind)
);
create index if not exists law_diffs_recent_idx on public.law_diffs (analyzed_at desc);
alter table public.law_diffs enable row level security;
drop policy if exists "anon read law_diffs" on public.law_diffs;
create policy "anon read law_diffs" on public.law_diffs for select using (true);;
