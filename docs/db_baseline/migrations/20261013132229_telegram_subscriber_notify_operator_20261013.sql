-- 20261013132229 telegram_subscriber_notify_operator_20261013

-- 텔레그램 구독자 봇에 새 구독자가 생기면(telegram_subscribers 새 행) 운영자 봇으로 즉시 알린다 (#301, 2026-10-13 운영자 요청).
-- 발송 패턴은 handle_new_user·notify_lawmap_request와 같다(Vault telegram_bot_token + net.http_post, 운영자 봇, 10초).
-- AFTER INSERT만 — 웹훅 upsert가 기존 행을 고치는 경우(설정 토글·/start 다시 누름·사용 횟수)는 UPDATE라 알리지 않는다.
-- 알림은 부가 기능 — 실패해도 구독 행 저장은 반드시 성공해야 하므로 예외를 삼킨다.
create or replace function public.notify_new_telegram_subscriber()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  tok text;
  n int;
begin
  begin
    select count(*) into n from public.telegram_subscribers where active;
    select decrypted_secret into tok from vault.decrypted_secrets where name = 'telegram_bot_token';
    if tok is not null then
      perform net.http_post(
        url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
        body    := jsonb_build_object(
          'chat_id', '<OPERATOR_CHAT_ID>',
          'text', '🆕 텔레그램 구독 시작' || E'\n'
               || '이름: ' || coalesce(nullif(left(new.first_name, 64), ''), '(없음)') || E'\n'
               || '아이디: ' || coalesce('@' || nullif(new.username, ''), '(없음)') || E'\n'
               || 'chat_id: ' || new.chat_id::text || E'\n'
               || '지금 구독자 ' || n || '명' || E'\n'
               || '→ 팀·계정 연결은 대시보드 설정 > 텔레그램 구독자'
        ),
        headers := '{"Content-Type":"application/json"}'::jsonb,
        timeout_milliseconds := 10000
      );
    end if;
  exception when others then
    raise warning '[구독 시작 알림 실패(구독은 정상)] %', sqlerrm;
  end;
  return new;
end $$;

revoke all on function public.notify_new_telegram_subscriber() from public, anon, authenticated;

drop trigger if exists trg_notify_new_telegram_subscriber on public.telegram_subscribers;
create trigger trg_notify_new_telegram_subscriber
  after insert on public.telegram_subscribers
  for each row execute function public.notify_new_telegram_subscriber();;
