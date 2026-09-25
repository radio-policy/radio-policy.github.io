-- 20260801074351 add_quiet_night_to_subscribers

-- 야간 무음: 23~07시(KST) 긴급·법안 푸시 보류. 기본 ON.
-- 보류된 건도 다음날 모닝 브리핑에 포함되므로 정보 손실은 없다(발송만 생략).
alter table public.telegram_subscribers
  add column if not exists quiet_night boolean not null default true;

comment on column public.telegram_subscribers.quiet_night is
  '야간 무음(23:00~07:00 KST) — 긴급 뉴스·법안 동향 푸시 생략. 모닝 브리핑은 무관';;
