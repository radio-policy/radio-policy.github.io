-- 20260801081535 add_last_urgent_sent_at

-- 긴급 뉴스를 '즉시'가 아니라 구독자가 고른 시각에 모아 보내도록 변경.
-- 이 컬럼이 마지막 발송 시점 = 다음 발송의 수집 구간 시작점 역할을 한다.
alter table public.telegram_subscribers
  add column if not exists last_urgent_sent_at timestamptz;

comment on column public.telegram_subscribers.last_urgent_sent_at is
  '긴급 뉴스 다이제스트 마지막 발송 시각. 다음 발송 시 이 시점 이후 수집분만 보낸다(1일 1회, briefing_hour에 발송)';;
