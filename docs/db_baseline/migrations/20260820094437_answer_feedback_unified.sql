-- 20260820094437 answer_feedback_unified

-- 답변 만족도 통합 수집 (3경로: telegram_ask / telegram_law / dashboard) — 2026-08-20
-- 1) chat_logs → 전 채널 정본 답변 로그
alter table public.chat_logs
  add column if not exists channel text,
  add column if not exists chat_id bigint,
  add column if not exists chunk_ids jsonb;

update public.chat_logs
  set channel = case when category = '텔레그램' then 'telegram_ask' else 'dashboard' end
  where channel is null;

-- 2) 통합 피드백 테이블 (1답변 1행, 재투표는 갱신)
create table public.answer_feedback (
  id bigint generated always as identity primary key,
  log_id uuid unique references public.chat_logs(id) on delete set null,
  channel text not null check (channel in ('telegram_ask','telegram_law','dashboard')),
  rating smallint not null check (rating in (1,-1)),
  reason text,
  chat_id bigint,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index idx_answer_feedback_channel on public.answer_feedback (channel, rating);

-- 운영자 전용: RLS ON + anon 정책 없음 (직접 select/insert/update 전부 차단)
alter table public.answer_feedback enable row level security;

-- 3) 투표 제출 RPC (anon 실행 가능, 조회는 불가) — channel은 서버가 chat_logs에서 결정
create or replace function public.submit_answer_feedback(p_log_id uuid, p_rating smallint, p_reason text default null)
returns void language plpgsql security definer set search_path to 'public','extensions' as $$
declare v_channel text;
begin
  if p_rating not in (1,-1) then raise exception 'BAD_RATING'; end if;
  select channel into v_channel from chat_logs where id = p_log_id;
  if v_channel is null then raise exception 'LOG_NOT_FOUND'; end if;
  insert into answer_feedback (log_id, channel, rating, reason)
  values (p_log_id, v_channel, p_rating, p_reason)
  on conflict (log_id) do update
    set rating = excluded.rating,
        reason = coalesce(excluded.reason, answer_feedback.reason),
        updated_at = now();
end $$;

-- 4) 운영자 조회 RPC (기존 admin_* RPC와 동일한 sha256 해시 비교)
create or replace function public.admin_list_answer_feedback(p_pwd text)
returns table (fb_id bigint, channel text, rating smallint, reason text, fb_chat_id bigint,
               fb_created_at timestamptz, fb_updated_at timestamptz,
               log_id uuid, question text, answer text, category text, sources text, chunk_ids jsonb)
language plpgsql security definer set search_path to 'public','extensions' as $$
begin
  if encode(digest(p_pwd,'sha256'),'hex') is distinct from '<REDACTED:hex_digest>' then
    raise exception 'AUTH_FAILED';
  end if;
  return query select f.id, f.channel, f.rating, f.reason, f.chat_id, f.created_at, f.updated_at,
                      c.id, c.question, c.answer, c.category, c.sources, c.chunk_ids
               from answer_feedback f left join chat_logs c on c.id = f.log_id
               order by f.created_at desc limit 500;
end $$;;
