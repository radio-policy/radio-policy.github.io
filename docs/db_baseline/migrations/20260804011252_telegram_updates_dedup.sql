-- 20260804011252 telegram_updates_dedup

-- 텔레그램 웹훅 재전송 차단 (#83)
-- 텔레그램은 웹훅이 60초 안에 200을 못 돌려주면 같은 update_id로 재전송한다.
-- /law·/ask는 답변 생성에 1~2분이 걸려 재전송이 겹치면 같은 질문에 답이 여러 번 나간다.
-- update_id는 업데이트마다 고유하므로, 최초 1건만 통과시키면 재전송은 막히고
-- 새 질문(다른 update_id)은 그대로 지나간다.
create table if not exists public.telegram_updates (
  update_id   bigint primary key,
  chat_id     bigint,
  received_at timestamptz not null default now()
);

create index if not exists idx_telegram_updates_received
  on public.telegram_updates (received_at);

alter table public.telegram_updates enable row level security;
-- 정책 0개 = service_role 전용 (anon 접근 불가)

comment on table public.telegram_updates is
  '텔레그램 웹훅 update_id 중복 차단(#83). 재전송된 같은 update_id는 무시하고, 새 질문은 통과. 2일 지난 행은 웹훅이 저빈도로 청소.';;
