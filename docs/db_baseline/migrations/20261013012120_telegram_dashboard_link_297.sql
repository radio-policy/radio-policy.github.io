-- 20261013012120 telegram_dashboard_link_297

-- #297 (2026-10-13 운영자 결정) 텔레그램 구독자 ↔ 대시보드 계정 연결 — 관리자만 지정.
-- 연결된 구독자의 봇 /ask는 대시보드 자문 한도(charge_ai_usage: 개인 daily_limit + 팀 합산)에서 함께 세고,
-- /ask·/law 승인·무제한은 profiles(approved·active·unlimited)를 따른다(telegram-webhook linkedProfile).
-- FK는 두지 않는다(#266-보론: profiles 쪽 관계를 늘리지 않는다 — teams.grader_user_id와 같은 방식). 계정이 지워져 연결만
-- 남으면 봇이 막는다(fail-closed), 관리자 화면에 「(없는 계정 — 봇 이용 막힘)」으로 보인다.
alter table public.telegram_subscribers add column if not exists dashboard_user_id uuid;
comment on column public.telegram_subscribers.dashboard_user_id is
  '연결된 대시보드 계정(profiles.user_id, #297) — 관리자만 admin_set_subscriber_account로 지정. FK 없음. 연결되면 /ask는 대시보드 자문 한도와 합산, /ask·/law 승인·무제한은 profiles를 따른다';
create unique index if not exists telegram_subscribers_dashboard_user_uidx
  on public.telegram_subscribers (dashboard_user_id) where dashboard_user_id is not null;

-- 목록 RPC에 연결 칸 추가 — 반환 형태가 바뀌어 drop & create(권한이 같이 사라지므로 아래에서 다시 준다)
drop function if exists public.admin_list_subscribers();
create function public.admin_list_subscribers()
 returns table(chat_id bigint, first_name text, username text, active boolean, topic_urgent boolean, news_level text,
               team_id smallint, division text, created_at timestamp with time zone, dashboard_user_id uuid)
 language plpgsql stable security definer set search_path to 'public'
as $function$
begin
  if not public.is_admin() then raise exception 'AUTH_FAILED'; end if;
  return query
    select s.chat_id, s.first_name, s.username, s.active, s.topic_urgent, s.news_level, s.team_id, s.division, s.created_at,
           s.dashboard_user_id
      from public.telegram_subscribers s
     order by s.created_at, s.chat_id;
end $function$;
revoke all on function public.admin_list_subscribers() from public, anon;
grant execute on function public.admin_list_subscribers() to authenticated, service_role;

create or replace function public.admin_set_subscriber_account(p_chat_id bigint, p_user_id uuid)
 returns integer
 language plpgsql security definer set search_path to 'public'
as $function$
declare n integer;
begin
  if not public.is_admin() then raise exception 'AUTH_FAILED'; end if;
  if not exists (select 1 from public.telegram_subscribers s where s.chat_id = p_chat_id) then
    raise exception 'NOT_FOUND';
  end if;
  if p_user_id is not null then
    if not exists (select 1 from public.profiles p where p.user_id = p_user_id) then raise exception 'UNKNOWN_ACCOUNT'; end if;
    if exists (select 1 from public.telegram_subscribers s where s.dashboard_user_id = p_user_id and s.chat_id <> p_chat_id) then
      raise exception 'ALREADY_LINKED';
    end if;
  end if;
  update public.telegram_subscribers s
     set dashboard_user_id = p_user_id, updated_at = now()
   where s.chat_id = p_chat_id
     and s.dashboard_user_id is distinct from p_user_id;
  get diagnostics n = row_count;
  return n;
end $function$;
revoke all on function public.admin_set_subscriber_account(bigint, uuid) from public, anon;
grant execute on function public.admin_set_subscriber_account(bigint, uuid) to authenticated, service_role;;
