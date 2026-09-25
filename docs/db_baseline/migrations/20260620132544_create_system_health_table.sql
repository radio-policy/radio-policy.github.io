-- 20260620132544 create_system_health_table

create table if not exists public.system_health (
  key text primary key,
  updated_at timestamptz not null default now(),
  note text
);

alter table public.system_health enable row level security;

drop policy if exists system_health_anon_select on public.system_health;
create policy system_health_anon_select on public.system_health
  for select to anon using (true);;
