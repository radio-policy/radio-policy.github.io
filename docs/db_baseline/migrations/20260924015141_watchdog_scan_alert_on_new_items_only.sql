-- 20260924015141 watchdog_scan_alert_on_new_items_only

-- watchdog_scan: '이상 조합이 바뀌면' → '새 이상 항목이 생기면'만 알림 (#199, 2026-09-24 운영자 결정)
-- 종전엔 해소돼서 조합이 줄어도 재알림해, 해묵은 항목(law_watch apifail=2)이 옆 항목이 생기고 사라질 때마다
-- 4번 실려 왔다(09-23 21:10·00:10·03:10·09:10). 상태 note는 md5 대신 키 목록(쉼표)으로 저장해 차집합을 구한다.
-- 새 항목은 🆕, 이어지는 항목은 (계속) 표시. 모두 해소되면 'ok'로만 기록(해소 메시지는 보내지 않는다 — 운영자 결정).
create or replace function public.watchdog_scan(p_dry_run boolean default true)
 returns text
 language plpgsql
 security definer
 set search_path to 'public'
as $function$
declare
  r         record;
  probs     text[] := '{}';
  keys      text[] := '{}';
  fail_n    text;
  cur_set   text;
  prev_set  text;
  prev_keys text[] := '{}';
  new_keys  text[] := '{}';
  lines     text[] := '{}';
  tok       text;
  msg       text;
  now_kst   text;
  i         int;
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
    if r.updated_at is null then
      probs := probs || (r.label || ': heartbeat 없음');
      keys  := keys  || (r.key || ':missing');
    elsif r.age_h >= r.thresh_h then
      probs := probs || (r.label || ' ' || round(r.age_h, 1) || 'h 무갱신(임계 ' || round(r.thresh_h) || 'h)');
      keys  := keys  || (r.key || ':late');
    end if;

    if r.note ~ '(fail|failed)=[1-9]' or r.note ~ '실패\s+[1-9]' then
      fail_n := coalesce(substring(r.note from '(?:fail|failed)=([0-9]+)'),
                         substring(r.note from '실패\s+([0-9]+)'), '?');
      probs := probs || (r.label || ' 실패 ' || fail_n || '건 (note: ' || r.note || ')');
      keys  := keys  || (r.key || ':fail');
    end if;

    if r.note ~ 'outdated=[1-9]' then
      fail_n := substring(r.note from 'outdated=([0-9]+)');
      probs := probs || (r.label || ' — 지식베이스가 구버전인 법령 ' || fail_n ||
                         '건 (law_sync.py 로 현행화 필요)');
      keys  := keys  || (r.key || ':outdated');
    end if;
  end loop;

  if array_length(probs, 1) is null then
    insert into system_health(key, note, updated_at)
      values ('watchdog_alert_state', 'ok', now())
      on conflict (key) do update set note = 'ok', updated_at = now();
    return 'ok: 이상 없음 (' || now_kst || ' KST)';
  end if;

  select string_agg(x, ',' order by x) into cur_set from unnest(keys) as x;
  select note into prev_set from system_health where key = 'watchdog_alert_state';
  if prev_set is null or prev_set = 'ok' then
    prev_keys := '{}';
  elsif prev_set ~ '^[0-9a-f]{32}$' then
    prev_keys := keys;                      -- 종전 md5 서명 — 이전 집합을 모르므로 전부 '계속'으로(전환 직후 재알림 억제)
  else
    prev_keys := string_to_array(prev_set, ',');
  end if;
  new_keys := array(select x from unnest(keys) as x where not (x = any(prev_keys)));

  insert into system_health(key, note, updated_at)
    values ('watchdog_alert_state', cur_set, now())
    on conflict (key) do update set note = excluded.note, updated_at = now();

  if array_length(new_keys, 1) is null then
    return 'suppressed(새 이상 항목 없음) | ' || array_to_string(probs, ' | ');
  end if;

  for i in 1..array_length(probs, 1) loop
    lines := lines || ((case when keys[i] = any(new_keys) then '🆕 ' else '(계속) ' end) || probs[i]);
  end loop;
  msg := '⚠️ [워치독] 파이프라인 이상 감지 (' || now_kst || ' KST):' || chr(10) ||
         '- ' || array_to_string(lines, chr(10) || '- ');
  if not p_dry_run then
    select decrypted_secret into tok from vault.decrypted_secrets where name = 'telegram_bot_token';
    if tok is not null then
      perform net.http_post(
        url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
        body    := jsonb_build_object('chat_id', '<OPERATOR_CHAT_ID>', 'text', msg),
        headers := '{"Content-Type": "application/json"}'::jsonb
      );
    end if;
  end if;
  return (case when p_dry_run then '[dry-run] 발송생략 ' else 'sent ' end) || array_to_string(lines, ' | ');
end;
$function$;

revoke execute on function public.watchdog_scan(boolean) from public, anon, authenticated;

-- 상태를 키 목록으로 전환(발송 없음): 종전 md5가 남아 있으면 이번 호출은 전부 '계속'으로 처리돼 재알림 없이 목록만 기록된다
select public.watchdog_scan(true);;
