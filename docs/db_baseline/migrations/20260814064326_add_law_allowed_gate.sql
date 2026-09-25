-- 20260814064326 add_law_allowed_gate

-- /law 을 신규 가입자만 승인제로 (운영자 지시 2026-08-14).
-- 기존 가입자는 그대로 쓰게 두고(grandfather), 앞으로 가입하는 사람만 최초 1회 승인을 받는다.
alter table telegram_subscribers
  add column if not exists law_allowed boolean not null default false;

-- 이미 가입한 사람 전원 허용 처리 — 지금까지 승인 없이 쓰던 기능을 소급해 막지 않는다.
update telegram_subscribers set law_allowed = true where law_allowed = false;

comment on column telegram_subscribers.law_allowed is
  '/law 자연어 검색 허용 여부. 신규 가입자는 false(운영자 승인 필요), 2026-08-14 이전 가입자는 소급 허용. 조문번호 직답(/law OO법 N조)은 이 게이트와 무관하게 항상 허용.';;
