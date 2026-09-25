-- 20260731202248 create_telegram_subscribers

-- 텔레그램 구독 봇: 구독자 테이블 (배경역사 #51 예정)
-- RLS on + 정책 0개 = service_role 전용 (chat_id는 개인정보, 프론트 노출 금지 — 의도적)
create table public.telegram_subscribers (
  chat_id        bigint primary key,
  username       text,
  first_name     text,
  active         boolean  not null default true,
  topic_briefing boolean  not null default true,
  topic_urgent   boolean  not null default true,
  topic_assembly boolean  not null default true,
  days           text     not null default 'daily' check (days in ('daily','weekday')),
  briefing_hour  smallint not null default 7 check (briefing_hour between 6 and 12),
  last_briefing_sent_date date,
  ai_allowed     boolean  not null default false,
  ai_count_date  date,
  ai_count       smallint not null default 0,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
alter table public.telegram_subscribers enable row level security;;
