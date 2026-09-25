-- 20260803110529 add_law_query_counter

-- /law 자연어 모드 일일 상한 카운터 (2026-08-03)
-- /law가 조문 즉답(비용 0)에서 Haiku 법령검색 답변(건당 ~$0.01)으로 확장되면서,
-- 승인제까지는 두지 않되(팀 조회 기능) 폭주만 막는 넉넉한 상한을 둔다. ai_count와 동일 패턴.
alter table public.telegram_subscribers
  add column if not exists law_count int not null default 0,
  add column if not exists law_count_date date;;
