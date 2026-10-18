# 세션 작업물 PC 백업 등록 — RadioPolicy-PCBackup, 매일 23:30 (#320, 2026-10-18)
# pc_backup.py가 %USERPROFILE%\PC백업\ 아래로 삭제 없이 복사(비밀값은 같은 길이 *로 가림)하고,
# 구글 드라이브 데스크톱 앱(운영자가 설치·로그인·「내 컴퓨터」 폴더 지정)이 그 폴더를 올린다. 복구: docs/PC백업_복구절차.md
# 회사 PC 전용 — 다른 RadioPolicy-* 작업처럼 사용자 계정·로그온할 때만. StartWhenAvailable: 23:30에 꺼져 있었으면
# 다음 로그인 때 한 번. 노트북이라 배터리에서도 시작·계속(복사만 하는 작업). 창 없음: pythonw run_hidden.py (#70).
# 경로 하드코딩 없음: $PSScriptRoot + py -3.12 (#178). 이 파일은 ASCII 코드만 쓴다(PS 5.1은 BOM 없는 파일을 CP949로 읽는다).
$root = $PSScriptRoot
$pyw  = (py -3.12 -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))")
if (-not $pyw -or -not (Test-Path $pyw)) { throw "Python 3.12 (py -3.12) not found - install Python 3.12 first" }
$taskName = "RadioPolicy-PCBackup"

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$trigger  = New-ScheduledTaskTrigger -Daily -At "23:30"
$action   = New-ScheduledTaskAction -Execute $pyw -Argument "run_hidden.py pc_backup.py pc_backup_sched.log" -WorkingDirectory $root
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Trigger $trigger -Action $action -Settings $settings -Force | Out-Null

$t = Get-ScheduledTask -TaskName $taskName
Write-Host ("Done: {0} ({1}, {2}) daily 23:30" -f $taskName, $t.Principal.UserId, $t.Principal.LogonType) -ForegroundColor Green
Write-Host ("  Execute:   {0}" -f $t.Actions[0].Execute)
Write-Host ("  Arguments: {0}" -f $t.Actions[0].Arguments)
Write-Host ("  StartIn:   {0}" -f $t.Actions[0].WorkingDirectory)
