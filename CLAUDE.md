# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Authoritative docs — read these first

This repo's operating knowledge lives in two hand-maintained Korean documents, not in code comments. Read them before any non-trivial change:

- **[전파정책AI_지침_운영핵심.md](전파정책AI_지침_운영핵심.md)** — operational core: system structure, full DB schema, pg_cron schedule, the "must-check" runbook, and a 40+ item **"하지 말아야 할 것"(do-not) guardrail list**. Every entry is a scar from a real incident. Apply on every task.
- **[전파정책AI_배경역사.md](전파정책AI_배경역사.md)** — background/history: the detailed why behind each guardrail, past-incident postmortems (#15–#19), dates, commit hashes.
- **[HANDOFF.md](HANDOFF.md)** — account-handoff procedure (multiple people share this same PC/folder under one Windows account).

**Doc-update rule (from the guidelines):** when you add a crawler/script/workflow, change scheduling, change a Supabase table, change a notification channel, change system flow, or discover a new constraint → update *both* the 지침 (rule + one-line reason) and the 배경역사 (detailed account), and provide the full updated text of both. Pure bugfixes with no behavior change are exempt.

## What this is

SKT Comm Center 기술정책팀's radio/telecom **policy-monitoring automation system**, run by a single operator. Crawlers gather government notices, laws, national-assembly bills, and news into Supabase; a morning briefing goes out daily; a GitHub Pages dashboard offers RAG-based AI advisory and report-draft generation.

- Dashboard: https://youjinwoong.github.io/radio-policy-ai/ (GitHub Pages)
- Supabase project `zwkjedumfuhodckmtxxn` (ap-northeast-1 / Tokyo)

## Architecture (big picture)

```
[collect] Python crawlers ──▶ [Supabase DB + Edge + Storage] ──▶ [dashboard / Telegram / email]
                                        ▲
             [schedule] Supabase pg_cron (PRIMARY trigger) + GitHub Actions cron (backup)
```

**Collection** — each crawler writes to a table and a `system_health` heartbeat:
- `crawler.py` — news via Naver Search OpenAPI (falls back to Google RSS), Haiku urgency classification with feedback learning. Runs in GitHub Actions hourly.
- `gov_notice_crawler.py` — government notices (RRA/MSIT/KCC) + 입법예고. **PC-local only** (Korean IP required; government sites block foreign IPs) — do NOT move to GitHub Actions.
- `law_crawler.py` (법제처 DRF API, endpoint `www.law.go.kr/DRF/lawSearch.do`), `assembly_crawler.py` (열린국회정보 API), `refetch_content.py` (body re-fetch via trafilatura, PC-local).

**Briefing/alerts** — `morning_briefing.py` sends 06:00 KST email(with analysis)/Telegram(without). Zero-news days still send a "🕊️ no news" notice so silent failure isn't mistaken for breakage.

**Dashboard frontend** — `index.html` + `app.js` (~270 KB, single file) + `styles.css`, plus `system_prompt.js`. Two AI features, both **SSE-streamed (`stream:true`) — do not revert to non-streaming** (2 min+ responses hit an idle "Failed to fetch"):
- *AI advisory*: RAG 3-way hybrid — keyword `ilike`+`search_chunks_trgm`, plus Voyage embedding → `match_chunks_semantic` (pgvector) → hybrid rank → Claude Sonnet. Also live-queries the team's internal Confluence (Server/DC) via the `confluence-search` Edge Function — the PAT stays in a Supabase Edge Secret (never in the browser), results inject as `[팀문서]` context. Fails soft: advisory still works if Confluence is down/unconfigured. See 지침 §Edge Function + do-not list, 배경역사 #20.
- *Report draft*: learns format/tone from the operator's own reports (stored whole, **not chunked**) + RAG for factual grounding; 3 personalization channels (spoken directives / red-pen edit-diff / 👍👎) with auto-redistillation.

**Scheduling is dual** — Supabase **pg_cron is the primary trigger** (GitHub cron drops jobs unreliably); GitHub Actions cron is backup. An external `health_watchdog.py` (independent of Supabase) distinguishes "broken" from "no news." See the pg_cron job table in the 지침.

**Shared DB client** — every Python script MUST create its Supabase client via `sb_client.make_client(url, key)`, never `create_client` directly. This forces HTTP/1.1 (supabase-py 2.31 negotiates HTTP/2, which the endpoint drops → `RemoteProtocolError: Server disconnected`). Applies to new scripts too.

## Commands

```bash
# One-time PC dependency for body extraction
pip install trafilatura
# Or full lock set (do not un-pin — see below)
pip install -r requirements.txt

# Run crawlers manually (need the matching keys in .env)
python crawler.py             # news — confirm "[네이버 뉴스] N건 수집" with N>0
python law_crawler.py         # laws/notices
python assembly_crawler.py    # assembly bills
python gov_notice_crawler.py  # gov notices + 입법예고 (Korean IP)
python refetch_content.py     # body re-fetch (Korean IP, trafilatura)

# Briefing / embeddings
python resend_briefing.py [date]        # resend a briefing
python backfill_embeddings.py           # document_chunks embeddings (NULL only)
python backfill_report_embeddings.py    # report_samples embeddings (NULL only) — run after registering/promoting a report
python upload_law_pdf.py <file> "<name>" 고시   # upload law/notice/ITU-R to RAG
```

There is no build step, linter, or test suite — the dashboard is static files served by GitHub Pages, and the crawlers are run directly. Validate JS changes with `node --check` on the changed function.

## Deploy / commit workflow (Windows PC — critical)

- **Session commits are allowed only with the 3-step verification** (relaxed 2026-07-31, 배경역사 #37): ① check the tail of each target file is intact before committing, ② `git add` explicit filenames only, ③ after push, verify remote==local (`git fetch` → rev-parse match + `git diff origin/main -- <files>` is empty + remote file tail intact). If ③ mismatches, do NOT re-push — investigate first. The old Cowork sandbox (stale/truncating mount — it once pushed a file with its end cut off, handoff §4-1) remains banned from committing; the relaxation applies to sessions whose git view of the repo is verifiably consistent.
- **Always `git add <explicit filename>` — never `git add -A` / `git add .`** A stale mount can silently revert other files back to an old version and push the revert.
- **Bump the dashboard cache-buster** in `index.html` (`app.js?v=` and `styles.css?v=` when CSS changes) on every deploy, or browsers keep the old bundle. Verify remotely: `git show HEAD:index.html | findstr "app.js?v="`.
- **`.bat` files: ASCII + CRLF only** (`.gitattributes` enforces `*.bat eol=crlf`; the rest of the repo is LF). UTF-8 Korean + LF makes Korean-locale `cmd` mis-parse lines and run arbitrary commands. **After editing a .bat, verify bytes (bareLF=0, nonASCII=0) — `git status` shows LF-corrupted .bat as clean** because of eol normalization; the Write/Edit tools save LF, so write .bat via PowerShell `[IO.File]::WriteAllText(..., ASCII)` with `` `r`n ``. (#22)
- Only one Claude session may commit to this repo at a time (concurrent commits → stale-revert incident).

## Non-obvious constraints (full list in the 지침's do-not section)

- **Don't un-pin `requirements.txt`** in workflows — an auto-latest upgrade caused the HTTP/2 breakage. Bump one package at a time and verify via a workflow Run.
- **GitHub PAT** lives in Supabase Vault `github_pat` (fine-grained, `radio-policy-commit`). Required scopes: Contents(R/W) + Metadata + **Actions(R/W)**. If Actions is missing, `git push` still works but `workflow_dispatch` returns 403 while pg_cron reports `succeeded` → all triggers stop **silently**. Verify a swap by `net._http_response.status_code` (204=ok), not by cron job status. (#18)
- **PC local scripts must keep `sys.stdout.reconfigure(encoding="utf-8")`** — the Windows scheduler captures output as cp949 and emoji `print` crashes with `UnicodeEncodeError`, silently killing the heartbeat. Manual terminals (UTF-8) look fine, causing misdiagnosis. (#19)
- **Keep Windows Task Scheduler "start in" path at `radio-policy-ai`** (not the old `…\frequence\전파정책전문가`). (#19)
- **Call Python by full path** `C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe` in scheduler tasks, .bat files, and manual runs — a bare `python` resolves to Python 3.13 (installed 2026-06-30, no packages) and dies with `ModuleNotFoundError`. All packages live in 3.12 only. (#22)
- **Clear `HTTP_PROXY`/`HTTPS_PROXY` before running crawlers manually from a Claude session** — the session shell injects a corporate proxy (150.2.127.249:9090) that breaks SSL verification for gov/news sites (0건 collected, but Supabase heartbeat still updates → looks like "ran fine, nothing new"). Machine/User env vars are clean, so scheduled (SYSTEM) runs are unaffected.
- Ministry-personnel news (`is_ministry_personnel_news()` in `crawler.py`) is always collected — don't remove. Keyword lists: use `전파간섭`, not `혼신` (`이혼신고` false positive).
- Supabase free slots (2) are both used — don't propose a new project. Emails only reach you.jinwoong@gmail.com (Resend domain unverified).

## First-response runbook

When something looks wrong, first open the dashboard **운영 상태(ops status)** tab (crawler heartbeats, news input, today's briefing, 입법예고, assembly at a glance). The 지침's "점검 체크리스트" maps each symptom (briefing not received / news not accumulating / all triggers silent / heartbeat stopped but scheduler "ran") to its diagnosis.
