-- 20260820102450 chat_logs_admin_only_read

-- 자문 이력을 운영자 전용으로 (2026-08-20, #103 후속)
-- 공개 대시보드에서 anon 키로 chat_logs를 그대로 읽을 수 있었다 — 화면만 가리면 우회되므로
-- 읽기를 비밀번호 RPC로만 열고 anon SELECT 정책은 제거한다(정책 제거는 대시보드 배포 후).

-- 목록 (조문 직조회는 기계적 원문 출력이라 자문 이력에서 제외 — 피드백 탭에서는 보인다)
create or replace function public.admin_list_chat_logs(p_pwd text, p_limit int default 100)
returns table (id uuid, question text, category text, created_at timestamptz)
language plpgsql security definer set search_path to 'public','extensions' as $$
begin
  if encode(digest(p_pwd,'sha256'),'hex') is distinct from '<REDACTED:hex_digest>' then
    raise exception 'AUTH_FAILED';
  end if;
  return query select c.id, c.question, c.category, c.created_at
               from chat_logs c
               where c.category is distinct from '텔레그램-조문조회'
               order by c.created_at desc
               limit least(greatest(p_limit, 1), 200);
end $$;

-- 상세 1건
create or replace function public.admin_get_chat_log(p_pwd text, p_id uuid)
returns table (question text, answer text, category text, sources text, created_at timestamptz)
language plpgsql security definer set search_path to 'public','extensions' as $$
begin
  if encode(digest(p_pwd,'sha256'),'hex') is distinct from '<REDACTED:hex_digest>' then
    raise exception 'AUTH_FAILED';
  end if;
  return query select c.question, c.answer, c.category, c.sources, c.created_at
               from chat_logs c where c.id = p_id;
end $$;

-- 이번달 자문 건수 — 숫자만 나가므로 비밀번호 없이 열어 둔다(홈 통계 카드·헬스체크용).
-- 내용은 일절 반환하지 않는다.
create or replace function public.chat_logs_month_count()
returns integer
language sql security definer set search_path to 'public','extensions' as $$
  select count(*)::int from chat_logs
  where created_at >= date_trunc('month', now() at time zone 'Asia/Seoul');
$$;;
