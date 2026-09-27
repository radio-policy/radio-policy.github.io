-- 20260927171957 pause_github_dispatch_20260928

-- 2026-09-28 GitHub 계정 차단(디스패치 422 "Actions has been disabled for this user", 01:50 KST~) — 배경역사 #94 교훈:
-- 차단 중 자동 호출을 끈다. 복구 뒤 되살림: select cron.alter_job(job_id := j, active := true) from unnest(array[7,8,9,10,11,13,19,20]) j;
select cron.alter_job(job_id := j, active := false) from unnest(array[7,8,9,10,11,13,19,20]) j;;
