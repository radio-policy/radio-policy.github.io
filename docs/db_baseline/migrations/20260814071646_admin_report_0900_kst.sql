-- 20260814071646 admin_report_0900_kst

-- 발송 시각을 09:00 KST 로 변경 (운영자 지시 2026-08-14). 00:00 UTC = 09:00 KST.
select cron.unschedule('admin-daily-report');
select cron.schedule('admin-daily-report', '0 0 * * *', $$select public.trigger_admin_report()$$);;
