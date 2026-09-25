-- 20260903041607 news_feed_published_at_index

-- 뉴스 목록 정렬(published_at desc nulls last)이 매 페이지마다 Seq Scan + 전체 정렬을 하며
-- external merge로 디스크에 6.5MB씩 흘러넘치고 있었다(2026-09-03 실측, 9,031행).
-- 목록 로드는 1,000행씩 여러 페이지를 받으므로 같은 정렬이 페이지 수만큼 반복된다.
create index if not exists idx_news_feed_published_at
  on news_feed (published_at desc nulls last);;
