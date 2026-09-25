-- cron — tools_db_baseline.py가 실DB에서 생성(손으로 고치지 말 것), 비밀 마스킹됨

select cron.schedule('admin-daily-report', '0 0 * * *', 'select public.trigger_admin_report()');

select cron.schedule('ai-usage-burst-check', '15 * * * *', 'select public.check_ai_usage_burst();');

select cron.schedule('api-usage-cleanup', '30 15 * * *', 'delete from public.api_usage where ts < now() - interval ''120 days'';');

select cron.schedule('assembly-crawl-trigger', '30 1 * * *', 'select public.dispatch_github_workflow(''assembly_crawl.yml'');');

select cron.schedule('briefing-health-check', '0 1 * * *', 'SELECT check_briefing_health();');

select cron.schedule('briefing-trigger-0605', '5 21 * * *', 'select public.trigger_briefing_if_missing();');

select cron.schedule('briefing-trigger-0620', '20 21 * * *', 'select public.trigger_briefing_if_missing();');

select cron.schedule('crawl-trigger-hourly', '*/10 * * * *', 'select public.dispatch_github_workflow(''daily_crawl.yml'');');

select cron.schedule('foreign-press-trigger', '30 20 * * *', 'select public.dispatch_github_workflow(''foreign_press.yml'');');

select cron.schedule('law-crawl-trigger', '30 2 * * *', 'select public.dispatch_github_workflow(''law_crawl.yml'');');

select cron.schedule('news-feed-cleanup', '0 15 * * *', 'DELETE FROM news_feed WHERE created_at < NOW() - INTERVAL ''60 days'' AND locked = false;');

select cron.schedule('news-health-check', '0 12 * * *', 'select public.check_news_health();');

select cron.schedule('subscriber-briefing-hourly', '25 * * * *', 'select public.trigger_subscriber_briefing()');

select cron.schedule('term-extract-trigger', '0 20 * * *', 'select public.dispatch_github_workflow(''term_extract.yml'');');

select cron.schedule('watchdog-scan-3x', '10 */3 * * *', ' select public.watchdog_scan(false); ');

select cron.schedule('watchdog-trigger', '35 12 * * *', 'select public.dispatch_github_workflow(''health_watchdog.yml'');');
