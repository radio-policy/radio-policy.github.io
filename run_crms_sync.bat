@echo off
set PYTHONUTF8=1
rem #178 (2026-09-20): no hardcoded PC paths. cd to this file's folder; run Python via the launcher
rem pinned to 3.12 (bare python / py -3 resolve to 3.13 without packages on the company PC, #22).
cd /d "%~dp0"
set PY=py -3.12
echo [%date% %time%] === crms sync start === >> crms_sync_log.txt
%PY% crms_guide_sync.py >> crms_sync_log.txt 2>&1
echo [%date% %time%] === done === >> crms_sync_log.txt
