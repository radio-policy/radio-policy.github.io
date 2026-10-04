-- 20261004092842 people_export_rpc_20261004

-- #279 (2026-10-04, 운영자 결정 A안) 인물 화면 승인 계정 전용 — 사내 다리(export_snapshot.py)가 anon REST 대신 읽을 길.
-- team_urgency_export·team_rules_export와 같은 방식: POST만, Vault bridge_team_urgency_key가 맞을 때만, 통째 스냅샷.
-- people anon 읽기 회수(people_anon_revoke_*)는 사내 다리가 이 길로 바꾼 뒤에 한다.
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
  -- 전 칸·전 행(REST select=*&order=id 와 같은 내용) — 칸 이름 순서만 jsonb 정렬을 따른다
  select (select count(*) from public.people),
         (select coalesce(jsonb_agg(to_jsonb(p) order by p.id), '[]'::jsonb) from public.people p)
    into v_n, v_rows;
  if v_n > v_cap then
    raise exception 'people_export: % rows > cap %', v_n, v_cap using errcode = '54000';
  end if;
  return jsonb_build_object('v', 1, 'generated_at', now(), 'total', v_n, 'rows', v_rows);
end $function$;

revoke all on function public.people_export(text) from public, anon, authenticated, service_role;
grant execute on function public.people_export(text) to anon;
grant execute on function public.people_export(text) to service_role;;
