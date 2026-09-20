# (legacy) 뉴스 크롤러 로컬 매시 실행 — 뉴스 수집은 GitHub Actions(10분마다)로 옮겨져 회사 PC에는 등록돼 있지 않다.
# 필요할 때만 쓴다. 경로는 #178 방식(하드코딩 없음).
# #178 (2026-09-20): no hardcoded PC paths. $PSScriptRoot = this repo folder on any PC;
# pythonw.exe is resolved through the Python launcher pinned to 3.12 (py -3 / bare python
# resolve to 3.13 without packages on the company PC, #22). Runs via run_hidden.py so no
# console window appears (#70).
$root = $PSScriptRoot
$pyw  = (py -3.12 -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))")
if (-not $pyw -or -not (Test-Path $pyw)) { throw "Python 3.12 (py -3.12) not found - install Python 3.12 first" }
$taskName = "RadioPolicyCrawler"

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Hours 1) -Once -At (Get-Date).Date

$action = New-ScheduledTaskAction -Execute $pyw -Argument "run_hidden.py crawler.py" -WorkingDirectory $root

$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Trigger $trigger -Action $action -Settings $settings -RunLevel Highest -Force

Write-Host "Done: $taskName registered. Runs every hour." -ForegroundColor Green
