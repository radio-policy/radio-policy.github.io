-- 20261002045334 news_feed_urgency_check_268

-- #268 (2026-10-02) 긴급도 2차 확인(2단 구조) 그림자 — 1차 AI가 긴급인 기사에만 2차 Haiku(G1 형식) 결과를 남긴다.
-- 2차를 부르지 않은 행(1차 긴급 아님·낱말 하한 긴급·사람 사례·실패)은 네 칸 모두 null. 크롤러가 벌크 upsert 모든 행에 키를 채운다.
-- 권한: news_feed의 표 단위 SELECT(anon·authenticated)가 새 칸에도 그대로 미친다(공개 열람 화면과 같은 범위).
-- UPDATE는 칸 단위 권한(is_read 등)이라 anon·authenticated는 이 칸을 못 고친다 — 쓰기는 service_role(크롤러)뿐. 새 GRANT 불필요.
-- CHECK는 두지 않는다 — 값 검사는 크롤러가 하고, 제약 위반은 벌크 upsert 전체(기사 저장)를 실패시킨다.
alter table public.news_feed
  add column if not exists urgency_check_scope text,
  add column if not exists urgency_check_grade text,
  add column if not exists urgency_check_basis text,
  add column if not exists urgency_check_capped boolean;;
