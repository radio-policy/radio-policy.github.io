-- 20260914034918 lock_app_config_and_chat_logs

-- #1 app_config: anon 쓰기 제거 + system_prompt 열람 제외 (#169-보론2, 2026-09-14)
--   press_keywords 를 anon 이 덮어쓸 수 있었다 — 보도자료 KB에 무엇이 들어올지를 외부가 정한다.
--   대시보드가 실제로 읽는 키는 press_keywords 하나뿐이고(app.js:7313), /ask 의 system_prompt 는
--   Edge 가 service_role 로 읽으므로 anon 열람에서 빼도 동작에 영향이 없다.
drop policy if exists app_config_ins on public.app_config;
drop policy if exists app_config_upd on public.app_config;
alter policy app_config_sel on public.app_config using (key <> 'system_prompt');

-- 보도자료 키워드 편집은 관리자만 (화면에도 같은 게이트를 넣는다)
create policy app_config_ins_admin on public.app_config
  for insert to authenticated with check (is_admin());
create policy app_config_upd_admin on public.app_config
  for update to authenticated using (is_admin()) with check (is_admin());

-- #2 chat_logs: anon insert 제거. chat_logs_ins_auth 가 user_id = auth.uid() 를 강제하고,
--   대시보드는 이미 user_id 를 넣어 보낸다(app.js:3283). 텔레그램은 service_role 이라 무관.
drop policy if exists chat_logs_ins on public.chat_logs;;
