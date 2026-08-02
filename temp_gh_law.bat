@echo off
REM TEMPORARY - substitutes GitHub Actions while account is flagged (2026-08-01).
REM DELETE this file and its scheduled task after account restore (see ?? do-not / task #10).
REM Chain mirrors .github/workflows/law_crawl.yml: crawler -> promote -> watch
cd /d "C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai"
set PYTHONIOENCODING=utf-8
"C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe" law_crawler.py >> temp_law_log.txt 2>&1
"C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe" law_sync.py --promote >> temp_law_log.txt 2>&1
"C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe" law_watch.py >> temp_law_log.txt 2>&1
