@echo off
set PYTHONUTF8=1
cd /d C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai
echo [%date% %time%] === foreign start === >> foreign_press_log.txt
"C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe" foreign_press.py >> foreign_press_log.txt 2>&1
echo [%date% %time%] === done === >> foreign_press_log.txt
