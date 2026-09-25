-- 20260910160516 add_kmcc_subscriber_topic

-- #154 방미통위 동향 토픽 (2026-09-11): 컬럼 기본 true = 신규 가입자 켜짐, 기존 구독자는 false 로 시작(운영자 결정)
alter table public.telegram_subscribers
  add column if not exists topic_kmcc boolean not null default true,
  add column if not exists last_kmcc_sent_at timestamptz;
update public.telegram_subscribers set topic_kmcc = false;
-- subscriber_queue.topic CHECK 에 kmcc 추가
alter table public.subscriber_queue drop constraint if exists subscriber_queue_topic_check;
alter table public.subscriber_queue add constraint subscriber_queue_topic_check
  check (topic = any (array['urgent'::text, 'assembly'::text, 'kmcc'::text]));;
