# 모닝 브리핑 로컬 백업 — 매일 09:40 KST (lampmanH-pc 본선; 회사 PC 예비는 09:50으로, 2026-09-20 lampmanH-pc 이전)
# GitHub Actions 스케줄 전체 누락 대비 (2026-06-11 확인: 3중 cron + daily_crawl 백업 모두 skip)
# already_sent_today()가 중복 발송 차단 → GitHub이 정상 발송했으면 아무것도 안 함
# -StartWhenAvailable: 09:40에 PC가 꺼져 있었으면 부팅 후 즉시 실행
# #178 (2026-09-20): no hardcoded PC paths. $PSScriptRoot = this repo folder on any PC;
# pythonw.exe is resolved through the Python launcher pinned to 3.12 (py -3 / bare python
# resolve to 3.13 without packages on the company PC, #22). Runs via run_hidden.py so no
# console window appears (#70).
$root = $PSScriptRoot
$pyw  = (py -3.12 -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))")
if (-not $pyw -or -not (Test-Path $pyw)) { throw "Python 3.12 (py -3.12) not found - install Python 3.12 first" }
$taskName = "RadioPolicy-BriefingBackup"

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$trigger  = New-ScheduledTaskTrigger -Daily -At "09:40"
$action   = New-ScheduledTaskAction -Execute $pyw -Argument "run_hidden.py morning_briefing.py briefing_backup_sched.log" -WorkingDirectory $root
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Trigger $trigger -Action $action -Settings $settings -Force

Write-Host "Done: $taskName registered. Runs daily at 09:40 KST (or on next boot if missed)." -ForegroundColor Green
