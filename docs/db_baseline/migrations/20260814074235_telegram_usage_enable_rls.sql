-- 20260814074235 telegram_usage_enable_rls

-- telegram_usage 는 구독자 chat_id 와 질의 원문을 담는데 RLS가 꺼진 채 생성됐다.
-- anon 키는 공개 GitHub Pages 대시보드에 박혀 있어 누구나 읽고/지울 수 있는 상태였다.
-- 다른 텔레그램 테이블(telegram_subscribers/telegram_updates/subscriber_queue)과 동일하게
-- RLS on + 정책 0개 = service_role 전용으로 맞춘다.
alter table public.telegram_usage enable row level security;
revoke all on public.telegram_usage from anon, authenticated;;
