-- 20260802134159 create_watchdog_scan


-- 플랫폼 독립 워치독: system_health 10개 키를 키별 임계값으로 전수 감시.
-- GitHub health_watchdog.py(감시대상과 함께 죽는 사각지대)를 보완하는 Supabase 내부 감시자.
-- A 담당의 check_news_health / check_briefing_health 는 건드리지 않음 (신규 함수).
create or replace function public.watchdog_scan(p_dry_run boolean default true)
returns text
language plpgsql
security definer
set search_path = public
as $function$
declare
  r         record;
  probs     text[] := '{}';   -- 사람이 읽는 이상 문구
  sig_parts text[] := '{}';   -- 재알림 억제용 시그니처 토큰(키:유형)
  fail_n    text;
  sig       text;
  prev_sig  text;
  tok       text;
  msg       text;
  now_kst   text;
begin
  now_kst := to_char(now() at time zone 'Asia/Seoul', 'MM-DD HH24:MI');

  for r in
    select t.key, t.thresh_h, t.label,
           sh.updated_at, sh.note,
           extract(epoch from (now() - sh.updated_at))/3600 as age_h
    from (values
      ('last_crawl_run',                3.0,   '뉴스 크롤러(매시)'),
      ('last_gov_notice_run',           26.0,  '정부고시·입법예고(매일 17시)'),
      ('last_press_ingest',             26.0,  '보도자료 수집(17시 체인)'),
      ('last_law_diff_run',             26.0,  '법령 조문 DIFF(17시 체인)'),
      ('last_assembly_run',             26.0,  '국회 법안·입법예고(매일 10:30)'),
      ('last_minutes_run',              26.0,  '과방위 회의록(17시 체인)'),
      ('last_foreign_press_run',        30.0,  '해외 규제기관(매일 05:30)'),
      ('last_itu_watch_run',            960.0, 'ITU-R 권고 감시(월 1회)'),
      ('last_refetch_run',              26.0,  '본문 재수집(PC 매시)'),
      ('last_subscriber_briefing_run',  3.0,   '구독자 정시 발송(매시 :25)')
    ) as t(key, thresh_h, label)
    left join system_health sh on sh.key = t.key
  loop
    -- ① 지연(heartbeat 미갱신) 검사
    if r.updated_at is null then
      probs     := probs || (r.label || ': heartbeat 없음');
      sig_parts := sig_parts || (r.key || ':missing');
    elsif r.age_h >= r.thresh_h then
      probs     := probs || (r.label || ' ' || round(r.age_h, 1) || 'h 무갱신(임계 ' || round(r.thresh_h) || 'h)');
      sig_parts := sig_parts || (r.key || ':late');
    end if;

    -- ② 무음 의미실패: note에 fail>0 / failed>0 / 실패 N(>0) 이 있으면 '돌았지만 실패'
    if r.note ~ '(fail|failed)=[1-9]' or r.note ~ '실패\s+[1-9]' then
      fail_n    := coalesce(substring(r.note from '(?:fail|failed)=([0-9]+)'),
                            substring(r.note from '실패\s+([0-9]+)'), '?');
      probs     := probs || (r.label || ' 실패 ' || fail_n || '건 (note: ' || r.note || ')');
      sig_parts := sig_parts || (r.key || ':fail');
    end if;
  end loop;

  -- ── 정상: 억제상태 리셋 후 무음 종료 ──
  if array_length(probs, 1) is null then
    insert into system_health(key, note, updated_at)
      values ('watchdog_alert_state', 'ok', now())
      on conflict (key) do update set note = 'ok', updated_at = now();
    return 'ok: 이상 없음 (' || now_kst || ' KST)';
  end if;

  -- ── 이상 있음: 시그니처로 재알림 억제 판정 ──
  select md5(coalesce(string_agg(x, ',' order by x), '')) into sig
    from unnest(sig_parts) as x;
  select note into prev_sig from system_health where key = 'watchdog_alert_state';

  if prev_sig is distinct from sig then
    -- 새 이상 or 이상 집합 변동 → 1건 요약 발송
    if not p_dry_run then
      select decrypted_secret into tok from vault.decrypted_secrets where name = 'telegram_bot_token';
      if tok is not null then
        msg := '⚠️ [워치독] 파이프라인 이상 감지 (' || now_kst || ' KST):' || chr(10) ||
               '- ' || array_to_string(probs, chr(10) || '- ');
        perform net.http_post(
          url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
          body    := jsonb_build_object('chat_id', '<OPERATOR_CHAT_ID>', 'text', msg),
          headers := '{"Content-Type": "application/json"}'::jsonb
        );
      end if;
    end if;
    insert into system_health(key, note, updated_at)
      values ('watchdog_alert_state', sig, now())
      on conflict (key) do update set note = excluded.note, updated_at = now();
    return (case when p_dry_run then '[dry-run] 발송생략 ' else 'sent ' end)
           || array_to_string(probs, ' | ');
  else
    -- 동일 이상 반복 → 재알림 억제(발송 안 함)
    return 'suppressed(동일 이상 재알림 억제) | ' || array_to_string(probs, ' | ');
  end if;
end;
$function$;

revoke all on function public.watchdog_scan(boolean) from anon, authenticated;
;
