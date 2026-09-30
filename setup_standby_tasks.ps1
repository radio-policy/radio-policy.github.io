# lampmanH-pc automatic standby for the company PC's scheduled tasks (#265-bis2, 2026-10-01).
# Run ONCE, on lampmanH-pc only, in its external repo folder, right after `git pull origin main`:
#   powershell -ExecutionPolicy Bypass -File setup_standby_tasks.ps1
# Registers 4 tasks under the current user (not SYSTEM - #179). Each runs standby_run.py, which
# skips the job when the company PC already ran it (heartbeat guard), so they only really run
# while the company PC is off (nights, weekends, days off). Re-running this script replaces the 4 tasks.
# The old disabled tasks (RadioPolicy-RefetchContent etc. and radio_TEMP_*) are left untouched -
# never delete them (operator decision 2026-09-30). To stop the standby:
#   Get-ScheduledTask -TaskName 'RadioPolicy-Standby-*' | Disable-ScheduledTask
# No hardcoded paths (#178): $PSScriptRoot = this folder, pythonw.exe resolved via py -3.12 (#22).
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

$cfg = Get-Content (Join-Path $root '.git\config') -Raw
if ($cfg -match '(?m)^\s*\[remote "gitlab"\]') {
  throw "This folder has the 'gitlab' remote = the company PC working folder. Run this on lampmanH-pc only."
}

# The unguarded old tasks (RadioPolicy-RefetchContent, -BriefingBackup, -AssemblySummary, the gov chain task)
# must stay disabled, or they would run next to the guarded standby. Matched by what they run, not by name
# (this file stays ASCII: Windows PowerShell 5.1 reads a BOM-less .ps1 in the ANSI code page).
# radio_TEMP_* (the GitHub-suspension set) is judged separately - see guideline #254/#265.
$pat = 'refetch_content\.py|run_gov_crawler\.bat|gov_notice_crawler\.py|morning_briefing\.py|summarize_assembly_bills\.py|run_briefing_backup\.bat|run_assembly_summary\.bat'
Get-ScheduledTask | Where-Object { $_.TaskName -notlike 'RadioPolicy-Standby-*' -and $_.TaskName -notlike 'radio_TEMP_*' -and $_.State -ne 'Disabled' } |
  ForEach-Object {
    $t = $_
    foreach ($a in $t.Actions) {
      if (("$($a.Execute) $($a.Arguments)") -match $pat) {
        throw "Old unguarded task '$($t.TaskName)' is enabled here - disable it first (do not delete)."
      }
    }
  }

$pyw = (py -3.12 -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))")
if (-not $pyw -or -not (Test-Path $pyw)) { throw "Python 3.12 (py -3.12) not found - install Python 3.12 first" }

function Register-Standby($name, $trigger, $job, $limitMin, $catchUp) {
  $action = New-ScheduledTaskAction -Execute $pyw `
    -Argument "run_hidden.py standby_run.py standby_${job}_sched.log $job" -WorkingDirectory $root
  $s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes $limitMin) -MultipleInstances IgnoreNew
  $s.StartWhenAvailable = $catchUp
  Register-ScheduledTask -TaskName $name -Trigger $trigger -Action $action -Settings $s -Force | Out-Null
  Write-Host "registered $name ($job)" -ForegroundColor Green
}

$today = (Get-Date).Date
# body refetch: every 10 min at :07/:17/... (company PC :02/:12/...); skipped while the company PC runs it
Register-Standby 'RadioPolicy-Standby-Refetch' `
  (New-ScheduledTaskTrigger -Once -At $today.AddMinutes(7) -RepetitionInterval (New-TimeSpan -Minutes 10)) `
  'refetch' 30 $false
# gov chain: daily 17:15 (company PC 16:30); git pull first, then skipped if the company PC ran it
Register-Standby 'RadioPolicy-Standby-GovChain' (New-ScheduledTaskTrigger -Daily -At '17:15') 'chain' 180 $true
# briefing backup: 09:35, BEFORE the company PC's 09:50 so the two never overlap (it stops itself if already sent)
Register-Standby 'RadioPolicy-Standby-Briefing' (New-ScheduledTaskTrigger -Daily -At '09:35') 'briefing' 20 $false
# assembly bill summaries: 11:00 (company PC 10:30); only bills with no summary, so a second run does nothing
Register-Standby 'RadioPolicy-Standby-AssemblySummary' (New-ScheduledTaskTrigger -Daily -At '11:00') 'summary' 30 $false

Write-Host ""
Write-Host "Check (decision only, nothing runs):  py -3.12 standby_run.py chain --check" -ForegroundColor Cyan
Get-ScheduledTask -TaskName 'RadioPolicy-Standby-*' | ForEach-Object {
  $i = $_ | Get-ScheduledTaskInfo
  "{0,-40} {1,-8} next={2}" -f $_.TaskName, $_.State, $i.NextRunTime
}
