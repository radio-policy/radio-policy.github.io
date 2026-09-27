-- 20260927104121 subscriber_team_alerts_252_review

-- #252 리뷰 반영 (2026-09-27, Fable 재검토 대상)
-- 1) news_feed 60일 정리 때 FK cascade·기사별 기록 확인 조회가 표 전체를 훑지 않게
create index if not exists subscriber_alert_log_news_idx on public.subscriber_alert_log (news_id);

-- 2) 알림 기준을 바꿀 때 발송 기준 시각을 '지금'이 아니라 least(지금, 옛 기준 + 5분)으로 —
--    같은 실행의 공통 행과 팀 행은 몇 초~몇 분 차로 들어가므로 5분 여유면 경계 중복을 막고, 밤(수신 시간대 밖)에 바꿔도
--    밤새 쌓인 대기분(옛 기준 + 5분 이후)은 새 단위 행으로 다음 날 아침에 이어 간다. 옛 기준이 없으면 지금.
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
         last_urgent_sent_at = least(now(), coalesce(s.last_urgent_sent_at, now()) + interval '5 minutes'),
         last_normal_sent_at = least(now(), coalesce(s.last_normal_sent_at, now()) + interval '5 minutes'),
         updated_at = now()
   where s.chat_id = p_chat_id
     and (s.team_id is distinct from p_team_id or s.division is distinct from p_division);
  get diagnostics n = row_count;
  return n;
end $$;

revoke execute on function public.admin_set_subscriber_team(bigint, smallint, text) from public, anon;
grant execute on function public.admin_set_subscriber_team(bigint, smallint, text) to authenticated, service_role;
;
