-- 20260908040208 drop_109_dup_from_subscriber_queue

-- 2026-09-08: 자살예방상담전화 109 긴급통신 지정 사건이 09:25·10:25 발송에 연달아 들어가
-- 구독자에게 중복 노출됐다. 아직 배달되지 않은 같은 사건 행을 제거한다(운영자 지시).
-- 판정 기준: 미배달(모든 구독자의 워터마크 이후) + 109/자살예방 문자열.
delete from subscriber_queue
where topic = 'urgent'
  and created_at > (select min(last_urgent_sent_at) from telegram_subscribers where topic_urgent)
  and (html like '%109%' or html like '%자살예방%');;
