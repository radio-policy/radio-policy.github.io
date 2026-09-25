-- 20260920020056 chat_logs_cite_verdicts_176

-- #176 (2026-09-20): 자문 답변의 인용 검증 판정 목록을 남긴다 — 검증기 오탐률을 세는 재료.
alter table public.chat_logs add column if not exists cite_verdicts jsonb;
comment on column public.chat_logs.cite_verdicts is '인용 검증기(cite_verify.js) 판정 목록 [{key,status,reason,doc,...}] — status: ok/missing/mismatch/unclear/unjudged/nocheck/noclaim/unparsed/dup (#176)';;
