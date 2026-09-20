@echo off
set PYTHONUTF8=1
rem #178 (2026-09-20): no hardcoded PC paths. cd to this file's folder; run Python via the launcher
rem pinned to 3.12 (bare python / py -3 resolve to 3.13 without packages on the company PC, #22).
cd /d "%~dp0"
set PY=py -3.12
echo [%date% %time%] === BRIEFING BACKUP START === >> briefing_backup_log.txt
%PY% morning_briefing.py >> briefing_backup_log.txt 2>&1
echo [%date% %time%] === DONE === >> briefing_backup_log.txt
