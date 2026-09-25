-- 20260908084340 people_update_admin_only

-- #135 (2026-09-08) 인물 프로필 갱신(입장 요약 stance_summary 등)은 관리자만.
-- 종전 people_upd 는 public(anon 포함) using(true) — 인터넷 누구나 인물 행을 덮어쓸 수 있었다.
-- 크롤러·Python 스크립트는 service_role 이라 정책과 무관.
drop policy if exists people_upd on public.people;
create policy people_upd on public.people
  for update to authenticated using (public.is_admin()) with check (public.is_admin());;
