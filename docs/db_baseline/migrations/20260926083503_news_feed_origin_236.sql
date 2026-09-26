-- 20260926083503 news_feed_origin_236

-- #236 (2026-09-26) news_feed.origin — 이슈맵 보강으로 넣은 옛 기사 표시(사내판 인계, 운영자 결정 (가))
alter table public.news_feed add column if not exists origin text;
comment on column public.news_feed.origin is '출처 구분(#236): NULL = 정규 수집(크롤러·정부 공고·방미통위·해외), ''issuemap'' = 이슈맵 보강(ihelp.link_news·news-archive-search)으로 넣은 옛 기사. created_at이 넣은 시각이라 created_at으로 새 기사를 고르는 곳은 origin is null만 볼 것';

-- 기존 보강 기사 표시: 이슈에 연결 + 본문·본문수집·선별 흔적 없음 + 읽음·잠금 상태로 들어온 행
--  (분류 '기타'로 넣은 것 385건 + 8/26 세션이 분류를 붙여 넣은 3건 = 388건, 2026-09-26 17:3x 실측)
update public.news_feed n set origin = 'issuemap'
where n.origin is null
  and n.id::text in (select item_id from public.issue_links where item_type = 'news')
  and n.content is null and n.content_fetched_at is null and n.urgency_screen is null and n.is_read and n.locked
  and ( n.category = '기타'
        or (n.created_at - n.published_at > interval '3 days'
            and exists (select 1 from public.issue_links l
                        where l.item_type = 'news' and l.item_id = n.id::text
                          and l.added_by in ('session', 'auto')
                          and abs(extract(epoch from (n.created_at - l.created_at))) < 300)) );

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
  -- 이슈맵 보강 기사(origin='issuemap', 옛 기사를 지금 넣음)는 '마지막 입력'에서 뺀다 — 크롤러 고장을 가리지 않게(#236)
  SELECT max(created_at) INTO last_news FROM news_feed WHERE origin IS NULL;
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

NOTIFY pgrst, 'reload schema';;
