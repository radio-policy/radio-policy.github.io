-- 20260821094616 signup_telegram_alert_timeout

-- 가입 알림의 pg_net 제한시간 5s→10s (첫 실측에서 TLS 핸드셰이크만 5초를 넘겨 유실됨)
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path to 'public' as $$
declare
  v_name text := coalesce(new.raw_user_meta_data->>'name', '');
  tok text;
begin
  insert into public.profiles (user_id, name)
  values (new.id, v_name)
  on conflict (user_id) do nothing;

  begin
    select decrypted_secret into tok from vault.decrypted_secrets where name = 'telegram_bot_token';
    if tok is not null then
      perform net.http_post(
        url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
        body    := jsonb_build_object(
          'chat_id', '<OPERATOR_CHAT_ID>',
          'text', '🆕 대시보드 가입 신청' || E'\n'
               || '이름: ' || coalesce(nullif(v_name, ''), '(미입력)') || E'\n'
               || '이메일: ' || coalesce(new.email, '?') || E'\n'
               || '→ 대시보드 설정 > 계정 관리에서 팀·역할 지정 후 승인'
        ),
        headers := '{"Content-Type":"application/json"}'::jsonb,
        timeout_milliseconds := 10000
      );
    end if;
  exception when others then
    raise warning '[가입 알림 실패(가입은 정상)] %', sqlerrm;
  end;

  return new;
end $$;;
