-- 20261016072012 watchdog_law_outdated_live_20261016

-- #316 (2026-10-16): 워치독의 '구버전 법령'을 아침 점검 문구(last_law_watch_run note 'outdated=N')가 아니라
-- law_watch 표의 지금 상태로 센다. 11:00 체인은 law_watch가 구버전을 표시한 몇 초 뒤 law_sync --all-outdated가
-- 교체하는데(#183), 문구는 다음 날 점검까지 'outdated=N'으로 남아 교체가 끝난 법령을 하루 종일
-- '현행화 필요'로 알렸다(10-16 12:10 🆕 · 15:10 (계속) — 11:35:16에 이미 교체됨).
-- 세는 행 = law_sync --all-outdated가 고칠 대상과 같은 행(유령 행 #183 제외) 중
--   ① 표시된 뒤 현행화(last_law_sync_run)가 돌았는데도 남은 행, 또는 ② 표시된 지 3시간이 넘은 행(현행화가 안 돎).
-- 표시 직후 현행화가 도는 중인 행은 세지 않는다. 그 밖의 줄(무갱신·fail=N)은 그대로.
CREATE OR REPLACE FUNCTION public.watchdog_scan(p_dry_run boolean DEFAULT true)
 RETURNS text
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
  out_n     int;
  out_names text[];
  sync_at   timestamptz;
begin
  now_kst := to_char(now() at time zone 'Asia/Seoul', 'MM-DD HH24:MI');

  for r in
    select t.key, t.thresh_h, t.label, t.clock,
           sh.updated_at, sh.note,
           case when t.clock = 'biz' then public.biz_hours_between(sh.updated_at, now())
                else extract(epoch from (now() - sh.updated_at))/3600 end as age_h
    from watchdog_targets t
    left join system_health sh on sh.key = t.key
    where t.active
    order by t.key
  loop
    if r.updated_at is null then
      probs := probs || (r.label || ': heartbeat 없음');
      keys  := keys  || (r.key || ':missing');
    elsif r.age_h >= r.thresh_h then
      probs := probs || (r.label || ' ' || round(r.age_h, 1) || 'h 무갱신(' ||
                         (case when r.clock = 'biz' then '근무시간 기준, ' else '' end) ||
                         '임계 ' || round(r.thresh_h) || 'h)' ||
                         (case when r.clock = 'biz' then ' — 회사 PC·lampmanH-pc 확인' else '' end));
      keys  := keys  || (r.key || ':late');
    end if;

    if r.note ~ '(fail|failed)=[1-9]' or r.note ~ '실패\s+[1-9]' then
      fail_n := coalesce(substring(r.note from '(?:fail|failed)=([0-9]+)'),
                         substring(r.note from '실패\s+([0-9]+)'), '?');
      probs := probs || (r.label || ' 실패 ' || fail_n || '건 (note: ' || r.note || ')');
      keys  := keys  || (r.key || ':fail');
    end if;

    -- #316: 구버전은 note 의 'outdated=N'(아침 점검 시점 값)이 아니라 law_watch 표의 지금 상태로 센다.
    if r.key = 'last_law_watch_run' then
      select updated_at into sync_at from system_health where key = 'last_law_sync_run';
      select count(*), (array_agg(w.law_name order by w.law_name))[1:3]
        into out_n, out_names
      from law_watch w
      where w.sync_status = 'outdated'
        and (w.updated_at < coalesce(sync_at, '-infinity'::timestamptz)   -- 표시 뒤 현행화가 돌았는데 남음
             or w.updated_at < now() - interval '3 hours')                -- 현행화가 안 돎
        and (exists (select 1 from document_chunks c
                     where c.doc_name = w.doc_name and c.status = 'current')
             or w.law_id is null
             or not exists (select 1 from document_chunks c                -- 유령 행(#183)은 law_sync가 지운다
                            where c.law_id = w.law_id and c.status = 'current'
                              and c.doc_name <> w.doc_name));
      if out_n > 0 then
        probs := probs || (r.label || ' — 자동 현행화 뒤에도 구버전인 법령 ' || out_n || '건: ' ||
                           array_to_string(out_names, ', ') ||
                           (case when out_n > 3 then ' 외 ' || (out_n - 3) || '건' else '' end) ||
                           ' (law_sync.py 로 현행화 필요)');
        keys  := keys  || (r.key || ':outdated');
      end if;
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
$function$;;
