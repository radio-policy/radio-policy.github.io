-- 20260924142255 b9_ops_system_prompt_hash

-- B-9(#210): 봇·검증기가 읽는 app_config.system_prompt와 대시보드 파일(system_prompt.js)의 동기화 확인용.
-- 행 자체는 RLS로 클라이언트에 숨겨져 있으므로(app_config_sel: key <> 'system_prompt') 내용 대신 길이·SHA-256만 돌려준다.
create or replace function public.ops_system_prompt_hash()
returns jsonb
language sql
stable
security definer
set search_path = public, pg_catalog
as $$
  select coalesce(
    (select jsonb_build_object('ok', true, 'len', length(value),
                               'sha256', encode(sha256(convert_to(value, 'UTF8')), 'hex'))
       from app_config where key = 'system_prompt'),
    jsonb_build_object('ok', false));
$$;
revoke all on function public.ops_system_prompt_hash() from public, anon;
grant execute on function public.ops_system_prompt_hash() to authenticated, service_role;;
