-- 20260913164302 lawmap_request_notify_mark_anon

-- 요청자 표기를 검증된 것처럼 보이게 하면 안 된다: 비로그인 요청은 이름을 자기가 적은 것이므로
-- 메시지에 '비로그인'을 명시한다.
create or replace function public.notify_lawmap_request()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  tok text;
  who text;
begin
  if new.origin is distinct from 'request' then
    return new;
  end if;
  if new.created_by is null then
    who := '비로그인 · ' || coalesce(nullif(new.requester, ''), '(이름 미입력)') || ' (자기 기재, 미확인)';
  else
    who := coalesce(nullif(new.requester, ''), '(미상)');
  end if;
  begin
    select decrypted_secret into tok from vault.decrypted_secrets where name = 'telegram_bot_token';
    if tok is not null then
      perform net.http_post(
        url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
        body    := jsonb_build_object(
          'chat_id', '<OPERATOR_CHAT_ID>',
          'text', '🗺️ 관계도 추가 요청' || E'\n'
               || '요청자: ' || who || E'\n'
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
end $$;;
