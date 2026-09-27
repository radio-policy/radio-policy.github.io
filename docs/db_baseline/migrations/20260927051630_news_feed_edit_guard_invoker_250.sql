-- 20260927051630 news_feed_edit_guard_invoker_250

-- #250 보론(2026-09-27): #159 수정 가드가 SECURITY DEFINER라 함수 안 current_user가 소유자(postgres)로 보여
-- 첫 줄 '서버 경로 통과'에 늘 걸렸다 → 승인 계정 누구나 REST로 공통 importance·urgency·locked를 바꿀 수 있었다(실측: 팀원 update rows=1).
-- 호출자 권한으로 돌려 current_user가 실제 역할(authenticated / service_role / postgres)이 되게 한다. is_admin()은 자체 SECURITY DEFINER라 그대로 동작.
alter function public.news_feed_edit_guard() security invoker;
;
