-- 20260820103024 chat_logs_drop_anon_select

-- 자문 이력 운영자 전용화 마지막 단계 (2026-08-20, #103 후속)
-- 대시보드가 이미 admin RPC 경유로 배포됐으므로 anon 직접 읽기를 닫는다.
-- INSERT 정책(chat_logs_ins)은 유지 — 자문 기록은 계속 쌓여야 한다.
-- 주의: SELECT 정책이 없으면 PostgREST RETURNING이 실패하므로 insert에 .select()를 붙이지 말 것.
drop policy if exists chat_logs_sel on public.chat_logs;;
