-- 20260814071627 backfill_telegram_usage_from_counters

-- 이력 테이블 신설(2026-08-14) 이전 사용분 소급 적재.
-- 원본은 telegram_subscribers 의 당일 카운터라 **마지막으로 쓴 날의 횟수만** 남아 있다 —
-- 그 이전 사용분은 매일 초기화돼 복원할 수 없다. 그래서 소급분은 result_note 로 표시해 둔다.
insert into telegram_usage (chat_id, command, query, ok, result_note, created_at)
select s.chat_id, 'ask', null, true, '소급(당일 카운터)',
       (s.ai_count_date::timestamptz + interval '9 hours')
from telegram_subscribers s, generate_series(1, s.ai_count) g
where s.ai_count_date is not null and s.ai_count > 0;

insert into telegram_usage (chat_id, command, query, ok, result_note, created_at)
select s.chat_id, 'law', null, true, '소급(당일 카운터)',
       (s.law_count_date::timestamptz + interval '9 hours')
from telegram_subscribers s, generate_series(1, s.law_count) g
where s.law_count_date is not null and s.law_count > 0;;
