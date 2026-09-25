-- 20260908080959 news_edit_requires_approved_user

-- #133 (2026-09-08) 뉴스 편집(중요도·잠금·삭제)과 브리핑 원문 갱신은 승인된 로그인 계정만.
-- 열람은 그대로 공개. anon은 news_feed의 is_read·content·summary 컬럼만 갱신할 수 있다
-- (읽음 표시·본문 캐시·요약 저장 — 화면 편의 기능이라 열어 둔다).

create or replace function public.is_approved_user()
returns boolean
language sql stable security definer
set search_path to 'public'
as $$
  select exists (select 1 from profiles
                 where user_id = auth.uid() and approved and active)
$$;

-- news_feed UPDATE: anon은 컬럼 3개만, authenticated는 승인 프로필만
revoke update on public.news_feed from anon;
grant update (is_read, content, summary) on public.news_feed to anon;
drop policy if exists news_feed_upd on public.news_feed;
create policy news_feed_upd_anon on public.news_feed
  for update to anon using (true) with check (true);
create policy news_feed_upd_auth on public.news_feed
  for update to authenticated using (public.is_approved_user()) with check (public.is_approved_user());

-- news_feed DELETE: 승인 프로필만 (종전엔 anon 포함 누구나)
drop policy if exists news_feed_del on public.news_feed;
create policy news_feed_del on public.news_feed
  for delete to authenticated using (public.is_approved_user());

-- importance_feedback 쓰기: 승인 프로필만 (SELECT는 그대로 공개 — 학습 데이터 열람)
drop policy if exists imp_fb_ins on public.importance_feedback;
drop policy if exists imp_fb_upd on public.importance_feedback;
create policy imp_fb_ins on public.importance_feedback
  for insert to authenticated with check (public.is_approved_user());
create policy imp_fb_upd on public.importance_feedback
  for update to authenticated using (public.is_approved_user()) with check (public.is_approved_user());

-- deleted_news INSERT(삭제 시 재수집 방지 기록): 승인 프로필만
drop policy if exists deleted_news_ins on public.deleted_news;
create policy deleted_news_ins on public.deleted_news
  for insert to authenticated with check (public.is_approved_user());

-- daily_briefings UPDATE(중요도 변경 시 🔴 동기화): 승인 프로필만 (종전엔 anon 포함)
drop policy if exists daily_briefings_upd on public.daily_briefings;
create policy daily_briefings_upd on public.daily_briefings
  for update to authenticated using (public.is_approved_user()) with check (public.is_approved_user());;
