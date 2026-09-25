-- 20260528104048 add_summary_to_news_feed

ALTER TABLE news_feed ADD COLUMN IF NOT EXISTS summary text;;
