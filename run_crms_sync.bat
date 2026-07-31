@echo off
set PYTHONUTF8=1
cd /d C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai
echo [%date% %time%] === crms sync start === >> crms_sync_log.txt
"C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe" crms_guide_sync.py >> crms_sync_log.txt 2>&1
echo [%date% %time%] === done === >> crms_sync_log.txt
