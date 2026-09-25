-- 20260612013217 create_deleted_news_blocklist

-- 사용자가 대시보드에서 삭제한 기사 재수집 방지 블록리스트
-- crawler.py get_existing_urls()가 이 테이블의 url·title도 중복 체크에 포함
CREATE TABLE IF NOT EXISTS deleted_news (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  url text,
  title text,
  deleted_at timestamptz NOT NULL DEFAULT now()
);
-- news_feed와 동일하게 RLS 미사용 (대시보드 anon 키로 insert 필요);
