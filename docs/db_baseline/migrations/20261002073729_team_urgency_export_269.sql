-- 20261002073729 team_urgency_export_269

-- #269 (2026-10-02) 사내 다리 전용: 팀 등급 사람 수정(source='human') 스냅숏. 표 team_urgency는 anon에 계속 닫아 둔다.
-- 비밀값은 DB 안에서 무작위로 만든다(이 SQL에 값이 없다 — 이주 기록에 평문으로 남지 않게). 값은 Vault와 사내 PC 저장소 밖 파일에만.
select vault.create_secret(
  encode(extensions.gen_random_bytes(32), 'hex'),
  'bridge_team_urgency_key',
  '사내 다리 team_urgency_export 비밀값 (#269) — Vault와 사내 PC 저장소 밖 파일에만 둔다');

create function public.team_urgency_export(p_key text) returns jsonb
language plpgsql security definer
set search_path = ''
set row_security = off            -- RLS가 걸리게 되면 빈 목록 대신 오류
as $$
declare
  v_secret text;
  v_cap constant int := 5000;
  v_n int;
  v_rows jsonb;
begin
  select decrypted_secret into v_secret
    from vault.decrypted_secrets where name = 'bridge_team_urgency_key';
  -- 맞을 때만 통과: Vault 값이 없거나 짧거나, 인자가 null이거나 다르면 오류(null 비교가 통과로 새지 않게)
  if v_secret is null or length(v_secret) < 32 or p_key is null or p_key <> v_secret then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  with h as (select news_id, team_id, urgency, source, updated_at
               from public.team_urgency where source = 'human')
  select (select count(*) from h),
         (select coalesce(jsonb_agg(to_jsonb(x) order by x.news_id, x.team_id), '[]'::jsonb) from h x)
    into v_n, v_rows;              -- 수와 행을 한 문장에서
  if v_n > v_cap then
    raise exception 'team_urgency_export: % rows > cap %', v_n, v_cap using errcode = '54000';
  end if;
  return jsonb_build_object('v', 1, 'generated_at', now(), 'total', v_n, 'rows', v_rows);
end $$;

comment on function public.team_urgency_export(text) is
  '#269 사내 다리 전용 — Vault bridge_team_urgency_key와 맞을 때만 사람 수정 행 전부를 {v, generated_at, total, rows}로. 틀린 키·5,000행 초과는 오류(빈 목록 아님). 모양·오류 동작·상한을 바꾸기 전에 사내판에 통보';

revoke all on function public.team_urgency_export(text) from public, anon, authenticated;
grant execute on function public.team_urgency_export(text) to anon, service_role;;
