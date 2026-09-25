-- 20260821094439 signup_telegram_alert

-- 가입 신청 → 운영자 텔레그램 즉시 알림 (2026-08-21, #104 후속)
-- 승인 대기자가 생겨도 운영자가 대시보드를 열기 전까지 모르는 공백을 없앤다.
-- 발송 패턴은 check_news_health와 동일(Vault telegram_bot_token + net.http_post, 운영자 봇).
-- ★ 알림은 부가 기능 — 실패해도 가입(프로필 생성)은 반드시 성공해야 하므로 예외를 삼킨다.
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
        headers := '{"Content-Type":"application/json"}'::jsonb
      );
    end if;
  exception when others then
    raise warning '[가입 알림 실패(가입은 정상)] %', sqlerrm;
  end;

  return new;
end $$;;
