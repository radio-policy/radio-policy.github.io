-- 20260914032654 watchdog_scan_reads_targets

-- 감시 목록만 watchdog_targets 에서 읽도록 바꾼다. 지연 검사·무음 의미실패(fail=N) 검사·
-- 시그니처 재알림 억제 로직은 그대로다(#169).
create or replace function public.watchdog_scan(p_dry_run boolean default true)
returns text
language plpgsql
security definer
set search_path to 'public'
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
    from watchdog_targets t
    left join system_health sh on sh.key = t.key
    where t.active
    order by t.key
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
    return 'suppressed(동일 이상 재알림 억제) | ' || array_to_string(probs, ' | ');
  end if;
end;
$function$;;
