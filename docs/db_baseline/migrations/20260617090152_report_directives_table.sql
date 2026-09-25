-- 20260617090152 report_directives_table

create table if not exists report_directives (
  id bigint generated always as identity primary key,
  directive text not null,
  created_at timestamptz default now()
);
alter table report_directives enable row level security;
create policy report_dir_sel on report_directives for select to anon using (true);
create policy report_dir_ins on report_directives for insert to anon with check (true);
create policy report_dir_upd on report_directives for update to anon using (true) with check (true);
create policy report_dir_del on report_directives for delete to anon using (true);;
