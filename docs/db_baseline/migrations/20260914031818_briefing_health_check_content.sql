-- 20260914031818 briefing_health_check_content

-- 헬스체크가 '행이 있나'만 봐서, 2026-09-14 문장 중간에서 잘린 브리핑이 '정상'으로 집계됐다.
-- 존재 + 최소 길이 + 꼬리표('[저장 결과]')까지 본다. 브리핑은 항상 이 꼬리표로 끝난다.
create or replace function public.check_briefing_health()
returns void
language plpgsql
security definer
as $function$
DECLARE
  today_kst date;
  b         record;
  msg       text;
  tok       text;
BEGIN
  today_kst := (NOW() AT TIME ZONE 'Asia/Seoul')::date;

  SELECT length(content) AS len,
         (content LIKE '%[저장 결과]%') AS has_tail
    INTO b
    FROM daily_briefings
   WHERE briefing_date = today_kst;

  IF b IS NULL THEN
    msg := '⚠️ [헬스체크] ' || today_kst::text || ' 모닝 브리핑이 10:00 KST까지 생성되지 않았습니다. GitHub Actions 확인 필요.';
  ELSIF b.len < 1500 THEN
    msg := '⚠️ [헬스체크] ' || today_kst::text || ' 브리핑이 너무 짧습니다(' || b.len || '자). 생성 실패나 간이 브리핑일 수 있습니다.';
  ELSIF NOT b.has_tail THEN
    msg := '⚠️ [헬스체크] ' || today_kst::text || ' 브리핑에 [저장 결과] 꼬리표가 없습니다 — 길이 제한에서 잘렸을 가능성이 큽니다(' || b.len || '자).';
  ELSE
    RETURN;
  END IF;

  SELECT decrypted_secret INTO tok FROM vault.decrypted_secrets WHERE name = 'telegram_bot_token';
  IF tok IS NULL THEN RETURN; END IF;

  PERFORM net.http_post(
    url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
    body    := jsonb_build_object('chat_id', '<OPERATOR_CHAT_ID>', 'text', msg),
    headers := '{"Content-Type": "application/json"}'::jsonb
  );
END;
$function$;;
