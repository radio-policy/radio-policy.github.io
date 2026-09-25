-- 20260908085847 terms_last_extraction_server_gate

-- #137 (2026-09-08) 기술 용어 자동 추출의 "오늘 실행" 기준을 브라우저(localStorage) → 서버(app_config)로.
-- 승인자 브라우저마다 하루 1회 돌던 것을 시스템 전체 하루 1회로 고정한다. 선점은 UPDATE ... WHERE value <> today.
insert into public.app_config (key, value) values ('terms_last_extraction', '')
  on conflict (key) do nothing;

-- 승인 프로필만 이 키를 갱신할 수 있다(기존 정책은 press_keywords 키만 허용). 다른 키는 여전히 잠김.
create policy app_config_upd_terms_gate on public.app_config
  for update to authenticated
  using (key = 'terms_last_extraction' and public.is_approved_user())
  with check (key = 'terms_last_extraction' and public.is_approved_user());;
