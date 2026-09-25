-- 20260820123240 app_config_drop_claude_key_write

-- anon이 claude_key 행을 다시 심을 수 없게 쓰기 허용 범위를 좁힌다 (#104).
-- 대시보드가 실제로 편집하는 것은 press_keywords뿐이다.
drop policy if exists app_config_ins on public.app_config;
drop policy if exists app_config_upd on public.app_config;
create policy app_config_ins on public.app_config for insert to anon, authenticated
  with check (key = 'press_keywords');
create policy app_config_upd on public.app_config for update to anon, authenticated
  using (key = 'press_keywords') with check (key = 'press_keywords');;
