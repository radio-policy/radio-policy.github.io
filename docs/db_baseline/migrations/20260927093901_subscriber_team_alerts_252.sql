-- 20260927093901 subscriber_team_alerts_252

-- #252 (2026-09-27) 긴급도 2단계 세션 B — 팀별 긴급 알림(E5·E6·E9) · Fable 재검토 대상
-- 1) 구독자: 관리자가 지정하는 팀 또는 실(실장), 받을 뉴스(중요만/중요+보통), 보통 묶음 발송 기준 시각
alter table public.telegram_subscribers
  add column if not exists team_id smallint references public.teams(id) on delete set null,
  add column if not exists division text,
  add column if not exists news_level text not null default 'urgent',
  add column if not exists last_normal_sent_at timestamptz;
alter table public.telegram_subscribers
  add constraint telegram_subscribers_news_level_check check (news_level in ('urgent', 'normal')),
  add constraint telegram_subscribers_team_or_division_check check (team_id is null or division is null);

-- 2) 큐: 새 주제 news = 받는 단위(audience)별 기사 행. 공통 중요(topic urgent, audience null)는 기존 행 그대로.
--    audience: c(공통 — 보통 채널만) | t:<팀 id> | d:<실 이름>, level: 긴급 | 보통
alter table public.subscriber_queue
  add column if not exists audience text,
  add column if not exists level text;
alter table public.subscriber_queue drop constraint if exists subscriber_queue_topic_check;
alter table public.subscriber_queue
  add constraint subscriber_queue_topic_check check (topic = any (array['urgent', 'assembly', 'kmcc', 'news'])),
  add constraint subscriber_queue_news_shape_check check (
    (topic = 'news' and audience ~ '^(c|t:[0-9]+|d:.+)$' and level in ('긴급', '보통') and news_url is not null)
    or (topic <> 'news' and audience is null and level is null));

-- 3) 받는 단위별 알림 기록 — 공통 경로의 alert_suppress_log(사내 다리가 읽음)와 섞지 않는다.
--    (받는 단위, 채널, 기사)마다 한 줄 = 같은 기사를 같은 채널로 두 번 처리하지 않는 표식 + 재알림 억제 사슬(리마인드)의 재료
create table if not exists public.subscriber_alert_log (
  id bigint generated always as identity primary key,
  audience text not null check (audience ~ '^(c|t:[0-9]+|d:.+)$'),
  channel text not null check (channel in ('긴급', '보통')),
  news_id uuid not null references public.news_feed(id) on delete cascade,
  article_title text not null default '',
  article_url text,
  outcome text not null check (outcome in ('sent', 'remind', 'suppressed', 'merged')),
  matched_title text,
  shared_keywords text,
  created_at timestamptz not null default now(),
  unique (audience, channel, news_id)
);
create index if not exists subscriber_alert_log_aud_created_idx
  on public.subscriber_alert_log (audience, channel, created_at);
alter table public.subscriber_alert_log enable row level security;   -- 정책 0개 = service_role 전용
revoke all on table public.subscriber_alert_log from anon, authenticated;
grant select, insert, update, delete on table public.subscriber_alert_log to service_role;
revoke all on sequence public.subscriber_alert_log_id_seq from anon, authenticated;
grant usage, select on sequence public.subscriber_alert_log_id_seq to service_role;

-- 4) 관리자 전용 — 구독자 표는 정책 0개(service_role 전용) 설계를 유지하고 이 두 함수로만 읽고 쓴다
create or replace function public.admin_list_subscribers()
returns table (chat_id bigint, first_name text, username text, active boolean, topic_urgent boolean,
               news_level text, team_id smallint, division text, created_at timestamptz)
language plpgsql stable security definer set search_path to 'public'
as $$
begin
  if not public.is_admin() then raise exception 'AUTH_FAILED'; end if;
  return query
    select s.chat_id, s.first_name, s.username, s.active, s.topic_urgent, s.news_level, s.team_id, s.division, s.created_at
      from public.telegram_subscribers s
     order by s.created_at, s.chat_id;
end $$;

-- 팀 또는 실(둘 중 하나, 둘 다 null = 공통)을 바꾼다. 바뀐 경우에만 발송 기준 시각을 지금으로 — 옛 단위의 대기분과 새 단위의
-- 행이 겹쳐 같은 기사가 두 번 가지 않게. 반환 1 = 바뀜, 0 = 이미 그 값(변경 없음). 대상 없음·형식 오류는 예외.
create or replace function public.admin_set_subscriber_team(p_chat_id bigint, p_team_id smallint, p_division text)
returns integer
language plpgsql security definer set search_path to 'public'
as $$
declare n integer;
begin
  if not public.is_admin() then raise exception 'AUTH_FAILED'; end if;
  if p_team_id is not null and p_division is not null then raise exception 'TEAM_OR_DIVISION'; end if;
  if p_division is not null and not exists (select 1 from public.teams t where t.division = p_division) then
    raise exception 'UNKNOWN_DIVISION';
  end if;
  if not exists (select 1 from public.telegram_subscribers s where s.chat_id = p_chat_id) then
    raise exception 'NOT_FOUND';
  end if;
  update public.telegram_subscribers s
     set team_id = p_team_id, division = p_division,
         last_urgent_sent_at = now(), last_normal_sent_at = now(), updated_at = now()
   where s.chat_id = p_chat_id
     and (s.team_id is distinct from p_team_id or s.division is distinct from p_division);
  get diagnostics n = row_count;
  return n;
end $$;

revoke execute on function public.admin_list_subscribers() from public, anon;
revoke execute on function public.admin_set_subscriber_team(bigint, smallint, text) from public, anon;
grant execute on function public.admin_list_subscribers() to authenticated, service_role;
grant execute on function public.admin_set_subscriber_team(bigint, smallint, text) to authenticated, service_role;
;
