-- 20260930145502 pc_standby_labels_265b2

-- #265-보론2 (2026-10-01): 회사 PC가 꺼진 동안 lampmanH-pc가 가드를 달고 대신 돈다(standby_run.py).
-- 판정(근무시간 기준·임계)은 그대로 — 이름표와 경보 끝말만 '두 PC 모두'로 고친다.
update public.watchdog_targets set label = '정부고시·입법예고(회사 PC 16:30 · 대체 lampmanH-pc 17:15)'
 where key = 'last_gov_notice_run';
update public.watchdog_targets set label = '본문 재수집(회사 PC 10분마다 · 대체 lampmanH-pc)'
 where key = 'last_refetch_run';
do $$
declare d text;
begin
  select pg_get_functiondef('public.watchdog_scan(boolean)'::regprocedure) into d;
  if position(' — 회사 PC 확인' in d) = 0 then
    raise exception 'watchdog_scan: marker not found';
  end if;
  execute replace(d, ' — 회사 PC 확인', ' — 회사 PC·lampmanH-pc 확인');
end $$;;
