@echo off
set PYTHONUTF8=1
cd /d C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai
echo [%date% %time%] === crawl start === >> gov_crawler_log.txt
"C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe" gov_notice_crawler.py >> gov_crawler_log.txt 2>&1
echo [%date% %time%] === law_diff start === >> gov_crawler_log.txt
"C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe" law_diff_gen.py >> gov_crawler_log.txt 2>&1
echo [%date% %time%] === minutes start === >> gov_crawler_log.txt
"C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe" assembly_minutes.py >> gov_crawler_log.txt 2>&1
rem law relation pipeline (order matters: law delegations -> notice delegations -> graph)
echo [%date% %time%] === law_delegations start === >> gov_crawler_log.txt
"C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe" sync_law_delegations.py >> sync_law_delegations_sched.log 2>&1
echo [%date% %time%] law_delegations exit=%ERRORLEVEL% >> gov_crawler_log.txt
echo [%date% %time%] === notice_delegations start === >> gov_crawler_log.txt
"C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe" sync_notice_delegations.py >> sync_notice_delegations_sched.log 2>&1
echo [%date% %time%] notice_delegations exit=%ERRORLEVEL% >> gov_crawler_log.txt
echo [%date% %time%] === citation_graph start === >> gov_crawler_log.txt
"C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe" build_law_citation_graph.py >> build_law_citation_graph_sched.log 2>&1
echo [%date% %time%] citation_graph exit=%ERRORLEVEL% >> gov_crawler_log.txt
echo [%date% %time%] === done === >> gov_crawler_log.txt
