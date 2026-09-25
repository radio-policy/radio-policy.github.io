-- 20260612140528 news_feed_url_unique

CREATE UNIQUE INDEX IF NOT EXISTS idx_news_feed_url_unique ON public.news_feed (url);;
