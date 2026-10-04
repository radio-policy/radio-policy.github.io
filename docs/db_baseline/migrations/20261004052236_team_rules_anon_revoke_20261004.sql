-- 20261004052236 team_rules_anon_revoke_20261004

-- #277 ③ — 사내 다리가 team_rules_export(RPC)로 옮긴 뒤(사내 회신 10-04 14:15 첫 회차 정상) anon의 팀 규칙 행·판정 직접 읽기를 닫는다.
-- 공통 행(team_id null)·teams 4칸 anon 읽기는 그대로. 칸 GRANT(anon 13칸·9칸)도 그대로 — 정책이 행을 막는다(anon 읽기는 오류가 아니라 빈 목록).
drop policy if exists urgency_rules_sel on public.urgency_rules;
create policy urgency_rules_sel_anon on public.urgency_rules for select to anon using (team_id is null);
create policy urgency_rules_sel on public.urgency_rules for select to authenticated using (true);
drop policy if exists urgency_rule_verdicts_sel_anon on public.urgency_rule_verdicts;;
