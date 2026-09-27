// ============================================================================
//  urgency_rules.js — 뉴스 긴급도 공통 낱말 규칙 매처 (#216, 2026-09-25)
//
//  Python `urgency_rules.py`(크롤러·소급 도구)와 **같은 규칙**의 JS판. 대시보드 규칙 편집기의
//  「최근 기사에 적용해 보기」가 저장 전에 이것으로 적중·값 변경을 미리 센다. 두 구현은
//  `tests/fixtures/urgency_rules_cases.json` 한 파일을 함께 돈다(node tests/urgency_rules.test.js,
//  python -m unittest — TestUrgencyRules). 사내판도 두 파일과 케이스 파일을 그대로 복사한다.
//
//  매처 계약(설계안 §3): 입력 = NFC(제목 + ' ' + 요약), 부분 문자열·대소문자 그대로.
//  적중 = any 하나 이상 AND and_any 각 그룹 하나 이상(평면 배열 = 그룹 하나) AND none 없음.
//  목록 순서의 첫 적중 규칙 하나가 정한다(첫 적중 min이 이미 그 이상이면 값 그대로, 뒤 규칙 안 봄).
//  min = 하한, set = 지정. team_id·enabled·position은 보지 않는다(목록을 만드는 쪽 몫).
//
//  cite_verify.js와 같은 방식 — ESM export 없이 globalThis.UrgencyRules 에 붙인다(브라우저 <script>·node).
//  GitLab Pages는 나열된 파일만 싣는다 — .gitlab-ci.yml cp 목록에 이 경로가 있어야 한다.
// ============================================================================
(function (root) {
  'use strict';

  const LEVELS = ['참고', '보통', '긴급'];
  const MODES = ['min', 'set'];
  function rank(lv) { return LEVELS.indexOf(lv); }   // 모르는 값 = -1
  function nfc(s) { return typeof s === 'string' ? s.normalize('NFC') : ''; }

  function normalizeText(title, summary) {
    return nfc((title || '') + ' ' + (summary || ''));
  }

  // 표 행(any_words/none_words/mode/level)과 JSON("min"/"set": 등급, any/none) 두 모양을 같이 읽는다
  function ruleView(r) {
    let mode = r.mode, level = r.level;
    if (!mode) for (const m of MODES) if (r[m]) { mode = m; level = r[m]; break; }
    const anyW = r.any_words != null ? r.any_words : r.any;
    const andAny = r.and_any || [];
    const noneW = r.none_words != null ? r.none_words : r.none;
    let groups;
    if (andAny.length && andAny.every(function (x) { return typeof x === 'string'; })) groups = [andAny.slice()];
    else groups = andAny.filter(Array.isArray).map(function (g) { return g.slice(); });
    return { id: r.id, mode: mode, level: level, any: (anyW || []).slice(), groups: groups, none: (noneW || []).slice() };
  }

  function hasAny(text, words) {
    return words.some(function (w) { return w && text.indexOf(nfc(w)) !== -1; });
  }

  function matchUrgencyRules(rules, title, summary) {
    const text = normalizeText(title, summary);
    for (const r of rules || []) {
      const v = ruleView(r);
      if (!v.any.length || !hasAny(text, v.any)) continue;
      if (!v.groups.every(function (g) { return hasAny(text, g); })) continue;
      if (v.none.length && hasAny(text, v.none)) continue;
      return { id: v.id, mode: v.mode, level: v.level };
    }
    return null;
  }

  // → { level, ruleId, changed }  (Python은 튜플 (등급, 규칙 id|None, 변경 여부))
  function combine(hit, aiLevel) {
    if (!hit) return { level: aiLevel, ruleId: null, changed: false };
    let level;
    if (hit.mode === 'set') level = hit.level;
    else level = rank(hit.level) > rank(aiLevel) ? hit.level : aiLevel;
    return { level: level, ruleId: hit.id, changed: level !== aiLevel };
  }

  function applyUrgencyRules(rules, title, summary, aiLevel) {
    return combine(matchUrgencyRules(rules, title, summary), aiLevel);
  }

  // ── 팀 층(#250, 2026-09-27, 설계안 §10 — Fable 재검토) ──────────────────────────────────────
  // Python urgency_rules.py의 max_level·rule_input_text·team_rule_decision·effective_team_urgency·
  // division_urgency와 **같은 규칙**. 케이스 파일 tests/fixtures/urgency_team_cases.json을 함께 돈다.
  function maxLevel(a, b) { return rank(a) >= rank(b) ? a : b; }

  // 빈 글 판정 — Python _blank와 같은 문자 집합(JS \s + Python isspace만 공백으로 보는 U+001C~001F·U+0085)
  function isBlank(s) { return /^[\s\u001c-\u001f\u0085]*$/.test(s || ''); }

  // 규칙 입력의 요약 자리 — 수집 때 본 검색 요약(screen_text)이 있으면 그것, 없으면 저장 요약
  function ruleInputText(screenText, summary) {
    return !isBlank(screenText) ? screenText : (summary || '');
  }

  // → { level, rule_id } 또는 null(미적중 — 팀 행을 두지 않는다). 기준값 = 공통값
  function teamRuleDecision(teamRules, title, text, commonLevel) {
    const hit = matchUrgencyRules(teamRules, title, text);
    if (!hit) return null;
    return { level: combine(hit, commonLevel).level, rule_id: hit.id };
  }

  // 한 팀이 보는 등급 → { level, source }  source = common | human | rule | ai
  // rule 행은 지금 규칙 정의로 다시 계산(없음·꺼짐·다른 팀 규칙이면 공통값), 저장 urgency는 쓰지 않는다
  function effectiveTeamUrgency(commonLevel, teamRow, rulesById) {
    if (!teamRow) return { level: commonLevel, source: 'common' };
    const src = teamRow.source;
    if (src === 'rule') {
      const r = (rulesById || {})[teamRow.rule_id];
      if (!r || !r.enabled || r.team_id !== teamRow.team_id || rank(r.level) < 0 || MODES.indexOf(r.mode) === -1)
        return { level: commonLevel, source: 'common' };
      if (r.mode === 'set') return { level: r.level, source: 'rule' };
      return { level: maxLevel(commonLevel, r.level), source: 'rule' };
    }
    if ((src === 'human' || src === 'ai') && rank(teamRow.urgency) >= 0) return { level: teamRow.urgency, source: src };
    return { level: commonLevel, source: 'common' };
  }

  // 실장 화면 등급 = 그 실 팀들이 보는 등급 중 가장 높은 것 → { level, teams }(그 등급을 본 팀 id, teamIds 순서)
  function divisionUrgency(commonLevel, rowsByTeam, rulesById, teamIds) {
    if (!teamIds || !teamIds.length) return { level: commonLevel, teams: [] };
    const effs = teamIds.map(function (t) {
      return [t, effectiveTeamUrgency(commonLevel, (rowsByTeam || {})[t], rulesById).level];
    });
    let top = effs[0][1];
    for (let i = 1; i < effs.length; i++) top = maxLevel(top, effs[i][1]);
    return { level: top, teams: effs.filter(function (e) { return e[1] === top; }).map(function (e) { return e[0]; }) };
  }

  function isWordList(v, allowEmpty) {
    return Array.isArray(v) && (allowEmpty || v.length > 0) &&
      v.every(function (w) { return typeof w === 'string' && w.trim() !== ''; });
  }

  function validateRules(rows) {
    const errs = [];
    const seen = {};
    (rows || []).forEach(function (r, i) {
      if (!r || typeof r !== 'object' || Array.isArray(r)) { errs.push((i + 1) + '번: 규칙이 객체가 아님'); return; }
      const v = ruleView(r);
      const tag = (i + 1) + '번(' + (v.id || 'id 없음') + ')';
      if (typeof v.id !== 'string' || !v.id.trim()) errs.push(tag + ': id가 비어 있음');
      else if (seen[v.id]) errs.push(tag + ': id 중복');
      else seen[v.id] = true;
      if (MODES.indexOf(v.mode) === -1) errs.push(tag + ': mode는 min 또는 set');
      if (LEVELS.indexOf(v.level) === -1) errs.push(tag + ': level은 긴급·보통·참고 중 하나');
      const anyW = r.any_words != null ? r.any_words : r.any;
      if (!isWordList(anyW, false)) errs.push(tag + ': any 낱말이 비어 있거나 형식 오류');
      const andAny = r.and_any || [];
      if (!Array.isArray(andAny)) errs.push(tag + ': and_any는 배열');
      else if (andAny.length && !(isWordList(andAny, false) ||
               andAny.every(function (g) { return isWordList(g, false); })))
        errs.push(tag + ': and_any는 낱말 배열 또는 비지 않은 낱말 배열들의 배열');
      const noneW = r.none_words != null ? r.none_words : r.none;
      if (noneW != null && !isWordList(noneW, true)) errs.push(tag + ': none 형식 오류');
    });
    return errs;
  }

  const UrgencyRules = {
    LEVELS: LEVELS, MODES: MODES, normalizeText: normalizeText, ruleView: ruleView,
    matchUrgencyRules: matchUrgencyRules, combine: combine, applyUrgencyRules: applyUrgencyRules,
    validateRules: validateRules,
    maxLevel: maxLevel, ruleInputText: ruleInputText, teamRuleDecision: teamRuleDecision,
    effectiveTeamUrgency: effectiveTeamUrgency, divisionUrgency: divisionUrgency,
  };
  root.UrgencyRules = UrgencyRules;
  if (typeof module !== 'undefined' && module.exports) module.exports = UrgencyRules;
})(typeof globalThis !== 'undefined' ? globalThis : this);
