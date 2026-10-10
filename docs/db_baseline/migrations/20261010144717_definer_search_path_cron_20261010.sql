-- 20261010144717 definer_search_path_cron_20261010

-- definer_search_path_cron_20261010 — 보안 구현 C-2 (판정 Q6 ③(b))
-- pg_cron이 부르는 6개. 본문의 public 표·vector 타입만 스키마 한정, 나머지(vault.·net.·pg_catalog)는 그대로.
-- 적용 전 되돌리는 시험(새 정의로 각 1회 — 브리핑 짧음·없음 갈래 포함, 큐 +6 → 전체 롤백) 통과(10-10 23:4x).

alter function public.trigger_subscriber_briefing() set search_path = '';
alter function public.trigger_admin_report() set search_path = '';

create or replace function public.trigger_briefing_if_missing()
 returns void
 language plpgsql
 security definer
 set search_path to ''
as $function$
DECLARE
  today_kst date;
  briefing_exists boolean;
BEGIN
  today_kst := (NOW() AT TIME ZONE 'Asia/Seoul')::date;
  SELECT EXISTS (SELECT 1 FROM public.daily_briefings WHERE briefing_date = today_kst) INTO briefing_exists;
  IF NOT briefing_exists THEN
    PERFORM net.http_post(
      url := 'https://api.github.com/repos/radio-policy/radio-policy.github.io/actions/workflows/morning_briefing.yml/dispatches',
      body := jsonb_build_object('ref','main'),
      headers := jsonb_build_object(
        'Authorization', 'Bearer ' || (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name='github_pat'),
        'Accept','application/vnd.github+json',
        'User-Agent','supabase-pg-cron-radiopolicy',
        'X-GitHub-Api-Version','2022-11-28'
      )
    );
  END IF;
END;
$function$;

create or replace function public.check_briefing_health()
 returns void
 language plpgsql
 security definer
 set search_path to ''
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
    FROM public.daily_briefings
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
$function$;

create or replace function public.check_news_health()
 returns void
 language plpgsql
 security definer
 set search_path to ''
as $function$
DECLARE
  last_news    timestamptz;
  last_crawl   timestamptz;
  hours_stale  numeric;
  crawl_stale  numeric;
  crawler_ok   boolean;
  tok          text;
  msg          text;
BEGIN
  -- 이슈맵 보강 기사(origin='issuemap', 옛 기사를 지금 넣음)는 '마지막 입력'에서 뺀다 — 크롤러 고장을 가리지 않게(#236)
  SELECT max(created_at) INTO last_news FROM public.news_feed WHERE origin IS NULL;
  hours_stale := EXTRACT(EPOCH FROM (now() - coalesce(last_news, 'epoch')))/3600;

  -- 크롤러 heartbeat: 최근 3시간 내 실행 기록이 있으면 '크롤러 정상'으로 간주
  SELECT updated_at INTO last_crawl FROM public.system_health WHERE key = 'last_crawl_run';
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

create or replace function public.batch_update_embeddings(p_ids bigint[], p_embeddings text[])
 returns void
 language plpgsql
 security definer
 set search_path to ''
as $function$
DECLARE
  i int;
BEGIN
  FOR i IN 1..array_length(p_ids, 1) LOOP
    UPDATE public.document_chunks
    SET embedding = p_embeddings[i]::public.vector(1024)
    WHERE id = p_ids[i];
  END LOOP;
END;
$function$;;
