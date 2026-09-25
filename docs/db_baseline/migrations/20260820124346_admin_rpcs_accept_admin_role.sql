-- 20260820124346 admin_rpcs_accept_admin_role

-- 관리 RPC의 관문을 '비밀번호'에서 '비밀번호 또는 admin 계정'으로 넓힌다 (#104 5단계).
-- 계정 체계가 자리잡았으므로 대시보드는 비밀번호를 더 이상 묻지 않는다. 다만 기존 호출부
-- (구버전 캐시 번들·스크립트)가 남아 있을 수 있어 비밀번호 경로는 당분간 함께 남긴다.
create or replace function public.admin_ok(p_pwd text default '')
returns boolean
language sql stable security definer set search_path to 'public','extensions' as $$
  select public.is_admin()
      or encode(digest(coalesce(p_pwd, ''), 'sha256'), 'hex')
         = '<REDACTED:hex_digest>';
$$;
grant execute on function public.admin_ok(text) to anon, authenticated;

do $mig$
declare
  r record;
  src text;
  patched text;
  n int := 0;
begin
  for r in
    select p.oid, p.proname
      from pg_proc p join pg_namespace ns on ns.oid = p.pronamespace
     where ns.nspname = 'public'
       and pg_get_function_identity_arguments(p.oid) like '%p_pwd%'
       and p.proname <> 'admin_ok'
  loop
    src := pg_get_functiondef(r.oid);
    -- 대소문자·공백 차이를 모두 흡수해 관문 한 줄만 교체
    patched := regexp_replace(
      src,
      '(?i)if\s+encode\(\s*digest\(\s*p_pwd\s*,\s*''sha256''\s*\)\s*,\s*''hex''\s*\)\s+is\s+distinct\s+from\s+''164eab[0-9a-f]+''\s+then',
      'IF NOT public.admin_ok(p_pwd) THEN',
      'g');
    if patched = src then
      raise notice '관문 미발견(건너뜀): %', r.proname;
    else
      execute patched;
      n := n + 1;
    end if;
  end loop;
  raise notice '관문 교체 완료: % 건', n;
end $mig$;

-- 교체 결과 확인용: 이제 해시 상수를 직접 쓰는 함수는 admin_ok 하나여야 한다
select p.proname,
       (pg_get_functiondef(p.oid) like '%admin_ok(p_pwd)%') as uses_helper,
       (pg_get_functiondef(p.oid) like '%164eab%')          as still_has_hash
from pg_proc p join pg_namespace ns on ns.oid = p.pronamespace
where ns.nspname = 'public' and pg_get_function_identity_arguments(p.oid) like '%p_pwd%'
order by p.proname;;
