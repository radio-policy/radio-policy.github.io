@echo off
set PYTHONUTF8=1
cd /d C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai
echo [%date% %time%] === crawl start === >> gov_crawler_log.txt
"C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe" gov_notice_crawler.py >> gov_crawler_log.txt 2>&1
echo [%date% %time%] === law_diff start === >> gov_crawler_log.txt
"C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe" law_diff_gen.py >> gov_crawler_log.txt 2>&1
echo [%date% %time%] === minutes start === >> gov_crawler_log.txt
"C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe" assembly_minutes.py >> gov_crawler_log.txt 2>&1
echo [%date% %time%] === done === >> gov_crawler_log.txt
