-- 20260924111155 drop_rpc_timeout_probe

-- #203 검증용 임시 프로브 제거(service_role 경로 pg_sleep(9.5) → '15s' 확인 완료)
drop function if exists public.rpc_timeout_probe(double precision);;
