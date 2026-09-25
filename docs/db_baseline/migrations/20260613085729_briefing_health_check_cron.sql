-- 20260613085729 briefing_health_check_cron


-- 1. 익스텐션 활성화
CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_net;

-- 2. 헬스체크 함수 생성
CREATE OR REPLACE FUNCTION check_briefing_health()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  briefing_exists boolean;
  today_kst       date;
  msg             text;
BEGIN
  today_kst := (NOW() AT TIME ZONE 'Asia/Seoul')::date;

  SELECT EXISTS (
    SELECT 1 FROM daily_briefings
    WHERE briefing_date = today_kst
  ) INTO briefing_exists;

  IF NOT briefing_exists THEN
    msg := '⚠️ [헬스체크] ' || today_kst::text || ' 모닝 브리핑이 10:00 KST까지 생성되지 않았습니다. GitHub Actions 확인 필요.';

    PERFORM net.http_post(
      url     := 'https://api.telegram.org/bot<REDACTED:telegram_bot_token>/sendMessage',
      body    := jsonb_build_object('chat_id', '<OPERATOR_CHAT_ID>', 'text', msg),
      headers := '{"Content-Type": "application/json"}'::jsonb
    );
  END IF;
END;
$$;

-- 3. pg_cron 스케줄 등록 (매일 01:00 UTC = 10:00 KST)
--    기존 동명 job이 있으면 삭제 후 재등록
SELECT cron.unschedule('briefing-health-check') WHERE EXISTS (
  SELECT 1 FROM cron.job WHERE jobname = 'briefing-health-check'
);

SELECT cron.schedule(
  'briefing-health-check',
  '0 1 * * *',
  'SELECT check_briefing_health();'
);
;
