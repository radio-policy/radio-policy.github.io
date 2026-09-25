-- 20260908083728 news_feed_impact_analysis_cache

-- #134 (2026-09-08) 뉴스 상세의 SKT 영향 분석 결과를 저장한다 — 종전엔 열 때마다·사람마다 Haiku를 다시 불렀다.
-- 60일 롤링 삭제(news-feed-cleanup)와 함께 사라지고, 잠금 기사는 분석도 같이 남는다.
-- 쓰기는 승인 프로필만(#133 정책 그대로 — anon 컬럼 권한에는 넣지 않는다).
alter table public.news_feed
  add column if not exists impact_analysis text,
  add column if not exists impact_analyzed_at timestamptz;
comment on column public.news_feed.impact_analysis is 'SKT 영향 분석 원문(<impact>/<priority> 태그 포함, Haiku). 첫 열람자가 만들고 이후는 저장본 표시 (#134)';;
