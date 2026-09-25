-- 20260801072732 tmp_set_subscriber_cron_secret

-- 임시 헬퍼: Vault 시크릿 등록/갱신 (값이 SQL 로그·대화에 남지 않도록 파라미터로 전달)
-- 등록 직후 DROP 한다.
create or replace function public.tmp_set_subscriber_cron_secret(p_secret text)
returns text
language plpgsql
security definer
as $$
declare v_id uuid;
begin
  select id into v_id from vault.secrets where name = 'subscriber_cron_secret';
  if v_id is null then
    perform vault.create_secret(p_secret, 'subscriber_cron_secret', '구독자 브리핑 cron → Edge Function 인증');
    return 'created';
  else
    perform vault.update_secret(v_id, p_secret);
    return 'updated';
  end if;
end;
$$;

revoke all on function public.tmp_set_subscriber_cron_secret(text) from public, anon, authenticated;;
