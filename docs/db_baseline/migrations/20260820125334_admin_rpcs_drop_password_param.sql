-- 20260820125334 admin_rpcs_drop_password_param

-- 관리 RPC에서 비밀번호 인자를 완전히 제거한다 (#104 5단계 완료, 2026-08-20).
-- 관문은 이제 admin 계정 하나뿐이다. 브라우저 외 호출자(파이썬·워크플로)는 없음을 확인했다.
do $mig$
declare
  r record; src text; newdef text; oldsig text; n int := 0;
begin
  for r in
    select p.oid, p.proname,
           pg_get_function_identity_arguments(p.oid) as idargs
      from pg_proc p join pg_namespace ns on ns.oid = p.pronamespace
     where ns.nspname = 'public'
       and pg_get_function_identity_arguments(p.oid) like '%p_pwd%'
       and p.proname <> 'admin_ok'
  loop
    src := pg_get_functiondef(r.oid);
    -- ① 인자 목록에서 p_pwd 제거 (선두/중간/말미 어느 위치든)
    newdef := regexp_replace(src, '\(\s*p_pwd\s+text\s*,\s*', '(', 'g');   -- 선두
    newdef := regexp_replace(newdef, ',\s*p_pwd\s+text\s*(?=[,)])', '', 'g'); -- 중간·말미
    newdef := regexp_replace(newdef, '\(\s*p_pwd\s+text\s*\)', '()', 'g');  -- 단독
    -- ② 관문을 is_admin()으로
    newdef := replace(newdef, 'public.admin_ok(p_pwd)', 'public.is_admin()');
    if newdef = src or newdef like '%p_pwd%' then
      raise exception '변환 실패: % (%)', r.proname, r.idargs;
    end if;
    execute newdef;                                   -- 새 시그니처로 생성
    oldsig := format('public.%I(%s)', r.proname, r.idargs);
    execute 'drop function ' || oldsig;               -- 구 시그니처 제거
    n := n + 1;
  end loop;
  raise notice '비밀번호 인자 제거: % 건', n;
end $mig$;

drop function if exists public.admin_ok(text);;
