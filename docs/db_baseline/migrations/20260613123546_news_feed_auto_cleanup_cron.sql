-- 20260613123546 news_feed_auto_cleanup_cron


-- 매일 15:00 UTC (00:00 KST) — locked=false인 15일 초과 뉴스 삭제
SELECT cron.schedule(
  'news-feed-cleanup',
  '0 15 * * *',
  $$DELETE FROM news_feed WHERE created_at < NOW() - INTERVAL '15 days' AND locked = false;$$
);
;
