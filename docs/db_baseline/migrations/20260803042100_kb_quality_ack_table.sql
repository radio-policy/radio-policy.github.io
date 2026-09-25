-- 20260803042100 kb_quality_ack_table

-- KB 품질 카드 '확인함' 처리: 사람이 보고 문제없다고 판단한 문서를 목록에서 제외
create table if not exists public.kb_quality_ack (
  doc_name text primary key,
  acked_at timestamptz not null default now(),
  note     text
);

alter table public.kb_quality_ack enable row level security;

do $$ begin
  if not exists (select 1 from pg_policies where schemaname='public'
                 and tablename='kb_quality_ack' and policyname='kb_quality_ack_sel') then
    create policy kb_quality_ack_sel on public.kb_quality_ack
      for select to anon, authenticated using (true);
  end if;
  if not exists (select 1 from pg_policies where schemaname='public'
                 and tablename='kb_quality_ack' and policyname='kb_quality_ack_ins') then
    create policy kb_quality_ack_ins on public.kb_quality_ack
      for insert to anon, authenticated with check (true);
  end if;
end $$;

grant select, insert on public.kb_quality_ack to anon, authenticated;;
