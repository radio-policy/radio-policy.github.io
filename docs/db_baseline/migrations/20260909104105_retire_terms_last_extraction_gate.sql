-- 20260909104105 retire_terms_last_extraction_gate

-- #141 (2026-09-09) 브라우저 자동 추출 폐지 → #137의 서버 게이트(app_config.terms_last_extraction)도 불필요.
-- 쓰기 정책을 닫고 행을 지운다(다시 열어 두면 쓸데없는 쓰기 경로).
drop policy if exists app_config_upd_terms_gate on public.app_config;
delete from public.app_config where key = 'terms_last_extraction';;
