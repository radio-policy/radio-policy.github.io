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

- Dashboard: https://radio-policy.gitlab.io/ (GitHub Pages)
- Supabase project `zwkjedumfuhodckmtxxn` (ap-northeast-1 / Tokyo)

## Architecture (big picture)

```
[collect] Python crawlers ──▶ [Supabase DB + Edge + Storage] ──▶ [dashboard / Telegram / email]
                                        ▲
             [schedule] Supabase pg_cron (PRIMARY trigger) + GitHub Actions cron (backup)
```

**Collection** — each crawler writes to a table and a `system_health` heartbeat:
- `crawler.py` — news via Naver Search OpenAPI (falls back to Google RSS). 넓은 키워드 54개 수집 → Haiku 관련성 1차 선별(app_config `news_relevance_criteria`, 무관은 저장 안 함, 실패 시 키워드 폴백, 부처 인사는 무조건 통과) → 통과분만 본문 수집·Haiku 긴급도 분류(피드백 학습) (#66). Runs in GitHub Actions hourly.
- `gov_notice_crawler.py` — government notices (RRA/MSIT/방통위/전파관리소/ETRI/KISDI) + 입법예고. **PC-local only** (Korean IP required; government sites block foreign IPs) — do NOT move to GitHub Actions. At the end it calls `press_ingest.run_daily()` — full-text press-release ingestion into the KB (6 agencies, 최근 15일 전수 수집 + Haiku 관련성 판정, keyword fallback) + auto embedding backfill. 주의: kmcc.go.kr은 전파관리소가 아니라 방송미디어통신위원회(구 방통위) 새 도메인이며, 전파관리소는 crms.go.kr (#53).
- `law_crawler.py` (법제처 DRF API, endpoint `www.law.go.kr/DRF/lawSearch.do`), `assembly_crawler.py` (열린국회정보 API — 법안 수집 + **국회 입법예고 패스**: `nknalejkafmvgzmpt` 전량 수신 → Haiku 의미 판정(app_config `assembly_notice_criteria`) → 의견마감 배지·운영자 알림, #56), `refetch_content.py` (body re-fetch via trafilatura, PC-local). 국회 입법예고 법안의 조문 분석(신구조문대비표 → proposed DIFF, origin='assembly')은 `law_diff_gen.py --assembly-only`.

**Briefing/alerts** — `morning_briefing.py` sends 06:00 KST email(with analysis)/Telegram(without). Zero-news days still send a "🕊️ no news" notice so silent failure isn't mistaken for breakage.

**Two Telegram bots, deliberately separate** — the operator bot (`TELEGRAM_BOT_TOKEN`) pushes to one person immediately, as it always has. The subscriber bot `정책 AI도우미` (`SUBSCRIBER_BOT_TOKEN`, added 2026-08-01; renamed from `정책AI 도우미` 2026-08-02) is interactive: `/start` opens an inline keyboard, and briefing + urgent news + assembly bills all arrive **once at the subscriber's chosen hour** (6–12), never immediately. Crawlers therefore *queue* into `subscriber_queue` instead of sending — the suppression/clustering verdicts (#44) stay in Python and are not reimplemented in TS. Two Edge Functions back this: `telegram-webhook` (commands, `/law` article lookup, `/ask` advisory behind per-chat_id approval + 20/day cap) and `send-subscriber-briefing` (hourly pg_cron, `briefing_hour <= now` catch-up). Source lives in `supabase/functions/`; deploy with the Supabase CLI (needs `SUPABASE_ACCESS_TOKEN` in `.env` — the MCP transfer route fails past ~50 KB). **`/ask` reads its system prompt from `app_config.system_prompt`, so run `python sync_system_prompt.py` after editing `system_prompt.js` or the bot answers with a stale prompt (or fails outright).**

**Dashboard frontend** — `index.html` + `app.js` (~270 KB, single file) + `styles.css`, plus `system_prompt.js`. Two AI features, both **SSE-streamed (`stream:true`) — do not revert to non-streaming** (2 min+ responses hit an idle "Failed to fetch"):
- *AI advisory*: RAG 3-way hybrid — keyword `ilike`+`search_chunks_trgm`, plus Voyage embedding → `match_chunks_semantic` (pgvector) → hybrid rank → Claude Sonnet.
- *Report draft*: learns format/tone from the operator's own reports (stored whole, **not chunked**) + RAG for factual grounding; 3 personalization channels (spoken directives / red-pen edit-diff / 👍👎) with auto-redistillation.

**Dashboard accounts (2026-08-20, #104)** — browsing (news/briefing/bills/KB) stays fully public; only **AI-generating** features sit behind login. The browser holds **no Anthropic key**: all 14 call sites go through `claudeFetch()` → the `claude-proxy` Edge Function, which verifies the Supabase Auth JWT with `auth.getUser()` (`verify_jwt` alone is *not* a gate — it accepts the anon key), requires `profiles.approved`, and charges a daily quota. Quota kind is decided server-side by `body.stream === true` (advisory/report-draft) — never by a client header, which is forgeable. Org model: `teams` (경쟁제도팀/기술정책팀/AI정책팀, each with a team-wide daily cap) × `profiles` (role `admin`/`leader`/`member`, own cap, `approved`). Signup is self-service → pending → admin approves in 설정 → 계정 관리. `chat_logs` reads are RLS-scoped: own rows / leader sees their team / admin sees all (telegram rows have no `user_id`, so admin-only). Streaming through the proxy **must** use `TransformStream` + `EdgeRuntime.waitUntil(pipeTo)` or long answers are cut off mid-stream.

**Scheduling is dual** — Supabase **pg_cron is the primary trigger** (GitHub cron drops jobs unreliably); GitHub Actions cron is backup. An external `health_watchdog.py` (independent of Supabase) distinguishes "broken" from "no news." See the pg_cron job table in the 지침.

**Shared utilities (2026-08-02, #58)** — new code MUST reuse these instead of re-implementing:
`notify.send_telegram(text, *, chat_id, parse_mode, disable_web_page_preview)` for Telegram (handles
3800-char splitting, retries, 429 Retry-After; `health_watchdog.py` stays deliberately independent) and
`embed_util.get_embeddings(texts, ...)` for Voyage embeddings. Smoke tests live in `tests/test_smoke.py`
(stdlib unittest, no network) — run `python -m unittest discover -s tests` after touching shared logic.

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

# 보도자료 (2026-08-02 자동화 — #53)
python press_ingest.py --dry-run          # 6개 기관 수집 시험 (DB 무변경)
python press_backfill.py --agency 방통위  # 특정 기관 백필/델타 (dedupe라 재실행 안전)
# 키워드·AI 판정 기준문은 app_config(press_keywords/press_relevance_criteria)가 원본

# 법령 DIFF·해외·회의록 (2026-08-02 신설 — #54)
python law_diff_gen.py --dry-run --backfill   # 시행예정/승격 쌍의 조문 diff (실행은 17시 체인)
python foreign_press.py --dry-run             # FCC·Ofcom·BEREC·日총무성·ITU (05:30 스케줄)
python assembly_minutes.py --dry-run --limit 1  # 과방위 회의록 (17시 체인, 뷰어가 정본·PDF 폴백) + 발언자별 assembly_speeches 적재(#67)
```

There is no build step, linter, or test suite — the dashboard is static files served by GitHub Pages, and the crawlers are run directly. Validate JS changes with `node --check` on the changed function.

## Deploy / commit workflow (Windows PC — critical)

- **push는 `gitlab`·`origin` 두 원격 모두** (2026-08-25~, GitHub 계정 복구로 이중화 완성). **주 저장소는 GitLab**(`gitlab.com/radio-policy/radio-policy.gitlab.io`), GitHub(`origin`)은 실시간 미러 — 두 Pages(radio-policy.gitlab.io / youjinwoong.github.io)가 **같은 커밋에서 자동 재빌드되어 상시 동일**하게 유지되므로, 한쪽이 죽으면 다른 주소가 즉시 예비가 된다(알림 링크는 GitLab 주소 사용). 워크플로는 저장소에 커밋하지 않으므로(크롤은 Supabase에만 씀) 두 원격이 어긋날 원인은 세션 커밋뿐이다. gitlab 인증은 **`C:\Users\SKTelecom\.gitlab-credentials` 파일**(credential store helper, URL 평문 토큰 금지), origin 인증은 Windows 자격 증명 관리자.
- **세션 커밋 규칙 3줄** (여러 창·맥북 공통): ① 작업 시작 전 `git pull gitlab main` ② 커밋·푸시는 작업한 세션이 직접 하되 **동시에 커밋하는 세션은 하나만** ③ 커밋 후 즉시 **`git push gitlab main && git push origin main`(둘 다)** + 원격 대조 — 미푸시를 쌓아두지 않는다. origin push가 실패해도 gitlab push가 성공했으면 백업은 확보된 것 — origin은 다음 기회에 따라잡으면 된다(반대는 불가).
- **Session commits are allowed only with the 3-step verification** (relaxed 2026-07-31, 배경역사 #37): ① check the tail of each target file is intact before committing, ② `git add` explicit filenames only, ③ after push, verify remote==local (`git fetch gitlab` → rev-parse match + `git diff gitlab/main -- <files>` is empty + remote file tail intact). If ③ mismatches, do NOT re-push — investigate first. The old Cowork sandbox (stale/truncating mount — it once pushed a file with its end cut off, handoff §4-1) remains banned from committing; the relaxation applies to sessions whose git view of the repo is verifiably consistent.
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
- Supabase is on the **Pro (paid) plan** (2026-08-02 확인 — 8GB DB incl.; the real bottleneck is compute RAM 2GB, so REINDEX after bulk loads). Don't create additional projects. Emails only reach you.jinwoong@gmail.com (Resend domain unverified).

## First-response runbook

When something looks wrong, first open the dashboard **운영 상태(ops status)** tab (crawler heartbeats, news input, today's briefing, 입법예고, assembly at a glance). The 지침's "점검 체크리스트" maps each symptom (briefing not received / news not accumulating / all triggers silent / heartbeat stopped but scheduler "ran") to its diagnosis.
