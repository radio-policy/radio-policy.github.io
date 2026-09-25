-- 20260612005210 add_locked_to_news_feed

ALTER TABLE news_feed ADD COLUMN IF NOT EXISTS locked boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_news_feed_locked ON news_feed (locked) WHERE locked = true;;
