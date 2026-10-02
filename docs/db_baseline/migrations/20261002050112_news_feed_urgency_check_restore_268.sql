-- 20261002050112 news_feed_urgency_check_restore_268

-- #268 (2026-10-02, 운영자 결정 「그림자 없이 켠다 + 안전장치 둘」) — ② 관리자가 2차 확인이 내린 기사(urgency_check_capped)를
-- 대시보드에서 다시 긴급으로 올리면 크롤러가 구독자 큐에 넣는다. 이 칸 = 그 처리를 한 시각(크롤러가 먼저 선점해 두 번 보내지 않는다).
-- 쓰기는 service_role(크롤러)뿐 — anon·authenticated의 UPDATE는 칸 단위 권한이라 이 칸에 미치지 않는다. 표 단위 SELECT는 그대로.
alter table public.news_feed add column if not exists urgency_check_restored_at timestamptz;
-- 매 실행(10분) 「capped인데 지금 긴급, 아직 안 되돌림」 조회용 — 내린 기사만 담는 작은 부분 인덱스
create index if not exists idx_news_feed_check_capped on public.news_feed (created_at) where urgency_check_capped;
NOTIFY pgrst, 'reload schema';;
