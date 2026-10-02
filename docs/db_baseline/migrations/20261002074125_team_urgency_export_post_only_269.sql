-- 20261002074125 team_urgency_export_post_only_269

-- #269 보강: PostgREST가 GET(쿼리스트링)으로도 이 함수를 부르므로 POST만 받는다 — 비밀값이 주소에 실려 게이트웨이 로그에 남는 호출을
-- 처음부터 실패시켜 다리 코드가 GET으로 굳지 않게 한다. PostgREST 밖(SQL 직접 호출)은 request.method가 없어 통과.
create or replace function public.team_urgency_export(p_key text) returns jsonb
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
  if coalesce(nullif(current_setting('request.method', true), ''), 'POST') <> 'POST' then
    raise exception 'team_urgency_export: POST only' using errcode = '22023';
  end if;
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

revoke all on function public.team_urgency_export(text) from public, anon, authenticated;
grant execute on function public.team_urgency_export(text) to anon, service_role;;
