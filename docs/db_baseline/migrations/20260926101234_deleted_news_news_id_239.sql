-- 20260926101234 deleted_news_news_id_239

-- #239 (2026-09-26) 지운 기사 목록에 지운 news_feed 행의 id를 남긴다 — 사내 반입(export_news.py)이 url 대신 id로 같은 기사를 맞추도록(사내판 인계 ④).
-- 빈칸 허용: 이전 329행·세션 SQL 삭제·크롤러 경로는 null일 수 있다. news_feed 행은 곧바로 지워지므로 외래키는 걸지 않는다.
-- 기존 표에 칸만 더하므로 GRANT 변경 없음(표 단위 권한이 새 칸에도 적용 — #214 대상 아님).
alter table public.deleted_news add column if not exists news_id uuid;
comment on column public.deleted_news.news_id is '#239 지운 news_feed 행의 id(대시보드 deleteNewsItem이 기록, 이전 행·세션 삭제는 null 가능) — 사내 반입이 url 대신 id로 같은 기사를 맞춘다';;
