-- 20260919184004 crawl_trigger_every_10min_174

-- #174 (2026-09-20): 뉴스+방미통위 크롤 트리거를 매시 :47 → 10분마다. jobid 9·이름은 유지(이름은 역사적).
select cron.alter_job(9, schedule := '*/10 * * * *');
update public.watchdog_targets set label = '뉴스 크롤러(10분)' where key = 'last_crawl_run';
update public.watchdog_targets set label = '방미통위 회의·보도자료(10분)' where key = 'last_kmcc_meeting_run';;
