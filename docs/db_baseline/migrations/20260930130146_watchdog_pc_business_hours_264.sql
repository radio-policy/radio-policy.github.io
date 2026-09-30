-- 20260930130146 watchdog_pc_business_hours_264

-- #264 (2026-09-30): PC 예약작업(정부 공고 체인·본문 재수집)을 회사 PC로 옮김.
-- 회사 PC는 평일 09:30~18:00에만 켜져 있어, 이 키들의 무갱신 시간을 '근무시간'으로 센다(밤·주말은 세지 않음).
-- 공휴일·휴가는 근무일로 센다 — 그날은 「회사 PC 확인」이 한 번 나간다(알고 있는 날이면 무시).

create or replace function public.biz_hours_between(p_from timestamptz, p_to timestamptz default now())
returns numeric
language sql
stable
set search_path to 'public'
as $$
  select coalesce(sum(greatest(0, extract(epoch from (least(p_to, d.e) - greatest(p_from, d.s))))), 0)::numeric / 3600.0
  from (
    select ((g::date + time '09:30') at time zone 'Asia/Seoul') as s,
           ((g::date + time '18:00') at time zone 'Asia/Seoul') as e,
           g::date as day
    from generate_series((p_from at time zone 'Asia/Seoul')::date::timestamp,
                         (p_to   at time zone 'Asia/Seoul')::date::timestamp,
                         interval '1 day') g
  ) d
  where extract(isodow from d.day) < 6
$$;

alter table public.watchdog_targets add column if not exists clock text not null default 'wall';
alter table public.watchdog_targets drop constraint if exists watchdog_targets_clock_chk;
alter table public.watchdog_targets add constraint watchdog_targets_clock_chk check (clock in ('wall', 'biz'));
comment on column public.watchdog_targets.clock is 'wall = 실제 경과 시간, biz = 근무시간(평일 09:30~18:00 KST)만 센 경과 시간 — 회사 PC 예약작업용(#264)';

update public.watchdog_targets set clock = 'biz', thresh_h = 10, label = '정부고시·입법예고(회사 PC 평일 16:30)' where key = 'last_gov_notice_run';
update public.watchdog_targets set clock = 'biz', thresh_h = 10, label = '법령 조문 DIFF(16:30 체인)'            where key = 'last_law_diff_run';
update public.watchdog_targets set clock = 'biz', thresh_h = 10, label = '과방위 회의록(16:30 체인)'             where key = 'last_minutes_run';
update public.watchdog_targets set clock = 'biz', thresh_h = 10, label = '보도자료 수집(16:30 체인)'             where key = 'last_press_ingest';
update public.watchdog_targets set clock = 'biz', thresh_h = 3,  label = '본문 재수집(회사 PC 10분마다)'          where key = 'last_refetch_run';

-- 외부 워치독(health_watchdog.py)·대시보드 운영 상태가 같은 계산을 쓰도록 — 근무시간 기준 키의 나이를 돌려준다.
create or replace function public.pc_heartbeat_ages()
returns table(key text, updated_at timestamptz, thresh_h numeric, age_h numeric, label text)
language sql
stable
set search_path to 'public'
as $$
  select t.key, sh.updated_at, t.thresh_h,
         case when sh.updated_at is null then null
              else round(public.biz_hours_between(sh.updated_at, now()), 2) end as age_h,
         t.label
  from public.watchdog_targets t
  left join public.system_health sh on sh.key = t.key
  where t.active and t.clock = 'biz'
  order by t.key
$$;

revoke all on function public.biz_hours_between(timestamptz, timestamptz) from public, anon, authenticated, service_role;
grant execute on function public.biz_hours_between(timestamptz, timestamptz) to anon, authenticated, service_role;
revoke all on function public.pc_heartbeat_ages() from public, anon, authenticated, service_role;
grant execute on function public.pc_heartbeat_ages() to anon, authenticated, service_role;

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
                         (case when r.clock = 'biz' then ' — 회사 PC 확인' else '' end));
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
$function$;;
