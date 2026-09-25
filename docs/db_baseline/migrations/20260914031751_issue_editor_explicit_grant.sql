-- 20260914031751 issue_editor_explicit_grant

-- 이슈맵 편집은 '승인 회원'이 아니라 '관리자가 따로 권한을 준 사람'만 (2026-09-14 운영자 결정).
-- 가입 승인(approved)은 열람·자문 자격일 뿐이고, 이슈맵은 운영자가 검수해 승인·기각하는
-- 판단의 산물이라 편집 권한을 따로 둔다. 기본값 false — 아무도 못 고치는 상태에서 시작한다.
alter table public.profiles
  add column if not exists can_edit_issues boolean not null default false;

create or replace function public.is_issue_editor()
returns boolean
language sql
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.profiles p
    where p.user_id = auth.uid()
      and p.approved and p.active
      and (p.role = 'admin' or p.can_edit_issues)
  );
$$;

grant execute on function public.is_issue_editor() to authenticated;

-- 앞서 is_approved_user() 로 바꿔 둔 것을 한 단계 더 조인다.
alter policy issues_ins on public.issues with check (is_issue_editor());
alter policy issues_upd on public.issues using (is_issue_editor()) with check (is_issue_editor());
alter policy issue_links_ins on public.issue_links with check (is_issue_editor());
alter policy issue_links_upd on public.issue_links using (is_issue_editor()) with check (is_issue_editor());
alter policy issue_links_del on public.issue_links using (is_issue_editor());;
