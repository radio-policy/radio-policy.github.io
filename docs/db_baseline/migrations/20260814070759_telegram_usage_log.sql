-- 20260814070759 telegram_usage_log

-- 구독자별 사용 이력 (2026-08-14, 운영자 지시: 매일 구독자 목록·작업 통계를 텔레그램으로).
-- 기존에는 telegram_subscribers.ai_count/law_count 가 **당일 카운터**라 매일 초기화됐고,
-- assem 은 기록 자체가 없어 "누가 무엇을 했는지"를 되짚을 방법이 없었다.
create table if not exists telegram_usage (
  id          bigserial primary key,
  chat_id     bigint      not null,
  command     text        not null,   -- assem | law | law_article | ask | start | settings
  query       text,                   -- 입력 원문(200자 절단)
  ok          boolean     not null default true,
  result_note text,                   -- '48건', '승인대기' 등 결과 요약
  created_at  timestamptz not null default now()
);

create index if not exists telegram_usage_created_idx on telegram_usage (created_at desc);
create index if not exists telegram_usage_chat_idx    on telegram_usage (chat_id, created_at desc);

comment on table telegram_usage is
  '텔레그램 봇 명령 사용 이력. 일일 리포트(admin-daily-report)와 사용량 추적용. 180일 보관 후 리포트 잡이 정리.';;
