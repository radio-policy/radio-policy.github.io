-- 20260731170648 daily_briefings_backup

-- 브리핑 재생성 전 원본 보존 (배경역사 #46). 되돌리기 근거.
create table if not exists daily_briefings_backup (
  id bigint generated always as identity primary key,
  briefing_date date not null,
  content text not null,
  news_count integer,
  terms_count integer,
  original_created_at timestamptz,
  backed_up_at timestamptz not null default now(),
  reason text
);
alter table daily_briefings_backup enable row level security;
-- 정책 없음 = anon 차단, service role만 접근;
