-- 20260927120740 internal_team_rule_import_253

-- #253 (2026-09-27, Fable 재검토) 사내판이 사외 팀 규칙을 같은 이름 팀의 기본값으로 받기 위한 비로그인(anon) 읽기 길 2개.
-- 사내 다리(export_news.py)는 anon 키로 REST를 읽는다(서비스 키 금지 원칙). 설계안 §10-4 결정 I2·I3.

-- ① teams: 번호·이름·실·순서 4칸만. daily_limit·unlimited·created_at은 계속 로그인 전용(authenticated 권한 불변).
--    18팀 이름은 이미 공개 저장소 설계안 §10·DB 설계도에 있다.
revoke select on public.teams from anon;
grant select (id, name, division, sort_order) on public.teams to anon;
drop policy if exists teams_sel_anon on public.teams;
create policy teams_sel_anon on public.teams for select to anon using (true);

-- ② urgency_rule_verdicts: 판정이 끝난 행(status='done')의 9칸만. requested_by(계정 uuid)·cost_usd·model·attempts·created_at은 비공개.
grant select (rule_id, sentence_rev, news_id, team_id, status, verdict, reason, input_kind, judged_at)
  on public.urgency_rule_verdicts to anon;
drop policy if exists urgency_rule_verdicts_sel_anon on public.urgency_rule_verdicts;
create policy urgency_rule_verdicts_sel_anon on public.urgency_rule_verdicts for select to anon using (status = 'done');
;
