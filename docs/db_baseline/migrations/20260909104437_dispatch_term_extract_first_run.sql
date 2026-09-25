-- 20260909104437 dispatch_term_extract_first_run

-- #141 첫 실행 검증 — term_extract.yml 을 pg_cron 과 같은 경로(dispatch_github_workflow)로 1회 디스패치.
-- 결과는 net._http_response(204=성공) 와 system_health(last_term_extract_run / last_term_backfill_run) 로 확인.
select public.dispatch_github_workflow('term_extract.yml');;
