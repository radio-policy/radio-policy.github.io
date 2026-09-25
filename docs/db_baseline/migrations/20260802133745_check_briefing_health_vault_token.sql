-- 20260802133745 check_briefing_health_vault_token

CREATE OR REPLACE FUNCTION public.check_briefing_health()
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
  briefing_exists boolean;
  today_kst       date;
  msg             text;
  tok             text;
BEGIN
  today_kst := (NOW() AT TIME ZONE 'Asia/Seoul')::date;

  SELECT EXISTS (
    SELECT 1 FROM daily_briefings
    WHERE briefing_date = today_kst
  ) INTO briefing_exists;

  IF NOT briefing_exists THEN
    SELECT decrypted_secret INTO tok FROM vault.decrypted_secrets WHERE name = 'telegram_bot_token';
    IF tok IS NULL THEN RETURN; END IF;

    msg := '⚠️ [헬스체크] ' || today_kst::text || ' 모닝 브리핑이 10:00 KST까지 생성되지 않았습니다. GitHub Actions 확인 필요.';

    PERFORM net.http_post(
      url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
      body    := jsonb_build_object('chat_id', '<OPERATOR_CHAT_ID>', 'text', msg),
      headers := '{"Content-Type": "application/json"}'::jsonb
    );
  END IF;
END;
$function$;;
