-- 20260913164254 lawmap_request_allow_anon

-- 비로그인 '관계도 추가 요청' 허용 (운영자 지시 2026-09-14).
-- 대시보드 열람은 원래 공개이므로 요청도 로그인 없이 받는다. 다만 인증 없는 쓰기 경로가
-- 열리는 것이므로 ① 넣을 수 있는 모양을 못 박고 ② 건수를 제한한다.

-- ① 모양 제한: origin='request' / status='pending' / 관계·판정 비어 있음 / 본인표기 없음 / 길이 제한.
--    이 조건을 하나라도 어기면 삽입 자체가 거부된다(다른 컬럼을 흘려 넣지 못하게).
drop policy if exists lawmap_proposals_ins_anon on public.lawmap_proposals;
create policy lawmap_proposals_ins_anon on public.lawmap_proposals
  for insert to anon
  with check (
    origin = 'request'
    and status = 'pending'
    and created_by is null
    and coalesce(relations, '[]'::jsonb) = '[]'::jsonb
    and coalesce(gate, '[]'::jsonb) = '[]'::jsonb
    and decided_at is null and decided_by is null
    and decision_note is null and result is null
    and description is null
    and char_length(topic) between 2 and 30
    and coalesce(char_length(question), 0) <= 300
    and coalesce(char_length(requester), 0) <= 40
  );

-- ② 건수 제한: 비로그인 요청만 대상. 시간당 10건, 미처리 대기 20건.
--    초과하면 예외로 막는다 — 조용히 버리면 요청자는 접수된 줄 안다.
create or replace function public.limit_anon_lawmap_request()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  n_hour int;
  n_open int;
begin
  if new.origin is distinct from 'request' or new.created_by is not null then
    return new;
  end if;
  select count(*) into n_hour from lawmap_proposals
   where origin = 'request' and created_by is null and created_at > now() - interval '1 hour';
  if n_hour >= 10 then
    raise exception '관계도 추가 요청이 한 시간에 너무 많이 들어왔습니다. 잠시 후 다시 시도해 주세요.';
  end if;
  select count(*) into n_open from lawmap_proposals
   where origin = 'request' and created_by is null and status = 'pending';
  if n_open >= 20 then
    raise exception '미처리 요청이 많습니다. 운영자 검토 후 다시 시도해 주세요.';
  end if;
  return new;
end $$;

drop trigger if exists trg_limit_anon_lawmap_request on public.lawmap_proposals;
create trigger trg_limit_anon_lawmap_request
  before insert on public.lawmap_proposals
  for each row execute function public.limit_anon_lawmap_request();;
