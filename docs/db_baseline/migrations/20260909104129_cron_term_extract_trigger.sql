-- 20260909104129 cron_term_extract_trigger

-- #141 (2026-09-09) 기술 용어 자동 추출·상세 백필 — 05:00 KST(20:00 UTC) GitHub Actions term_extract.yml 디스패치.
-- pg_cron이 주 트리거, 워크플로 자체 cron은 백업(다른 트리거 잡과 같은 구조).
select cron.schedule('term-extract-trigger', '0 20 * * *',
  $$select public.dispatch_github_workflow('term_extract.yml');$$);;
