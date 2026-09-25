-- 20260801025216 subscriber_briefing_cron

-- 구독자 브리핑 정시 발송 트리거 (dispatch_github_workflow와 동일 패턴: Vault + net.http_post)
-- 검증은 반드시 net._http_response.status_code 로 (cron job status는 비동기라 항상 succeeded — 배경역사 #18)
create or replace function public.trigger_subscriber_briefing()
returns void
language plpgsql
security definer
as $$
begin
  perform net.http_post(
    url := 'https://zwkjedumfuhodckmtxxn.supabase.co/functions/v1/send-subscriber-briefing',
    body := '{}'::jsonb,
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'x-cron-secret', (select decrypted_secret from vault.decrypted_secrets where name = 'subscriber_cron_secret')
    )
  );
end;
$$;

-- 매시 25분(KST=UTC 분 동일). 06:05~06:20 브리핑 생성 창을 피한다.
-- Edge Function 쪽에서 '수신 시각 도래 + 미발송'만 골라내므로 대상 없으면 no-op.
select cron.schedule('subscriber-briefing-hourly', '25 * * * *',
                     $$select public.trigger_subscriber_briefing()$$);;
