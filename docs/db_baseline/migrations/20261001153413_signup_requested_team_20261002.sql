-- 20261001153413 signup_requested_team_20261002

-- 가입 창 팀 고르기(2026-10-02, 운영자 결정): 신청자가 고른 팀은 권한이 없는 칸 requested_team_id에만 둔다.
-- 팀 권한(team_id)은 종전처럼 관리자가 승인 때 정한다(profiles UPDATE는 admin만 — 권한 경계 그대로).
alter table public.profiles
  add column if not exists requested_team_id smallint references public.teams(id) on delete set null;
comment on column public.profiles.requested_team_id is
  '가입 때 신청자가 고른 팀(참고용 — 어떤 권한·RLS에도 쓰지 않는다). 권한은 관리자가 승인 때 정하는 team_id만.';

create or replace function public.handle_new_user()
 returns trigger
 language plpgsql
 security definer
 set search_path to 'public'
as $function$
declare
  v_name text := coalesce(new.raw_user_meta_data->>'name', '');
  v_req  text := new.raw_user_meta_data->>'team_req';
  v_team smallint;
  v_team_name text;
  tok text;
begin
  -- 신청 팀은 사용자가 보낸 값이라 숫자·실재 팀만 받는다. 이상한 값은 버리고 가입은 막지 않는다.
  begin
    if v_req ~ '^[0-9]{1,4}$' then
      select t.id, t.name into v_team, v_team_name from public.teams t where t.id = v_req::int;
    end if;
  exception when others then
    v_team := null; v_team_name := null;
  end;

  insert into public.profiles (user_id, name, requested_team_id)
  values (new.id, v_name, v_team)
  on conflict (user_id) do nothing;

  begin
    select decrypted_secret into tok from vault.decrypted_secrets where name = 'telegram_bot_token';
    if tok is not null then
      perform net.http_post(
        url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
        body    := jsonb_build_object(
          'chat_id', '<OPERATOR_CHAT_ID>',
          'text', '🆕 대시보드 가입 신청' || E'\n'
               || '이름: ' || coalesce(nullif(v_name, ''), '(미입력)') || E'\n'
               || '이메일: ' || coalesce(new.email, '?') || E'\n'
               || '신청 팀: ' || coalesce(v_team_name, '(고르지 않음)') || E'\n'
               || '→ 대시보드 설정 > 계정 관리에서 팀 확인·역할 지정 후 승인'
        ),
        headers := '{"Content-Type":"application/json"}'::jsonb,
        timeout_milliseconds := 10000
      );
    end if;
  exception when others then
    raise warning '[가입 알림 실패(가입은 정상)] %', sqlerrm;
  end;

  return new;
end $function$;;
