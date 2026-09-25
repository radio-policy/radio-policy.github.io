-- 20260801081610 subscriber_queue

-- 구독자 알림 큐
-- 긴급·법안 알림을 '즉시 발송'에서 '구독자가 고른 시각에 모아 발송'으로 바꾸면서 도입.
-- 크롤러(Python)가 이미 억제·클러스터링·상태변경 판정을 마친 결과만 여기에 적재하고,
-- 매시 도는 send-subscriber-briefing이 각 구독자의 수신 시각에 꺼내 보낸다.
-- (판정 로직을 TS로 재구현하지 않기 위한 구조 — 배경역사 #44 억제 로직 재사용)
create table public.subscriber_queue (
  id         bigserial primary key,
  topic      text not null check (topic in ('urgent', 'assembly')),
  html       text not null,
  created_at timestamptz not null default now()
);
create index subscriber_queue_created_idx on public.subscriber_queue (created_at);
alter table public.subscriber_queue enable row level security;   -- 정책 0개 = service_role 전용

alter table public.telegram_subscribers
  add column if not exists last_assembly_sent_at timestamptz;

comment on column public.telegram_subscribers.last_assembly_sent_at is
  '법안 동향 다이제스트 마지막 발송 시각. 다음 발송 시 이 시점 이후 큐 항목만 보낸다';;
