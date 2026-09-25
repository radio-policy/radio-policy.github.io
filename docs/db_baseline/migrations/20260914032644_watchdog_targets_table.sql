-- 20260914032644 watchdog_targets_table

-- 감시 대상을 watchdog_scan() 본문 밖으로 (#169, 2026-09-14).
-- 본문 인라인 VALUES 라 크롤러를 추가할 때마다 함수를 다시 발행해야 했고, 그래서 실제로
-- 4개(kmcc·term_extract·term_backfill·law_terms_sync)가 감시에서 빠져 있었다.
-- kmcc 는 그 사이 note 에 fail=2 를 달고도 아무 알림이 없었다.
create table if not exists public.watchdog_targets (
  key        text primary key,
  thresh_h   numeric not null,
  label      text    not null,
  active     boolean not null default true,
  note       text,
  created_at timestamptz not null default now()
);
alter table public.watchdog_targets enable row level security;
-- 운영 상태 화면에서 읽을 수 있게 열람만 공개(뉴스·하트비트와 같은 수준). 쓰기는 service_role.
create policy watchdog_targets_sel on public.watchdog_targets
  for select to anon, authenticated using (true);
grant select on public.watchdog_targets to anon, authenticated;

insert into public.watchdog_targets(key, thresh_h, label, note) values
  ('last_crawl_run',               3.0,   '뉴스 크롤러(매시)', null),
  ('last_gov_notice_run',          26.0,  '정부고시·입법예고(매일 17시)', null),
  ('last_press_ingest',            26.0,  '보도자료 수집(17시 체인)', null),
  ('last_law_diff_run',            26.0,  '법령 조문 DIFF(17시 체인)', null),
  ('last_assembly_run',            26.0,  '국회 법안·입법예고(매일 10:30)', null),
  ('last_minutes_run',             26.0,  '과방위 회의록(17시 체인)', null),
  ('last_foreign_press_run',       30.0,  '해외 규제기관(매일 05:30)', null),
  ('last_itu_watch_run',           960.0, 'ITU-R 권고 감시(월 1회)', null),
  ('last_refetch_run',             26.0,  '본문 재수집(PC 매시)', null),
  ('last_subscriber_briefing_run', 3.0,   '구독자 정시 발송(매시 :25)', null),
  -- 아래 4개가 그동안 빠져 있던 것
  ('last_kmcc_meeting_run',        3.0,   '방미통위 회의·보도자료(매시)', '2026-09-14 등록 — 그전까지 미감시'),
  ('last_term_extract_run',        26.0,  '기술 용어 추출(매일 05:00)',   '2026-09-14 등록 — 그전까지 미감시'),
  ('last_term_backfill_run',       26.0,  '용어 상세 백필(매일 05:00)',   '2026-09-14 등록 — 그전까지 미감시'),
  ('last_law_terms_sync',          26.0,  '법적 용어 정의 동기화(11:00)', '2026-09-14 등록 — 그전까지 미감시')
on conflict (key) do nothing;;
