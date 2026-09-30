-- 20260930120857 resume_github_dispatch_20260930

-- #254-보론5: GitHub 계정 복구(09-30) 뒤 수집을 GitHub Actions로 되돌림 — pause_github_dispatch_20260928의 반대
select cron.alter_job(job_id := j, active := true) from unnest(array[7,8,9,10,11,13,19,20]::bigint[]) j;;
