-- 20260930130337 watchdog_pc_business_hours_comment_265

-- 바로 앞 마이그레이션 watchdog_pc_business_hours_264의 항목 번호 정정: 같은 시각 다른 세션이 #264(긴급도 유사 사례 블록)를 먼저 썼다 — 이 변경은 #265다.
comment on column public.watchdog_targets.clock is 'wall = 실제 경과 시간, biz = 근무시간(평일 09:30~18:00 KST)만 센 경과 시간 — 회사 PC 예약작업용(#265)';
comment on function public.biz_hours_between(timestamptz, timestamptz) is '두 시각 사이의 근무시간(평일 09:30~18:00 KST) — 공휴일은 근무일로 센다(#265)';
comment on function public.pc_heartbeat_ages() is '근무시간 기준(watchdog_targets.clock=biz) 키의 나이 — watchdog_scan·health_watchdog.py·대시보드 운영 상태가 함께 쓴다(#265)';;
