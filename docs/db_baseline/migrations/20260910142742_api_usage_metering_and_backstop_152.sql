-- 20260910142742 api_usage_metering_and_backstop_152

-- #152 계측·폭주 방지 (2026-09-10)
-- 1) API 토큰 사용량 기록 — Python 스크립트가 호출마다 1행 insert(service_role). 관리자만 열람.
create table if not exists public.api_usage (
  id            bigserial primary key,
  ts            timestamptz not null default now(),
  host          text not null default 'pc',      -- actions / pc / edge
  site          text not null,                   -- '<script>.py:<function>'
  model         text,
  input_tokens  int not null default 0,
  cache_read    int not null default 0,
  cache_write   int not null default 0,
  output_tokens int not null default 0
);
create index if not exists api_usage_ts_idx on public.api_usage (ts desc);
alter table public.api_usage enable row level security;
drop policy if exists api_usage_admin_select on public.api_usage;
create policy api_usage_admin_select on public.api_usage for select to authenticated using (public.is_admin());

-- 2) 시간당 일반(Haiku) 호출 카운터 — 세션·스크립트가 브라우저를 대신 눌러 하루 한도를 몇 분 만에 비우는 것 방지
create table if not exists public.ai_usage_hour (
  user_id uuid not null references auth.users(id) on delete cascade,
  hour    timestamptz not null,
  count   int not null default 0,
  primary key (user_id, hour)
);

-- 3) charge_ai_usage v2: general 백스톱 300→100/일, 시간당 60. 그 외 로직은 v1과 동일.
create or replace function public.charge_ai_usage(p_user uuid, p_kind text)
 returns jsonb
 language plpgsql
 security definer
 set search_path to 'public'
as $function$
declare
  v_day   date := (now() at time zone 'Asia/Seoul')::date;   -- KST 일자 = 리셋 기준
  v_hour  timestamptz := date_trunc('hour', now());
  v_prof  public.profiles%rowtype;
  v_team  public.teams%rowtype;
  v_used  int;
  v_hour_used int := 0;
  v_team_used int := 0;
  v_team_limit int := null;
begin
  if p_kind not in ('advisory','general') then
    return jsonb_build_object('ok', false, 'reason', 'bad_kind');
  end if;

  -- fail-closed: 승인·활성 상태가 아니면 어떤 호출도 통과시키지 않는다
  select * into v_prof from public.profiles
    where user_id = p_user and approved and active;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_approved');
  end if;

  -- 같은 팀의 동시 요청을 직렬화(팀 합산 한도가 경쟁으로 넘어가는 것 방지)
  perform pg_advisory_xact_lock(hashtext('aiq-' || coalesce(v_prof.team_id, 0)::text));

  insert into public.advisory_usage as u (user_id, day, kind, count)
  values (p_user, v_day, p_kind, 1)
  on conflict (user_id, day, kind) do update set count = u.count + 1
  returning u.count into v_used;

  if p_kind = 'general' then
    -- 경량 호출은 한도 대상이 아니고 남용 방지 백스톱만.
    -- #152(2026-09-10): 300→100/일 + 시간당 60. 관측된 정상 최대가 30/일이라 3배 여유.
    -- KB 대량 등록 등 정당한 대량 작업은 관리자 profile.unlimited로 우회한다(지침 참조).
    insert into public.ai_usage_hour as h (user_id, hour, count)
    values (p_user, v_hour, 1)
    on conflict (user_id, hour) do update set count = h.count + 1
    returning h.count into v_hour_used;

    if (v_used > 100 or v_hour_used > 60) and not v_prof.unlimited then
      update public.advisory_usage set count = count - 1
        where user_id = p_user and day = v_day and kind = p_kind;
      update public.ai_usage_hour set count = count - 1
        where user_id = p_user and hour = v_hour;
      return jsonb_build_object('ok', false,
        'reason', case when v_hour_used > 60 then 'hourly_backstop' else 'general_backstop' end,
        'used', v_used, 'hour_used', v_hour_used);
    end if;
    return jsonb_build_object('ok', true);
  end if;

  -- 개인 한도
  if not v_prof.unlimited and v_used > v_prof.daily_limit then
    update public.advisory_usage set count = count - 1
      where user_id = p_user and day = v_day and kind = p_kind;
    return jsonb_build_object('ok', false, 'reason', 'member_limit',
      'used', v_prof.daily_limit, 'limit', v_prof.daily_limit);
  end if;

  -- 팀 합산 한도 (개인 잔여가 있어도 팀이 소진되면 차단)
  if v_prof.team_id is not null then
    select * into v_team from public.teams where id = v_prof.team_id;
    if found and not v_team.unlimited then
      v_team_limit := v_team.daily_limit;
      select coalesce(sum(u.count), 0) into v_team_used
        from public.advisory_usage u
        join public.profiles p on p.user_id = u.user_id
       where p.team_id = v_prof.team_id and u.day = v_day and u.kind = 'advisory';
      if v_team_used > v_team.daily_limit then
        update public.advisory_usage set count = count - 1
          where user_id = p_user and day = v_day and kind = p_kind;
        return jsonb_build_object('ok', false, 'reason', 'team_limit',
          'team_used', v_team.daily_limit, 'team_limit', v_team.daily_limit,
          'team_name', v_team.name);
      end if;
    end if;
  end if;

  return jsonb_build_object('ok', true, 'used', v_used, 'limit', v_prof.daily_limit,
    'team_used', v_team_used, 'team_limit', v_team_limit, 'unlimited', v_prof.unlimited);
end $function$;

-- 4) 일반 호출 폭주 경보 — 오늘(KST) general 합계가 100을 넘으면 운영자 텔레그램 1회/일
create or replace function public.check_ai_usage_burst()
 returns void
 language plpgsql
 security definer
 set search_path to 'public'
as $function$
declare
  v_day date := (now() at time zone 'Asia/Seoul')::date;
  v_general int; v_advisory int; v_prev text; tok text; msg text;
begin
  select coalesce(sum(count) filter (where kind='general'),0),
         coalesce(sum(count) filter (where kind='advisory'),0)
    into v_general, v_advisory
    from public.advisory_usage where day = v_day;
  if v_general <= 100 then return; end if;
  select note into v_prev from public.system_health where key = 'ai_burst_alert';
  if v_prev = v_day::text then return; end if;           -- 하루 1회
  select decrypted_secret into tok from vault.decrypted_secrets where name = 'telegram_bot_token';
  if tok is null then return; end if;
  msg := '⚠️ [AI 호출 폭주] 오늘 대시보드 일반(Haiku) 호출 ' || v_general || '회 (평소 5~30), 자문 ' || v_advisory ||
         '회. 화면 자동 호출 버그나 대량 등록이 의심됩니다 — 운영 상태 탭 확인. 대량 작업은 세션에서(비용 0).';
  perform net.http_post(
    url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
    body    := jsonb_build_object('chat_id', '<OPERATOR_CHAT_ID>', 'text', msg),
    headers := '{"Content-Type":"application/json"}'::jsonb);
  insert into public.system_health (key, updated_at, note) values ('ai_burst_alert', now(), v_day::text)
    on conflict (key) do update set updated_at = now(), note = v_day::text;
end $function$;

-- 5) 운영 상태 탭용 집계 RPC (관리자만)
create or replace function public.ops_ai_usage_today()
 returns jsonb
 language plpgsql
 stable security definer
 set search_path to 'public'
as $function$
declare
  v_day date := (now() at time zone 'Asia/Seoul')::date;
  v_from timestamptz := (v_day::timestamp at time zone 'Asia/Seoul');
  r jsonb;
begin
  if not public.is_admin() then return jsonb_build_object('ok', false, 'reason', 'not_admin'); end if;
  select jsonb_build_object('ok', true,
    'advisory', coalesce((select sum(count) from public.advisory_usage where day = v_day and kind='advisory'),0),
    'general',  coalesce((select sum(count) from public.advisory_usage where day = v_day and kind='general'),0),
    'general_yday', coalesce((select sum(count) from public.advisory_usage where day = v_day - 1 and kind='general'),0),
    'tokens', coalesce((select jsonb_agg(t) from (
        select host, count(*) calls, sum(input_tokens) input_tokens, sum(cache_read) cache_read,
               sum(cache_write) cache_write, sum(output_tokens) output_tokens
          from public.api_usage where ts >= v_from group by host order by host) t), '[]'::jsonb)
  ) into r;
  return r;
end $function$;
grant execute on function public.ops_ai_usage_today() to authenticated;
revoke execute on function public.check_ai_usage_burst() from public, anon, authenticated;

-- 6) pg_cron: 매시 :15 폭주 점검, 매일 api_usage 120일 보관
select cron.schedule('ai-usage-burst-check', '15 * * * *', $$select public.check_ai_usage_burst();$$);
select cron.schedule('api-usage-cleanup', '30 15 * * *', $$delete from public.api_usage where ts < now() - interval '120 days';$$);;
