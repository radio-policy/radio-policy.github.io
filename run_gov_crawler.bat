@echo off
set PYTHONUTF8=1
rem #178 (2026-09-20): no hardcoded PC paths. cd to this file's folder; run Python via the launcher
rem pinned to 3.12 (bare python / py -3 resolve to 3.13 without packages on the company PC, #22).
cd /d "%~dp0"
set PY=py -3.12
echo [%date% %time%] === crawl start === >> gov_crawler_log.txt
%PY% gov_notice_crawler.py >> gov_crawler_log.txt 2>&1
echo [%date% %time%] === law_diff start === >> gov_crawler_log.txt
%PY% law_diff_gen.py >> gov_crawler_log.txt 2>&1
echo [%date% %time%] === minutes start === >> gov_crawler_log.txt
%PY% assembly_minutes.py >> gov_crawler_log.txt 2>&1
rem people roster refresh after minutes import (no AI; writes changed rows only, #212)
echo [%date% %time%] === people_refresh start === >> gov_crawler_log.txt
%PY% tools_people_refresh.py >> gov_crawler_log.txt 2>&1
echo [%date% %time%] people_refresh exit=%ERRORLEVEL% >> gov_crawler_log.txt
rem law relation pipeline (order matters: law delegations -> notice delegations -> graph)
echo [%date% %time%] === law_delegations start === >> gov_crawler_log.txt
%PY% sync_law_delegations.py >> sync_law_delegations_sched.log 2>&1
echo [%date% %time%] law_delegations exit=%ERRORLEVEL% >> gov_crawler_log.txt
echo [%date% %time%] === notice_delegations start === >> gov_crawler_log.txt
%PY% sync_notice_delegations.py >> sync_notice_delegations_sched.log 2>&1
echo [%date% %time%] notice_delegations exit=%ERRORLEVEL% >> gov_crawler_log.txt
echo [%date% %time%] === citation_graph start === >> gov_crawler_log.txt
%PY% build_law_citation_graph.py >> build_law_citation_graph_sched.log 2>&1
echo [%date% %time%] citation_graph exit=%ERRORLEVEL% >> gov_crawler_log.txt
rem lawmap topic-edge check (read-only; reports edges whose cited article is missing from the KB text, #123)
echo [%date% %time%] === lawmap_edge_check start === >> gov_crawler_log.txt
%PY% lawmap_edge_check.py >> lawmap_edge_check_sched.log 2>&1
echo [%date% %time%] lawmap_edge_check exit=%ERRORLEVEL% >> gov_crawler_log.txt
echo [%date% %time%] === done === >> gov_crawler_log.txt
