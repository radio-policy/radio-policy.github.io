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

console.log('\n' + (total - fails) + '/' + total + ' 통과');
if (fails) process.exit(1);
