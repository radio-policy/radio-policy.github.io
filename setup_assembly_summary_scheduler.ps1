# 국회 법안 제안이유 AI 요약 - Windows 작업 스케줄러 등록 (매일 10:30, PC ON 시; 회사 PC 예비는 10:45)
# #178 (2026-09-20): no hardcoded PC paths. $PSScriptRoot = this repo folder on any PC;
# pythonw.exe is resolved through the Python launcher pinned to 3.12 (py -3 / bare python
# resolve to 3.13 without packages on the company PC, #22). Runs via run_hidden.py so no
# console window appears (#70).
$root = $PSScriptRoot
$pyw  = (py -3.12 -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))")
if (-not $pyw -or -not (Test-Path $pyw)) { throw "Python 3.12 (py -3.12) not found - install Python 3.12 first" }
$taskName = "RadioPolicy-AssemblySummary"

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$trigger  = New-ScheduledTaskTrigger -Daily -At 10:30am
$action   = New-ScheduledTaskAction -Execute $pyw -Argument "run_hidden.py summarize_assembly_bills.py" -WorkingDirectory $root
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Trigger $trigger -Action $action -Settings $settings -RunLevel Highest -Force

Write-Host "Done: $taskName registered. Runs daily at 10:30 (catches up if missed)." -ForegroundColor Green
