// node tests/urgency_rules.test.js — supabase/functions/_shared/urgency_rules.js 매처 검증(#216, 네트워크 없음)
// 케이스는 Python(TestUrgencyRules)·사내판과 같은 파일 tests/fixtures/urgency_rules_cases.json.
var fs = require('fs');
var path = require('path');
var UR = require(path.join(__dirname, '..', 'supabase', 'functions', '_shared', 'urgency_rules.js'));
var CASES = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'urgency_rules_cases.json'), 'utf8'));

var fails = 0, total = 0;
function eq(name, got, want) {
  total++;
  var g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) console.log('ok    ' + name);
  else { fails++; console.log('FAIL  ' + name + '\n      got  ' + g + '\n      want ' + w); }
}

CASES.forEach(function (c) {
  eq(c.name + ' (형식)', UR.validateRules(c.rules), []);
  var r = UR.applyUrgencyRules(c.rules, c.title, c.summary, c.ai);
  eq(c.name, [r.level, r.ruleId, r.changed], [c.expect.level, c.expect.rule_id, c.expect.changed]);
});
eq('NFD 케이스가 실제로 NFD', CASES.some(function (c) { return (c.title + c.summary) !== (c.title + c.summary).normalize('NFC'); }), true);

var v = UR.validateRules;
eq('검증: mode 오류', v([{ id: 'a', mode: 'max', level: '보통', any_words: ['x'] }]).length > 0, true);
eq('검증: level 오류', v([{ id: 'a', mode: 'min', level: '높음', any_words: ['x'] }]).length > 0, true);
eq('검증: any 비어 있음', v([{ id: 'a', mode: 'min', level: '보통', any_words: [] }]).length > 0, true);
eq('검증: 빈 그룹', v([{ id: 'a', mode: 'min', level: '보통', any_words: ['x'], and_any: [[]] }]).length > 0, true);
eq('검증: id 중복', v([{ id: 'a', min: '보통', any: ['x'] }, { id: 'a', min: '보통', any: ['y'] }]).length > 0, true);
eq('검증: 평면 and_any 정상', v([{ id: 'a', min: '보통', any: ['x'], and_any: ['y', 'z'] }]), []);

// ── 팀 층(#250) — Python TestUrgencyTeamLayer와 같은 파일 ──
var T = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'urgency_team_cases.json'), 'utf8'));
var byId = {};
T.rules.forEach(function (r) { byId[r.id] = r; });
function teamRules(teamId) {
  return T.rules.filter(function (r) { return r.team_id === teamId && r.enabled; })
    .sort(function (a, b) { return (a.position - b.position) || (a.id < b.id ? -1 : 1); });
}
eq('팀 규칙 형식', UR.validateRules(T.rules), []);
T.input_text_cases.forEach(function (c) { eq('[입력] ' + c.name, UR.ruleInputText(c.screen_text, c.summary), c.expect); });
T.decision_cases.forEach(function (c) {
  eq('[팀 규칙] ' + c.name, UR.teamRuleDecision(teamRules(c.team_id), c.title, c.text, c.common), c.expect);
});
T.effective_cases.forEach(function (c) { eq('[팀 등급] ' + c.name, UR.effectiveTeamUrgency(c.common, c.row, byId), c.expect); });
T.division_cases.forEach(function (c) {
  var rows = {};
  Object.keys(c.rows_by_team).forEach(function (k) { rows[parseInt(k, 10)] = c.rows_by_team[k]; });
  eq('[실장] ' + c.name, UR.divisionUrgency(c.common, rows, byId, c.team_ids), c.expect);
});

// ── 문장 조건(#251) — Python TestUrgencyTeamLayer와 같은 파일 ──
// 문장 규칙이 없으면 판정 반영 함수 = 기존 teamRuleDecision
T.decision_cases.forEach(function (c) {
  eq('[문장 없음=기존] ' + c.name, UR.teamRuleDecisionJudged(teamRules(c.team_id), c.title, c.text, c.common, {}), c.expect);
});
var S = T.sentence_rules.filter(function (r) { return r.enabled; })
  .sort(function (a, b) { return (a.position - b.position) || (a.id < b.id ? -1 : 1); });
eq('문장 규칙 형식', UR.validateRules(T.sentence_rules), []);
T.sentence_cases.forEach(function (c) {
  eq('[문장 후보] ' + c.name, UR.sentenceCandidates(S, c.title, c.text, c.verdicts), c.expect_candidates);
  eq('[문장 판정] ' + c.name, UR.teamRuleDecisionJudged(S, c.title, c.text, c.common, c.verdicts), c.expect_decision);
});
T.verdict_map_cases.forEach(function (c) { eq('[판정 모음] ' + c.name, UR.verdictMap(c.rows), c.expect); });
T.has_sentence_cases.forEach(function (c) { eq('[문장 있음] ' + c.name, UR.hasSentence(c.rule), c.expect); });
eq('NFD 문장 케이스가 실제로 NFD', T.sentence_cases.some(function (c) { return c.title !== c.title.normalize('NFC'); }), true);

console.log('\n' + (total - fails) + '/' + total + ' 통과');
if (fails) process.exit(1);
