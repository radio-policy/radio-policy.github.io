-- 20261004101610 people_anon_revoke_20261004

-- #279 2단계 (2026-10-04, 운영자 결정 A안) 사외판 인물 = 승인 계정 전용.
-- 사내 다리는 people_export(p_key) RPC로 전환 끝(사내 897bcbd, 19:08 회차 271행) — 그 뒤에 회수한다.
-- 회수 뒤 anon REST는 오류가 아니라 빈 목록을 받는다. 다시 열지 말 것(지침 하지 말 것 #279).
drop policy if exists people_sel on public.people;
create policy people_sel on public.people as permissive for select to authenticated
  using (is_approved_user());

revoke all on public.people from anon;
revoke all on sequence public.people_id_seq from anon;;
