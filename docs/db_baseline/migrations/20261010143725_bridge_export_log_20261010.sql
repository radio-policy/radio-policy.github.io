-- 20261010143725 bridge_export_log_20261010

-- bridge_export_log_20261010 — 시스템 평가 ④ 보안 구현 B (판정 §3 Q4·Q7, §4 B)
-- 비밀값 RPC 3개: 키 대조 통과 직후 성공 기록 한 블록만 추가(이름·인자·돌려주는 모양·오류·상한·Vault 그대로).
-- CREATE OR REPLACE라 소유자·ACL(anon·service_role)은 그대로 남는다.

create or replace function public.people_export(p_key text)
 returns jsonb
 language plpgsql
 security definer
 set search_path to ''
 set row_security to 'off'
as $function$
declare
  v_secret text;
  v_cap constant int := 2000;
  v_n int;
  v_rows jsonb;
  v_h jsonb;
begin
  if coalesce(nullif(current_setting('request.method', true), ''), 'POST') <> 'POST' then
    raise exception 'people_export: POST only' using errcode = '22023';
  end if;
  select decrypted_secret into v_secret
    from vault.decrypted_secrets where name = 'bridge_team_urgency_key';
  -- 맞을 때만 통과: Vault 값이 없거나 짧거나, 인자가 null이거나 다르면 오류(null 비교가 통과로 새지 않게)
  if v_secret is null or length(v_secret) < 32 or p_key is null or p_key <> v_secret then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  -- 성공 호출 기록(#29x) — 실패는 raise가 되돌려 DB에 남길 수 없다. 기록 실패가 반출을 막지 않게 감싼다.
  begin
    v_h := nullif(current_setting('request.headers', true), '')::jsonb;
    insert into public.bridge_export_log (fn, ua, ip)
    values ('people_export', v_h ->> 'user-agent',
            nullif(btrim(coalesce(v_h ->> 'cf-connecting-ip', split_part(v_h ->> 'x-forwarded-for', ',', 1), v_h ->> 'x-real-ip')), ''));
  exception when others then null;
  end;
  -- 전 칸·전 행(REST select=*&order=id 와 같은 내용) — 칸 이름 순서만 jsonb 정렬을 따른다
  select (select count(*) from public.people),
         (select coalesce(jsonb_agg(to_jsonb(p) order by p.id), '[]'::jsonb) from public.people p)
    into v_n, v_rows;
  if v_n > v_cap then
    raise exception 'people_export: % rows > cap %', v_n, v_cap using errcode = '54000';
  end if;
  return jsonb_build_object('v', 1, 'generated_at', now(), 'total', v_n, 'rows', v_rows);
end $function$;

create or replace function public.team_rules_export(p_key text, p_since timestamp with time zone default null::timestamp with time zone)
 returns jsonb
 language plpgsql
 security definer
 set search_path to ''
 set row_security to 'off'
as $function$
declare
  v_secret text;
  v_rcap constant int := 2000;
  v_vcap constant int := 20000;
  v_rn int;
  v_vn int;
  v_rules jsonb;
  v_verd jsonb;
  v_h jsonb;
begin
  if coalesce(nullif(current_setting('request.method', true), ''), 'POST') <> 'POST' then
    raise exception 'team_rules_export: POST only' using errcode = '22023';
  end if;
  select decrypted_secret into v_secret
    from vault.decrypted_secrets where name = 'bridge_team_urgency_key';
  -- 맞을 때만 통과: Vault 값이 없거나 짧거나, 인자가 null이거나 다르면 오류(null 비교가 통과로 새지 않게)
  if v_secret is null or length(v_secret) < 32 or p_key is null or p_key <> v_secret then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  -- 성공 호출 기록(#29x) — 실패는 raise가 되돌려 DB에 남길 수 없다. 기록 실패가 반출을 막지 않게 감싼다.
  begin
    v_h := nullif(current_setting('request.headers', true), '')::jsonb;
    insert into public.bridge_export_log (fn, ua, ip)
    values ('team_rules_export', v_h ->> 'user-agent',
            nullif(btrim(coalesce(v_h ->> 'cf-connecting-ip', split_part(v_h ->> 'x-forwarded-for', ',', 1), v_h ->> 'x-real-ip')), ''));
  exception when others then null;
  end;
  -- 팀 규칙 행 전부(꺼진 행 포함) — anon 13칸과 같은 칸, updated_by(계정 uuid) 없음
  with r as (select id, team_id, "position", mode, level, any_words, and_any, none_words, note, enabled,
                    updated_at, sentence, sentence_rev
               from public.urgency_rules where team_id is not null)
  select count(*), coalesce(jsonb_agg(to_jsonb(r) order by r.id), '[]'::jsonb) into v_rn, v_rules from r;
  if v_rn > v_rcap then
    raise exception 'team_rules_export: rules % > cap %', v_rn, v_rcap using errcode = '54000';
  end if;
  -- 판정 done 행 — anon 9칸과 같은 칸(requested_by·cost_usd 없음), p_since null = 전부
  with v as (select rule_id, sentence_rev, news_id, team_id, status, verdict, reason, input_kind, judged_at
               from public.urgency_rule_verdicts
              where status = 'done' and (p_since is null or judged_at >= p_since))
  select count(*), coalesce(jsonb_agg(to_jsonb(v) order by v.judged_at, v.rule_id, v.sentence_rev, v.news_id), '[]'::jsonb)
    into v_vn, v_verd from v;
  if v_vn > v_vcap then
    raise exception 'team_rules_export: verdicts % > cap %', v_vn, v_vcap using errcode = '54000';
  end if;
  return jsonb_build_object('v', 1, 'generated_at', now(), 'since', p_since,
                            'rules_total', v_rn, 'verdicts_total', v_vn, 'rules', v_rules, 'verdicts', v_verd);
end $function$;

create or replace function public.team_urgency_export(p_key text)
 returns jsonb
 language plpgsql
 security definer
 set search_path to ''
 set row_security to 'off'
as $function$
declare
  v_secret text;
  v_cap constant int := 5000;
  v_n int;
  v_rows jsonb;
  v_h jsonb;
begin
  if coalesce(nullif(current_setting('request.method', true), ''), 'POST') <> 'POST' then
    raise exception 'team_urgency_export: POST only' using errcode = '22023';
  end if;
  select decrypted_secret into v_secret
    from vault.decrypted_secrets where name = 'bridge_team_urgency_key';
  -- 맞을 때만 통과: Vault 값이 없거나 짧거나, 인자가 null이거나 다르면 오류(null 비교가 통과로 새지 않게)
  if v_secret is null or length(v_secret) < 32 or p_key is null or p_key <> v_secret then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  -- 성공 호출 기록(#29x) — 실패는 raise가 되돌려 DB에 남길 수 없다. 기록 실패가 반출을 막지 않게 감싼다.
  begin
    v_h := nullif(current_setting('request.headers', true), '')::jsonb;
    insert into public.bridge_export_log (fn, ua, ip)
    values ('team_urgency_export', v_h ->> 'user-agent',
            nullif(btrim(coalesce(v_h ->> 'cf-connecting-ip', split_part(v_h ->> 'x-forwarded-for', ',', 1), v_h ->> 'x-real-ip')), ''));
  exception when others then null;
  end;
  with h as (select news_id, team_id, urgency, source, updated_at
               from public.team_urgency where source = 'human')
  select (select count(*) from h),
         (select coalesce(jsonb_agg(to_jsonb(x) order by x.news_id, x.team_id), '[]'::jsonb) from h x)
    into v_n, v_rows;              -- 수와 행을 한 문장에서
  if v_n > v_cap then
    raise exception 'team_urgency_export: % rows > cap %', v_n, v_cap using errcode = '54000';
  end if;
  return jsonb_build_object('v', 1, 'generated_at', now(), 'total', v_n, 'rows', v_rows);
end $function$;

-- security_audit() — ㉡ 허용 목록 위반 + ㉠ 권한 지문(변화 1회) + ㉣ 만료 30일 안 + 다리 출처(판정 Q7, 운영자 결정 R5·R7)
-- 허용 목록은 이 본문에만 둔다(바꾸려면 마이그레이션 = 설계도 diff). 지문·설정은 service_role 전용 표.
create or replace function public.security_audit()
 returns jsonb
 language plpgsql
 security definer
 set search_path to ''
as $function$
declare
  c_anon_definer_ok constant text[] := array['people_export', 'team_rules_export', 'team_urgency_export'];
  v_viol jsonb := '[]'::jsonb;
  v_lines text[];
  v_hash text;
  v_prev_hash text;
  v_prev_lines jsonb;
  v_changed boolean;
  v_first boolean;
  v_added jsonb := '[]'::jsonb;
  v_removed jsonb := '[]'::jsonb;
  v_due jsonb := '[]'::jsonb;
  v_known jsonb;
  v_bridge jsonb;
  v_now_kst timestamp := (now() at time zone 'Asia/Seoul');
begin
  -- ㉡-1 anon 표 권한이 SELECT 밖(예외 lawmap_proposals INSERT)
  select v_viol || coalesce(jsonb_agg(jsonb_build_object('k', 'anon_table_priv', 'obj', c.relname, 'priv', pr.p) order by c.relname, pr.p), '[]'::jsonb)
    into v_viol
    from pg_catalog.pg_class c
    cross join lateral unnest(array['INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER','MAINTAIN']) as pr(p)
   where c.relnamespace = 'public'::regnamespace and c.relkind in ('r','p','v','m','f')
     and pg_catalog.has_table_privilege('anon', c.oid, pr.p)
     and not (c.relname = 'lawmap_proposals' and pr.p = 'INSERT');
  -- ㉡-2 anon 칸 단위 권한이 SELECT 밖
  select v_viol || coalesce(jsonb_agg(jsonb_build_object('k', 'anon_column_priv', 'obj', c.relname || '.' || a.attname, 'priv', x.privilege_type)), '[]'::jsonb)
    into v_viol
    from pg_catalog.pg_attribute a
    join pg_catalog.pg_class c on c.oid = a.attrelid
    cross join lateral pg_catalog.aclexplode(a.attacl) x
   where c.relnamespace = 'public'::regnamespace and a.attacl is not null
     and x.grantee = 'anon'::regrole and x.privilege_type <> 'SELECT';
  -- ㉡-3 anon 시퀀스 권한(예외 없음)
  select v_viol || coalesce(jsonb_agg(jsonb_build_object('k', 'anon_sequence_priv', 'obj', c.relname)), '[]'::jsonb)
    into v_viol
    from pg_catalog.pg_class c
   where c.relnamespace = 'public'::regnamespace and c.relkind = 'S'
     and (pg_catalog.has_sequence_privilege('anon', c.oid, 'USAGE') or pg_catalog.has_sequence_privilege('anon', c.oid, 'SELECT')
          or pg_catalog.has_sequence_privilege('anon', c.oid, 'UPDATE'));
  -- ㉡-4 anon·public 역할 정책 중 SELECT 아닌 것(예외 lawmap_proposals_ins_anon) — public·storage 스키마
  select v_viol || coalesce(jsonb_agg(jsonb_build_object('k', 'anon_write_policy', 'obj', p.schemaname || '.' || p.tablename || ':' || p.policyname, 'priv', p.cmd)), '[]'::jsonb)
    into v_viol
    from pg_catalog.pg_policies p
   where p.schemaname in ('public', 'storage') and ('anon' = any(p.roles) or 'public' = any(p.roles)) and p.cmd <> 'SELECT'
     and not (p.schemaname = 'public' and p.tablename = 'lawmap_proposals' and p.policyname = 'lawmap_proposals_ins_anon');
  -- ㉡-5 anon EXECUTE SECURITY DEFINER(예외 비밀값 RPC 3) · ㉡-6 PUBLIC EXECUTE SECURITY DEFINER(예외 없음)
  select v_viol || coalesce(jsonb_agg(jsonb_build_object('k', 'anon_exec_definer', 'obj', p.oid::regprocedure::text)), '[]'::jsonb)
    into v_viol
    from pg_catalog.pg_proc p
   where p.pronamespace = 'public'::regnamespace and p.prosecdef
     and pg_catalog.has_function_privilege('anon', p.oid, 'EXECUTE')
     and not (p.proname = any(c_anon_definer_ok));
  select v_viol || coalesce(jsonb_agg(jsonb_build_object('k', 'public_exec_definer', 'obj', p.oid::regprocedure::text)), '[]'::jsonb)
    into v_viol
    from pg_catalog.pg_proc p
   where p.pronamespace = 'public'::regnamespace and p.prosecdef
     and pg_catalog.has_function_privilege('public', p.oid, 'EXECUTE');
  -- ㉡-5b 반대 방향: 허용 목록 3개는 anon 실행권이 있어야 한다(drop & create로 잃으면 사내 다리가 401 — 사내 rp-smoke만 보던 것)
  select v_viol || coalesce(jsonb_agg(jsonb_build_object('k', 'anon_exec_missing', 'obj', ok.n)), '[]'::jsonb)
    into v_viol
    from unnest(c_anon_definer_ok) as ok(n)
   where not exists (select 1 from pg_catalog.pg_proc p
                      where p.pronamespace = 'public'::regnamespace and p.proname = ok.n and p.prosecdef
                        and pg_catalog.has_function_privilege('anon', p.oid, 'EXECUTE'));
  -- ㉡-7 기본 권한: postgres·public에 anon(표·시퀀스·함수) 또는 authenticated(함수), postgres 전역 함수 항목에 PUBLIC 또는 항목 없음
  select v_viol || coalesce(jsonb_agg(jsonb_build_object('k', 'default_acl', 'obj', 'postgres/public/' || d.defaclobjtype::text, 'priv', x.grantee::regrole::text)), '[]'::jsonb)
    into v_viol
    from pg_catalog.pg_default_acl d
    cross join lateral pg_catalog.aclexplode(d.defaclacl) x
   where d.defaclrole = 'postgres'::regrole and d.defaclnamespace = 'public'::regnamespace
     and x.grantee <> 0
     and (x.grantee = 'anon'::regrole or (d.defaclobjtype = 'f' and x.grantee = 'authenticated'::regrole));
  if not exists (select 1 from pg_catalog.pg_default_acl d
                  where d.defaclrole = 'postgres'::regrole and d.defaclnamespace = 0 and d.defaclobjtype = 'f'
                    and not exists (select 1 from pg_catalog.aclexplode(d.defaclacl) x where x.grantee = 0)) then
    v_viol := v_viol || jsonb_build_array(jsonb_build_object('k', 'default_acl', 'obj', 'postgres/(global)/f', 'priv', 'PUBLIC'));
  end if;
  -- ㉡-8 security_invoker 꺼진 public 뷰 · ㉡-9 RLS 꺼진 public 표
  select v_viol || coalesce(jsonb_agg(jsonb_build_object('k', 'view_not_invoker', 'obj', c.relname)), '[]'::jsonb)
    into v_viol
    from pg_catalog.pg_class c
   where c.relnamespace = 'public'::regnamespace and c.relkind = 'v'
     and not coalesce(c.reloptions && array['security_invoker=on','security_invoker=true','security_invoker=1','security_invoker=yes'], false);
  select v_viol || coalesce(jsonb_agg(jsonb_build_object('k', 'rls_off', 'obj', c.relname)), '[]'::jsonb)
    into v_viol
    from pg_catalog.pg_class c
   where c.relnamespace = 'public'::regnamespace and c.relkind in ('r','p') and not c.relrowsecurity;
  -- ㉡-10 anon SELECT 정책은 있는데 GRANT(표·칸)가 없음 / anon SELECT GRANT(표·칸)는 있는데 그 표에 정책이 하나도 없음
  with t as (
    select c.oid, c.relname,
           exists (select 1 from pg_catalog.pg_attribute a where a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped
                     and pg_catalog.has_column_privilege('anon', c.oid, a.attnum, 'SELECT')) as anon_sel,
           exists (select 1 from pg_catalog.pg_policies p where p.schemaname = 'public' and p.tablename = c.relname
                     and p.cmd in ('SELECT','ALL') and ('anon' = any(p.roles) or 'public' = any(p.roles))) as anon_pol,
           exists (select 1 from pg_catalog.pg_policy p where p.polrelid = c.oid) as any_pol
      from pg_catalog.pg_class c
     where c.relnamespace = 'public'::regnamespace and c.relkind in ('r','p'))
  select v_viol || coalesce(jsonb_agg(jsonb_build_object('k', case when anon_pol and not anon_sel then 'anon_policy_no_grant' else 'anon_grant_no_policy' end, 'obj', relname)), '[]'::jsonb)
    into v_viol
    from t
   where (anon_pol and not anon_sel) or (anon_sel and not any_pol);

  -- ㉠ 권한 지문: anon·authenticated·PUBLIC 표/칸/함수 권한, 정책, 기본 권한, RLS, 뷰 옵션
  select array_agg(l order by l) into v_lines from (
    select 'rel|' || c.relname || '|' || coalesce(nullif(x.grantee::regrole::text, '-'), 'PUBLIC') || '|' || x.privilege_type as l
      from pg_catalog.pg_class c cross join lateral pg_catalog.aclexplode(c.relacl) x
     where c.relnamespace = 'public'::regnamespace and c.relkind in ('r','p','v','m','S','f')
       and (x.grantee = 0 or x.grantee in ('anon'::regrole, 'authenticated'::regrole))
    union all
    select 'col|' || c.relname || '.' || a.attname || '|' || coalesce(nullif(x.grantee::regrole::text, '-'), 'PUBLIC') || '|' || x.privilege_type
      from pg_catalog.pg_attribute a join pg_catalog.pg_class c on c.oid = a.attrelid
      cross join lateral pg_catalog.aclexplode(a.attacl) x
     where c.relnamespace = 'public'::regnamespace and a.attacl is not null
       and (x.grantee = 0 or x.grantee in ('anon'::regrole, 'authenticated'::regrole))
    union all
    select 'fn|' || p.oid::regprocedure::text || '|' || r.rn || '|' || case when p.prosecdef then 'definer' else 'invoker' end
           || '|' || coalesce(array_to_string(p.proconfig, ','), '')
      from pg_catalog.pg_proc p
      cross join lateral unnest(array['anon','authenticated','public']) as r(rn)
     where p.pronamespace = 'public'::regnamespace and p.prokind in ('f','p')
       and pg_catalog.has_function_privilege(r.rn, p.oid, 'EXECUTE')
    union all
    select 'pol|' || p.schemaname || '.' || p.tablename || '|' || p.policyname || '|' || array_to_string(p.roles, ',') || '|' || p.cmd
           || '|' || coalesce(p.qual, '') || '|' || coalesce(p.with_check, '')
      from pg_catalog.pg_policies p where p.schemaname in ('public', 'storage')
    union all
    select 'dacl|' || d.defaclrole::regrole::text || '|'
           || case when d.defaclnamespace = 0 then '(global)' else d.defaclnamespace::regnamespace::text end || '|'
           || d.defaclobjtype::text || '|' || d.defaclacl::text
      from pg_catalog.pg_default_acl d
     where d.defaclrole in ('postgres'::regrole, 'supabase_admin'::regrole)
       and (d.defaclnamespace = 0 or d.defaclnamespace in ('public'::regnamespace, 'extensions'::regnamespace))
    union all
    -- 설정(출처 목록·만료일)은 값 대신 md5만 — 바뀌면 1회 알림, 알림 문구에 값이 실리지 않게
    select 'cfg|' || s.key || '|' || md5(s.value::text) from public.security_config s
    union all
    select 'rls|' || c.relname || '|' || c.relrowsecurity::text || '|' || c.relforcerowsecurity::text
      from pg_catalog.pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind in ('r','p')
    union all
    select 'view|' || c.relname || '|' || coalesce(array_to_string(c.reloptions, ','), '')
      from pg_catalog.pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind = 'v'
  ) s;
  v_hash := md5(array_to_string(v_lines, E'\n'));

  select l.hash, l.lines into v_prev_hash, v_prev_lines
    from public.security_audit_log l where l.lines is not null order by l.at desc, l.id desc limit 1;
  v_first := v_prev_hash is null;
  v_changed := v_first or v_prev_hash <> v_hash;
  if v_changed and not v_first then
    select coalesce(jsonb_agg(l order by l), '[]'::jsonb) into v_added
      from unnest(v_lines) l where not (v_prev_lines ? l);
    select coalesce(jsonb_agg(l order by l), '[]'::jsonb) into v_removed
      from jsonb_array_elements_text(v_prev_lines) l where not (l = any(v_lines));
  end if;
  insert into public.security_audit_log (hash, lines, violations, changed)
  values (v_hash, case when v_changed then to_jsonb(v_lines) end, v_viol, v_changed);

  -- 보존 90일(마지막 기준 행은 남김) · bridge_export_log 90일
  delete from public.security_audit_log l
   where l.at < now() - interval '90 days'
     and l.id <> (select l2.id from public.security_audit_log l2 where l2.lines is not null order by l2.at desc, l2.id desc limit 1);
  delete from public.bridge_export_log b where b.at < now() - interval '90 days';

  -- ㉣ 만료 30일 안(만료일 있는 것만 — 정기 교체 없음, 운영자 결정 10-10)
  select coalesce(jsonb_agg(jsonb_build_object('name', e.key, 'expires', e.value) order by e.value), '[]'::jsonb) into v_due
    from public.security_config s
    cross join lateral jsonb_each_text(s.value) e
   where s.key = 'secret_expiry'
     and e.value ~ '^\d{4}-\d{2}-\d{2}$'
     and e.value::date <= (v_now_kst::date + 30);

  -- 다리 출처(Q4): 지난 24시간 성공 호출·알려진 출처 밖·오늘(KST) 평일 10~18시 호출
  select s.value into v_known from public.security_config s where s.key = 'bridge_known_sources';
  with b as (
    select fn, ua, ip, at,
           (ua is null and ip is null) as no_hdr,
           (v_known is not null
            and exists (select 1 from jsonb_array_elements_text(v_known -> 'ua_prefixes') u where b0.ua like u || '%')
            and exists (select 1 from jsonb_array_elements_text(v_known -> 'ip_prefixes') i where b0.ip like i || '%')) as known
      from public.bridge_export_log b0
     where b0.at > now() - interval '24 hours')
  select jsonb_build_object(
           'calls_24h', (select count(*) from b),
           'by_fn', (select coalesce(jsonb_object_agg(fn, n), '{}'::jsonb) from (select fn, count(*) n from b group by fn) f),
           'unknown', (select coalesce(jsonb_agg(jsonb_build_object('ua', ua, 'ip16', split_part(ip, '.', 1) || '.' || split_part(ip, '.', 2), 'n', n)), '[]'::jsonb)
                         from (select ua, ip, count(*) n from b where not no_hdr and not known group by ua, ip) u),
           'known_config', v_known is not null,
           'weekday_today', extract(isodow from v_now_kst) between 1 and 5,
           'biz_calls_today', (select count(*) from public.bridge_export_log b1
                                where (b1.at at time zone 'Asia/Seoul')::date = v_now_kst::date
                                  and extract(hour from (b1.at at time zone 'Asia/Seoul')) >= 10
                                  and extract(hour from (b1.at at time zone 'Asia/Seoul')) < 18))
    into v_bridge;

  return jsonb_build_object(
    'v', 1, 'at', now(), 'violations', v_viol, 'changed', v_changed, 'first', v_first,
    'hash', v_hash, 'n_lines', coalesce(array_length(v_lines, 1), 0),
    'added', v_added, 'removed', v_removed, 'secrets_due', v_due, 'bridge', v_bridge);
end $function$;

revoke execute on function public.security_audit() from public, anon, authenticated;
grant execute on function public.security_audit() to service_role;
comment on function public.security_audit() is
  '보안 정기 점검(#29x): 허용 목록 위반·권한 지문 변화(1회)·만료 30일 안·비밀값 RPC 출처. health_watchdog.py 21:30이 service_role로 부른다. 허용 목록은 이 본문에만 둔다.';
;
