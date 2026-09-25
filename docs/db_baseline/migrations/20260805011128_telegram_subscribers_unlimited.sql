-- 20260805011128 telegram_subscribers_unlimited

-- 개인별 일일 한도 면제 (#86)
-- /ask 20회·/law 10회 상한은 과금 폭주 방지용 전원 공통값이다(AI_DAILY_LIMIT / LAW_DAILY_LIMIT).
-- 특정 인원에게만 상한을 풀 수단이 없어 컬럼으로 둔다 — 구독자 속성이므로 app_config가 아니라
-- 구독자 행에 두는 것이 맞다(getSub이 select('*')라 코드가 자동으로 읽는다).
-- ⚠️ true면 그 사람의 /ask·/law 호출이 무제한이 된다 = 비용 상한이 사라진다. 신중히 켤 것.
alter table public.telegram_subscribers
  add column if not exists unlimited boolean not null default false;

comment on column public.telegram_subscribers.unlimited is
  '일일 한도 면제(#86). true면 /ask·/law 상한을 건너뛴다. 비용 상한이 사라지므로 신뢰 인원에게만.';;
