-- 20260803100649 add_news_screen_cache

-- 뉴스 선별 무관 판정 캐시 (2026-08-03, 비용 절감 ①)
-- Haiku가 '무관'으로 판정한 기사의 URL·제목 지문을 기억해, 네이버 검색에 같은 기사가
-- 다시 나타나도(노출 기간 ~15일, 매시간) 재판정하지 않는다. 판정 결과 자체는 안 바뀌므로
-- 품질 영향 없음. 기준문(app_config.news_relevance_criteria)이 바뀌면 criteria_hash가
-- 달라져 캐시가 자동 무효화된다.
create table if not exists public.news_screen_cache (
  url           text primary key,
  title_hash    text not null,   -- 정규화한 제목의 sha256 앞 16자 — 제목이 바뀌면 재판정
  criteria_hash text not null,   -- 판정 당시 기준문의 지문 — 기준문 변경 시 자동 무효
  judged_at     timestamptz not null default now()
);
comment on table public.news_screen_cache is
  '뉴스 선별 무관 판정 캐시 — 크롤러 전용(service key). 20일 지난 행은 크롤러가 삭제.';
create index if not exists news_screen_cache_judged_at_idx
  on public.news_screen_cache (judged_at);
-- 크롤러는 service key라 RLS를 우회한다. anon(대시보드)은 읽기·쓰기 모두 차단.
alter table public.news_screen_cache enable row level security;;
