// node tests/urgency_audit_node.js <in.json> <out.json>
// 긴급도 팀 층 두 구현 대조(#250, 설계안 §5 원칙 8 · 문장 조건 #251 §10-2)의 JS 쪽 — tools_urgency_audit.py가 만든 입력을
// supabase/functions/_shared/urgency_rules.js(대시보드가 쓰는 파일 그대로)로 계산해 결과만 쓴다. 의존성 없음.
//
// 입력 { datasets: { 이름: { articles, rules, rulesets, rows, verdicts, divisions, queries } } }
//   rules     = 규칙 표 전체(꺼진 것 포함) — byId는 여기서 대시보드처럼 대입으로 만든다
//   rulesets  = { 팀 id: 그 팀의 켜진 규칙(position, id 순) } — 거르기·정렬은 Python이 한 번만 한다
//   rows      = team_urgency 행 → rowsByNews[news_id][team_id]
//   verdicts  = urgency_rule_verdicts 행(#251) → 기사마다 모아 verdictMap(그 기사 행 전부, 받은 순서)
//   queries   = ['txt', i] | ['dec', i, 팀] | ['cand', i, 팀] | ['eff', i, 팀] | ['div', i, 실] | ['max', a, b]
//               (i = articles 인덱스; dec = teamRuleDecisionJudged, cand = sentenceCandidates — 둘 다 그 기사 verdictMap)
// 출력 { node, unicode, ms, results: { 이름: [질의마다 결과] } } — 결과 모양은 Python 함수와 같다.
'use strict';
var fs = require('fs');
var path = require('path');
var UR = require(path.join(__dirname, '..', 'supabase', 'functions', '_shared', 'urgency_rules.js'));

function runDataset(ds) {
  var byId = {};
  (ds.rules || []).forEach(function (r) { byId[r.id] = r; });
  var rowsByNews = {};
  (ds.rows || []).forEach(function (row) {
    var m = rowsByNews[row.news_id] || (rowsByNews[row.news_id] = {});
    m[row.team_id] = row;
  });
  // 판정 기록 — Map(열쇠 비교가 값 그대로, '__proto__' 같은 기사 id도 안전). Python group_verdicts와 같은 순서
  var verdictsByNews = new Map();
  (ds.verdicts || []).forEach(function (v) {
    var k = v.news_id === undefined ? null : v.news_id;
    if (!verdictsByNews.has(k)) verdictsByNews.set(k, []);
    verdictsByNews.get(k).push(v);
  });
  var rulesets = ds.rulesets || {};
  var divisions = ds.divisions || {};
  var arts = ds.articles || [];
  var vmaps = new Map();                       // 기사 인덱스 → verdictMap — 기사마다 한 번(Python compute_python과 같게)
  function vmap(i) {
    if (!vmaps.has(i)) vmaps.set(i, UR.verdictMap(verdictsByNews.get(arts[i].id) || []));
    return vmaps.get(i);
  }
  return (ds.queries || []).map(function (q) {
    var kind = q[0];
    if (kind === 'max') return UR.maxLevel(q[1], q[2]);
    var a = arts[q[1]];
    if (kind === 'txt') return UR.ruleInputText(a.screen_text, a.summary);
    if (kind === 'dec') {
      return UR.teamRuleDecisionJudged(rulesets[q[2]] || [], a.title,
        UR.ruleInputText(a.screen_text, a.summary), a.common, vmap(q[1]));
    }
    if (kind === 'cand') {
      return UR.sentenceCandidates(rulesets[q[2]] || [], a.title,
        UR.ruleInputText(a.screen_text, a.summary), vmap(q[1]));
    }
    var rows = rowsByNews[a.id] || {};
    if (kind === 'eff') {
      var row = rows[q[2]];
      return UR.effectiveTeamUrgency(a.common, row === undefined ? null : row, byId);
    }
    if (kind === 'div') return UR.divisionUrgency(a.common, rows, byId, divisions[q[2]] || []);
    throw new Error('모르는 질의 종류: ' + kind);
  });
}

function main() {
  var inPath = process.argv[2], outPath = process.argv[3];
  if (!inPath || !outPath) {
    console.error('사용법: node tests/urgency_audit_node.js <in.json> <out.json>');
    process.exit(2);
  }
  var t0 = Date.now();
  var input = JSON.parse(fs.readFileSync(inPath, 'utf8'));
  var results = {};
  Object.keys(input.datasets || {}).forEach(function (name) {
    results[name] = runDataset(input.datasets[name]);
  });
  fs.writeFileSync(outPath, JSON.stringify({
    node: process.version, unicode: process.versions.unicode, ms: Date.now() - t0, results: results,
  }), 'utf8');
}

main();
