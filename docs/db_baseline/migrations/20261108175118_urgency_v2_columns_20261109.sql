-- 20261108175118 urgency_v2_columns_20261109

-- 긴급도 1차 판정 v2 재설계(2026-11-09, 설계 local_docs/긴급도_내림원인_261109/설계_1차판정_재설계_261109.md §2-1·§3·§6-1).
-- 운영은 v1 그대로(app_config urgency_grader 없음 = 코드 상수 'v1') — 이 마이그레이션은 칸만 더한다.
-- 기존 표의 칸 추가라 표 단위 GRANT를 따른다(news_feed: anon SELECT·service_role 전부, #214). authenticated UPDATE는 칸 단위라
-- A3(대시보드 「같은 사건 전부 내리기」) 두 칸만 더한다 — 공통 등급 변경은 그대로 관리자만(news_feed_edit_guard, urgency 칸 검사).
-- 외래 키 없음(urgency_event_of): 기록 칸 — 대표 기사가 지워져도 이 칸이 삭제를 막거나 함께 바뀌면 안 된다(#327 칸과 같은 이유).
alter table public.news_feed
  add column if not exists urgency_grader text,
  add column if not exists urgency_v2_scope text,
  add column if not exists urgency_v2_grade text,
  add column if not exists urgency_v2_basis text,
  add column if not exists urgency_reason text,
  add column if not exists urgency_lowered_by text,
  add column if not exists urgency_event_of uuid;

comment on column public.news_feed.urgency_grader is
  '긴급도를 정한 판정기(v2 재설계 2026-11-09): rule(set 규칙) · v1(Haiku 4.5 한 낱말 + 2차 확인) · v2(구조화 출력 판정기) · v1-fallback(v2 실패로 v1). 그림자(shadow) 기간에는 운영값이 v1이라 v1.';
comment on column public.news_feed.urgency_v2_scope is 'v2 판정기 출력 scope(통신|언저리|타영역) — v2·그림자에서 AI 판정한 모든 행. 그림자면 운영 등급과 무관한 기록.';
comment on column public.news_feed.urgency_v2_grade is 'v2 판정기 출력 등급(긴급|보통|참고, 영역 상한 전) — v2·그림자에서 AI 판정한 모든 행.';
comment on column public.news_feed.urgency_v2_basis is 'v2 판정기 출력 basis(즉시대응 항목 이름 또는 없음).';
comment on column public.news_feed.urgency_reason is 'v2 판정기 출력 reason(40자 안, 등급 뒤에 생성되는 기록용).';
comment on column public.news_feed.urgency_lowered_by is
  '긴급을 누가 내렸나: check(2차 확인·v2 영역 상한 — urgency_check_capped와 같은 행) · propagate(내림 전파, PROPAGATE_MODE on일 때만) · operator-event(대시보드 「같은 사건 전부 내리기」) · null.';
comment on column public.news_feed.urgency_event_of is
  '같은 사건의 대표 기사 news_feed.id — 공통 알림 억제가 「대표 X의 재보도」라 한 결과(A2)·내림 전파의 원인 기사(A1). 사슬 아님(대표의 대표를 적지 않는다).';

-- 기존 2차 확인 내림 행 — 뜻 그대로 옮긴다(capped = 기계가 영역으로 내림)
update public.news_feed set urgency_lowered_by = 'check'
 where urgency_check_capped is true and urgency_lowered_by is null;

grant update (urgency_lowered_by, urgency_event_of) on public.news_feed to authenticated;

-- importance_feedback.reason: 운영자 수정 사유(사람 행만, 40자). anon은 읽지 못한다 — 표 단위 SELECT를 칸 단위로 바꾼다
-- (기존 9칸은 그대로 공개, 대시보드 비로그인 읽기는 select('news_id')뿐 — 칸을 적어 읽는다). authenticated·service_role은 표 단위 그대로.
alter table public.importance_feedback add column if not exists reason text;
comment on column public.importance_feedback.reason is '운영자 수정 사유(선택, 40자) — 사람이 쓴 행만. anon 비공개(칸 단위 SELECT에서 뺌). v2 판정기 피드백 줄에 「(MM-DD, 사유)」로 붙는다.';
revoke select on public.importance_feedback from anon;
grant select (id, news_id, title, summary, ai_importance, user_importance, created_at, updated_at, team_id)
  on public.importance_feedback to anon;
;
