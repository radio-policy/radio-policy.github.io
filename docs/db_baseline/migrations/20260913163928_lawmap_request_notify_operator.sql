-- 20260913163928 lawmap_request_notify_operator

-- 관계도 '추가 요청'(origin='request')이 들어오면 운영자 봇으로 알린다.
-- 알림 실패가 요청 저장을 막지 않도록 예외를 삼킨다(handle_new_user와 같은 방식).
create or replace function public.notify_lawmap_request()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  tok text;
begin
  if new.origin is distinct from 'request' then
    return new;
  end if;
  begin
    select decrypted_secret into tok from vault.decrypted_secrets where name = 'telegram_bot_token';
    if tok is not null then
      perform net.http_post(
        url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
        body    := jsonb_build_object(
          'chat_id', '<OPERATOR_CHAT_ID>',
          'text', '🗺️ 관계도 추가 요청' || E'\n'
               || '요청자: ' || coalesce(nullif(new.requester, ''), '(미상)') || E'\n'
               || '주제: ' || coalesce(nullif(new.topic, ''), '(미입력)') || E'\n'
               || coalesce(nullif(new.question, ''), '(사유 없음)') || E'\n'
               || '→ 대시보드 법령 관계도 > 검토 대기에서 처리'
        ),
        headers := '{"Content-Type":"application/json"}'::jsonb,
        timeout_milliseconds := 10000
      );
    end if;
  exception when others then
    raise warning '[관계도 요청 알림 실패(요청은 정상 저장)] %', sqlerrm;
  end;
  return new;
end $$;

drop trigger if exists trg_notify_lawmap_request on public.lawmap_proposals;
create trigger trg_notify_lawmap_request
  after insert on public.lawmap_proposals
  for each row execute function public.notify_lawmap_request();;
