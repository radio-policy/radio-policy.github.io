-- 20261002075246 urgency_rules_close_updated_by_269

-- #269 (2026-10-02, Fable 판정 Q4): urgency_rules.updated_by(계정 uuid)를 anon·authenticated SELECT에서 닫는다.
-- 가입만 한 미승인 계정도 authenticated라 anon만 닫으면 닫은 것이 아니다. INSERT·UPDATE 권한은 그대로(트리거가 updated_by를 본인 id로 덮어쓴다).
-- 대시보드는 88b1b5e(app.js?v=20261002e)부터 13칸 목록으로 읽는다 — select('*')는 이제 권한 오류.
revoke select on public.urgency_rules from anon, authenticated;
grant select (id, team_id, position, mode, level, any_words, and_any, none_words, note, enabled, updated_at, sentence, sentence_rev)
  on public.urgency_rules to anon, authenticated;;
