-- 20261013032825 news_feed_ai_summary_20261013

-- #298 (2026-10-13) 텔레그램 구독자 봇 주요 뉴스의 2문장 AI 요약 — 크롤러(service_role)만 쓴다, 대시보드 summarizeNews가 먼저 표시.
-- news_feed.summary(네이버 요약 — 목록·검색·긴급도 피드백 사례가 읽는 칸)는 덮지 않으려고 칸을 따로 둔다.
-- 권한: news_feed는 표 단위 GRANT(anon SELECT · authenticated SELECT/INSERT/DELETE · service_role 전부)라 새 칸에도 그대로 미친다.
-- authenticated의 UPDATE는 칸 단위 8칸뿐(#191) — 이 칸은 넣지 않는다(화면에서 못 고침). 칸 단위 GRANT를 덧붙이지 않는다
-- (효과 없이 security_audit 권한 지문만 바뀐다). 적용 뒤 has_column_privilege로 확인.
alter table public.news_feed add column if not exists ai_summary text;
comment on column public.news_feed.ai_summary is
  '텔레그램 구독자 주요 뉴스 2문장 AI 요약(#298, crawler attach_tg_summaries가 수집 때 받은 전문으로 생성). summary(네이버 요약)와 별개';;
