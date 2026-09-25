-- 20260820115919 auth_teams_profiles_base

-- 대시보드 로그인 계정 + 팀별 권한·한도 (2026-08-20, #104)
-- 열람은 전면 공개 유지, AI 생성 기능만 로그인 뒤로. 조직: 1실 3팀.

create table public.teams (
  id           smallserial primary key,
  name         text not null unique,
  daily_limit  int  not null default 30,     -- 팀 합산 일일 자문 한도
  unlimited    boolean not null default false,
  created_at   timestamptz not null default now()
);
insert into public.teams (name) values ('경쟁제도팀'), ('기술정책팀'), ('AI정책팀');

create table public.profiles (
  user_id      uuid primary key references auth.users(id) on delete cascade,
  name         text not null default '',
  team_id      smallint references public.teams(id),
  role         text not null default 'member' check (role in ('admin','leader','member')),
  daily_limit  int  not null default 10,     -- 개인 일일 자문 한도
  unlimited    boolean not null default false,
  approved     boolean not null default false,  -- 관리자 승인 전에는 AI 기능 잠김
  active       boolean not null default true,
  created_at   timestamptz not null default now()
);
create index idx_profiles_team on public.profiles (team_id);

-- 자문 사용량. kind='advisory'는 한도 대상(스트리밍=자문·보고서초안),
-- 'general'은 뉴스요약 등 경량 호출로 남용 방지 백스톱만 적용.
create table public.advisory_usage (
  user_id uuid not null references auth.users(id) on delete cascade,
  day     date not null,
  kind    text not null check (kind in ('advisory','general')),
  count   int  not null default 0,
  primary key (user_id, day, kind)
);

alter table public.chat_logs add column if not exists user_id uuid references auth.users(id);
create index if not exists idx_chat_logs_user on public.chat_logs (user_id);

-- 가입 시 '승인 대기' 프로필 자동 생성 (approved=false)
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path to 'public' as $$
begin
  insert into public.profiles (user_id, name)
  values (new.id, coalesce(new.raw_user_meta_data->>'name', ''))
  on conflict (user_id) do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- 역할 헬퍼 — SECURITY DEFINER로 두어야 profiles 정책이 자기 자신을 재귀 조회하지 않는다
create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path to 'public' as $$
  select exists (select 1 from profiles
                 where user_id = auth.uid() and role = 'admin' and approved and active) $$;

create or replace function public.is_leader() returns boolean
language sql stable security definer set search_path to 'public' as $$
  select exists (select 1 from profiles
                 where user_id = auth.uid() and role = 'leader' and approved and active) $$;

create or replace function public.my_team() returns smallint
language sql stable security definer set search_path to 'public' as $$
  select team_id from profiles where user_id = auth.uid() $$;

grant execute on function public.is_admin(), public.is_leader(), public.my_team() to authenticated;;
