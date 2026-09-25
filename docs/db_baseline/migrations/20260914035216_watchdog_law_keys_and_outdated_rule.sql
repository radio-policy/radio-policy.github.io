-- 20260914035216 watchdog_law_keys_and_outdated_rule

-- 법령 현행화 3종을 감시에 넣는다 (#169-보론2). 셋 다 system_health 기록이 0회라
-- 구조적으로 감시 대상이 될 수 없었고, 그 사이 방송통신사업 금지행위 업무처리규정이
-- 4개월째 구버전인 채 current 로 제공되고 있었다. 11:00 KST law_crawl 체인 = 하루 1회 → 26h.
insert into public.watchdog_targets(key, thresh_h, label, note) values
  ('last_law_crawl_run',  26.0, '법령·고시 수집(매일 11:00)',      '2026-09-14 등록 (#169-보론2)'),
  ('last_law_sync_run',   26.0, '법령 현행화 등재(11:00 체인)',    '2026-09-14 등록 (#169-보론2)'),
  ('last_law_watch_run',  26.0, '법령 현행성 점검(11:00 체인)',    '2026-09-14 등록 (#169-보론2)')
on conflict (key) do nothing;

-- note 의 outdated=N(N>0)도 '돌았지만 결과가 나쁘다'로 잡는다.
-- fail=N 은 '실행이 깨졌다', outdated=N 은 '실행은 됐는데 KB가 낡았다' — 둘 다 사람이 봐야 한다.
create or replace function public.watchdog_scan(p_dry_run boolean default true)
returns text
language plpgsql
security definer
set search_path to 'public'
as $function$
declare
  r         record;
  probs     text[] := '{}';
  sig_parts text[] := '{}';
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
    if r.updated_at is null then
      probs     := probs || (r.label || ': heartbeat 없음');
      sig_parts := sig_parts || (r.key || ':missing');
    elsif r.age_h >= r.thresh_h then
      probs     := probs || (r.label || ' ' || round(r.age_h, 1) || 'h 무갱신(임계 ' || round(r.thresh_h) || 'h)');
      sig_parts := sig_parts || (r.key || ':late');
    end if;

    if r.note ~ '(fail|failed)=[1-9]' or r.note ~ '실패\s+[1-9]' then
      fail_n    := coalesce(substring(r.note from '(?:fail|failed)=([0-9]+)'),
                            substring(r.note from '실패\s+([0-9]+)'), '?');
      probs     := probs || (r.label || ' 실패 ' || fail_n || '건 (note: ' || r.note || ')');
      sig_parts := sig_parts || (r.key || ':fail');
    end if;

    if r.note ~ 'outdated=[1-9]' then
      fail_n    := substring(r.note from 'outdated=([0-9]+)');
      probs     := probs || (r.label || ' — 지식베이스가 구버전인 법령 ' || fail_n ||
                             '건 (law_sync.py 로 현행화 필요)');
      sig_parts := sig_parts || (r.key || ':outdated');
    end if;
  end loop;

  if array_length(probs, 1) is null then
    insert into system_health(key, note, updated_at)
      values ('watchdog_alert_state', 'ok', now())
      on conflict (key) do update set note = 'ok', updated_at = now();
    return 'ok: 이상 없음 (' || now_kst || ' KST)';
  end if;

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
