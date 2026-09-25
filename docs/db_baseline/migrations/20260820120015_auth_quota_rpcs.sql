-- 20260820120015 auth_quota_rpcs

-- 한도 차감 — claude-proxy(service_role)만 실행. 텔레그램의 read-modify-write 경쟁 문제를
-- 피하려고 insert…on conflict…returning으로 원자적 증가를 쓰고, 팀 합산은 advisory lock으로 직렬화.
create or replace function public.charge_ai_usage(p_user uuid, p_kind text)
returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare
  v_day   date := (now() at time zone 'Asia/Seoul')::date;   -- KST 일자 = 리셋 기준
  v_prof  public.profiles%rowtype;
  v_team  public.teams%rowtype;
  v_used  int;
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
    -- 경량 호출은 한도 대상이 아니고 남용 방지 백스톱만
    if v_used > 300 and not v_prof.unlimited then
      update public.advisory_usage set count = count - 1
        where user_id = p_user and day = v_day and kind = p_kind;
      return jsonb_build_object('ok', false, 'reason', 'general_backstop');
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
end $$;

-- 환불 — 업스트림이 거부해 한 바이트도 못 받은 경우에만. 일자 재확인으로 다음날 예산 침범 방지.
create or replace function public.refund_ai_usage(p_user uuid, p_kind text)
returns void
language plpgsql security definer set search_path to 'public' as $$
declare v_day date := (now() at time zone 'Asia/Seoul')::date;
begin
  update public.advisory_usage set count = count - 1
   where user_id = p_user and day = v_day and kind = p_kind and count > 0;
end $$;

revoke execute on function public.charge_ai_usage(uuid, text) from public, anon, authenticated;
revoke execute on function public.refund_ai_usage(uuid, text) from public, anon, authenticated;
grant  execute on function public.charge_ai_usage(uuid, text) to service_role;
grant  execute on function public.refund_ai_usage(uuid, text) to service_role;

-- 화면 표시용 잔여 조회 (본인 것만, 읽기 전용)
create or replace function public.get_my_quota()
returns jsonb
language plpgsql stable security definer set search_path to 'public' as $$
declare
  v_day date := (now() at time zone 'Asia/Seoul')::date;
  v_prof public.profiles%rowtype;
  v_team public.teams%rowtype;
  v_used int := 0; v_team_used int := 0;
begin
  select * into v_prof from public.profiles where user_id = auth.uid();
  if not found then return jsonb_build_object('ok', false, 'reason', 'no_profile'); end if;

  select coalesce(count, 0) into v_used from public.advisory_usage
   where user_id = auth.uid() and day = v_day and kind = 'advisory';

  if v_prof.team_id is not null then
    select * into v_team from public.teams where id = v_prof.team_id;
    select coalesce(sum(u.count), 0) into v_team_used
      from public.advisory_usage u join public.profiles p on p.user_id = u.user_id
     where p.team_id = v_prof.team_id and u.day = v_day and u.kind = 'advisory';
  end if;

  return jsonb_build_object(
    'ok', true, 'approved', v_prof.approved, 'active', v_prof.active, 'role', v_prof.role,
    'unlimited', v_prof.unlimited,
    'used', coalesce(v_used, 0), 'limit', v_prof.daily_limit,
    'team_name', v_team.name, 'team_used', coalesce(v_team_used, 0),
    'team_limit', v_team.daily_limit, 'team_unlimited', coalesce(v_team.unlimited, false));
end $$;
grant execute on function public.get_my_quota() to authenticated;

-- 자문 이력 삭제 (역할 기반 v2). RLS에 DELETE 정책이 없어 직접 delete는 조용히 0건이 되므로
-- RPC + 삭제 행수 확인을 유지한다(#48).
create or replace function public.admin_delete_chat_log_v2(p_id uuid)
returns integer
language plpgsql security definer set search_path to 'public' as $$
declare n integer;
begin
  if not public.is_admin() then raise exception 'AUTH_FAILED'; end if;
  delete from public.chat_logs where id = p_id;
  get diagnostics n = row_count;
  return n;
end $$;
grant execute on function public.admin_delete_chat_log_v2(uuid) to authenticated;;
