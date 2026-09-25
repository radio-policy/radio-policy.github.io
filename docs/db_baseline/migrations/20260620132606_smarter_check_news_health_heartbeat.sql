-- 20260620132606 smarter_check_news_health_heartbeat

CREATE OR REPLACE FUNCTION public.check_news_health()
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
  last_news    timestamptz;
  last_crawl   timestamptz;
  hours_stale  numeric;
  crawl_stale  numeric;
  crawler_ok   boolean;
  tok          text;
  msg          text;
BEGIN
  SELECT max(created_at) INTO last_news FROM news_feed;
  hours_stale := EXTRACT(EPOCH FROM (now() - coalesce(last_news, 'epoch')))/3600;

  -- 크롤러 heartbeat: 최근 3시간 내 실행 기록이 있으면 '크롤러 정상'으로 간주
  SELECT updated_at INTO last_crawl FROM system_health WHERE key = 'last_crawl_run';
  crawl_stale := EXTRACT(EPOCH FROM (now() - coalesce(last_crawl, 'epoch')))/3600;
  crawler_ok  := (last_crawl IS NOT NULL AND crawl_stale < 3);

  -- 뉴스가 14h+ 멈췄을 때:
  --  · 크롤러도 안 돎 → 진짜 고장 → 경고
  --  · 크롤러는 도는데 새 뉴스만 없음 → 30h 전까지 침묵(주말 오경보 방지), 30h+면 조용한 실패 의심 → 경고
  IF last_news IS NULL
     OR (hours_stale >= 14 AND NOT crawler_ok)
     OR (hours_stale >= 30) THEN

    SELECT decrypted_secret INTO tok FROM vault.decrypted_secrets WHERE name = 'telegram_bot_token';
    IF tok IS NULL THEN RETURN; END IF;

    msg := '⚠️ [헬스체크] 뉴스 수집이 ' || round(hours_stale, 1) ||
           '시간째 멈춰 있습니다 (마지막 입력: ' ||
           coalesce(to_char(last_news AT TIME ZONE 'Asia/Seoul', 'MM-DD HH24:MI') || ' KST', '없음') || '). ' ||
           CASE WHEN crawler_ok
                THEN '크롤러는 정상 실행 중이나 새 기사가 없습니다 — NAVER 키·필터 점검 권장.'
                ELSE '크롤러도 미실행 — 크롤러/Supabase 트리거(crawl-trigger-hourly)·GitHub Actions 확인 필요.'
           END;

    PERFORM net.http_post(
      url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
      body    := jsonb_build_object('chat_id', '<OPERATOR_CHAT_ID>', 'text', msg),
      headers := '{"Content-Type":"application/json"}'::jsonb
    );
  END IF;
END;$function$;
