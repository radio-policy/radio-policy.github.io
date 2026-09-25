-- 20260924110803 advisory_search_meta_and_role_timeout_15s

-- #203 (2026-09-24) 운영자 결정 ②: 로그인 사용자·봇(service_role) 역할 한도 8s → 15s (anon 3s 유지).
-- trgm RPC(search_chunks_trgm 6~9s)가 8s에 잘려 조용히 0건이 되던 것(#201)을 결과 불변으로 해소. 되돌리기: '8s'.
alter role authenticated set statement_timeout = '15s';
alter role service_role set statement_timeout = '15s';
-- PostgREST가 impersonated role 설정을 다시 읽게 한다
notify pgrst, 'reload config';

-- 검색 갈래별 기록(fail-open 실패 가시화): [{fn, ms, rows, error}] — app.js·rag.ts buildAdvisoryContext가 채운다
alter table public.chat_logs add column if not exists search_meta jsonb;
comment on column public.chat_logs.search_meta is '검색 갈래별 기록 [{fn,ms,rows,error}] — trgm 57014 등 fail-open 실패 가시화(#203, 2026-09-24)';

-- 검증용 임시 프로브(적용 확인 뒤 다음 마이그레이션에서 삭제): 9.5초 대기 후 현재 한도 반환
create or replace function public.rpc_timeout_probe(p_sec double precision default 9.5)
returns text language sql stable security invoker as $$
  select current_setting('statement_timeout') from pg_sleep(p_sec);
$$;
revoke all on function public.rpc_timeout_probe(double precision) from public, anon;
grant execute on function public.rpc_timeout_probe(double precision) to authenticated, service_role;;
