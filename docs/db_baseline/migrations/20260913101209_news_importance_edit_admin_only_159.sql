-- 20260913101209 news_importance_edit_admin_only_159

-- #159 뉴스 중요도·잠금·삭제를 관리자 전용으로 (2026-09-13, 사내 공유 직전)
-- 배경: 중요도는 **모든 이용자가 함께 보는 단일 값**이고, 수정이 importance_feedback에 쌓여 이후 AI
--       판정까지 학습시킨다(당일 브리핑 🔴 표시도 동기화). 지금까지는 승인 계정이면 누구나 바꿀 수
--       있었는데(#133), 타 팀에 공유하면 그 팀 기준의 수정이 기술정책팀이 보는 값과 학습을 함께 흔든다.
--       팀별 중요도(team_urgency)가 나오기 전까지 관리자 전용으로 내린다.
-- 설계: news_feed UPDATE 정책 자체는 is_approved_user()로 **유지**한다 — 같은 통로로 요약(summary)·
--       영향분석(impact_analysis) 저장이 지나가기 때문(#134·#153 첫 열람 생성). 대신 트리거가
--       importance·urgency·locked **컬럼이 바뀔 때만** 관리자를 요구한다.
--       크롤러·스크립트(service_role)와 마이그레이션(postgres)은 그대로 통과시킨다 — 통과시키지 않으면
--       매시간 등급을 기록하는 crawler.py가 전부 실패한다.

create or replace function public.news_feed_edit_guard()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $$
begin
  -- 서버 쪽 경로(크롤러·PC 스크립트·마이그레이션)는 검사 대상이 아니다
  if current_user in ('service_role', 'postgres', 'supabase_admin', 'supabase_auth_admin') then
    return new;
  end if;

  if (new.importance is distinct from old.importance
      or new.urgency is distinct from old.urgency
      or new.locked  is distinct from old.locked)
     and not public.is_admin() then
    raise exception '뉴스 중요도·잠금 변경은 관리자만 가능합니다(팀별 중요도 기능 준비 중)'
      using errcode = '42501';
  end if;

  return new;
end $$;

drop trigger if exists news_feed_edit_guard_trg on public.news_feed;
create trigger news_feed_edit_guard_trg
  before update on public.news_feed
  for each row execute function public.news_feed_edit_guard();

-- 삭제·삭제이력·피드백 쓰기도 관리자 전용 (중요도 수정과 한 묶음)
drop policy if exists news_feed_del on public.news_feed;
create policy news_feed_del on public.news_feed for delete to authenticated using (public.is_admin());

drop policy if exists deleted_news_ins on public.deleted_news;
create policy deleted_news_ins on public.deleted_news for insert to authenticated with check (public.is_admin());

drop policy if exists imp_fb_ins on public.importance_feedback;
create policy imp_fb_ins on public.importance_feedback for insert to authenticated with check (public.is_admin());

drop policy if exists imp_fb_upd on public.importance_feedback;
create policy imp_fb_upd on public.importance_feedback for update to authenticated
  using (public.is_admin()) with check (public.is_admin());;
