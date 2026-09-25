-- 20260803112926 add_subscriber_end_hour

-- 수신 종료 시각 (2026-08-03) — 종전에는 '23시 이후 무발송'이 코드에 하드코딩돼 있었다.
-- 구독자가 직접 고르게 바꾼다(18~22시). 기본 22시 = 종전 23시와 가장 가까운 선택지라
-- 기존 구독자의 체감 동작이 거의 바뀌지 않는다.
alter table public.telegram_subscribers
  add column if not exists end_hour int not null default 22;
comment on column public.telegram_subscribers.end_hour is
  '수신 종료 시각(18~22, KST). briefing_hour(6~10) ~ end_hour 사이에만 발송. 이후 다음 날 시작 시각까지 무발송.';;
