// node tests/cite_universe_pairs.test.js — P-3″(#314-보론5, 2026-10-16 · Fable 재검토 18-2 §5) 우주 쌍 전수 잠금. 네트워크·AI 0.
//
// #314 P(표시 바로 앞 출처가 조 전체면 판정기 대상을 조 전체로 넓힘)는 항·호를 적은 앞 언급과 끝 언급이 **같은 문서군**일 때만 넓힌다(checkCitation paraWide ←
// sameLawDoc). 첫 대안 P-3′(공통 끝 낱말 글자 규칙)은 이 전수에서 다른 문서 74쌍을 「같음」으로 읽어 기각됐다(최대 점검 2) — 그래서 이 하네스가 잠근다:
//   실DB 법령·고시 문서군 277(tests/fixtures/cite_law_universe.json) 중 이름 끝 낱말이 같은 서로 다른 문서 A·B의 순서쌍마다
//   「A 제10조제2항에 따라 봅니다. 「B 제10조」 [원문 확인됨]」 — 자료에 A 제10조(①②)가 있어 대상은 A 제10조제2항, B가 다른 문서라 넓히면(paraWide) 틀린 것.
// 조건(문맥) 넷: ① 자료 A·B + DB 목록 ② 자료 A만 + DB 목록(운영 기본 — B는 자료 밖) ③ 자료 A·B, 목록 없음(목록 RPC 실패) ④ 자료 A만, 목록 없음.
// 넓힌 쌍은 둘로 가른다: 「P-3″ 판단 오류」(B 이름만 따로 읽으면 B로 맞는데 넓힘) — 네 조건 모두 0을 잠근다 · 「이름 읽기 자체 오선택」(B 이름만 따로 읽어도 A로 맞음 —
// B 자신의 인용도 A와 대조되는 이름 맞추기의 한계: 쉼표 든 이름(정적 측정 (a) 5와 같은 문서)·④ 목록 없이 B가 A의 끝 낱말 꼬리로 맞는 #315 fail-open) — 수만 적는다.
// 인용문은 판정기로 가는 길이(24자↑)라 모든 쌍이 paraWide 판단 자리까지 간다(도달 수를 함께 센다 — 0이 공허하지 않게).
// 대조군: 같은 문서(A = B, 산문 머리말을 양쪽에 붙인 꼴 포함)는 넓혀야 한다 — 넓힘이 꺼지면(P-3의 과함 — 탐침 A·B) 실패.
'use strict';
var fs = require('fs');
var path = require('path');
// --cv <파일> = 다른 판(예: git show HEAD:… 로 뽑은 옛 판)을 같은 잣대로 잰다(비교용 — 잠금은 저장소 판에만 의미가 있다)
var cvArg = process.argv.indexOf('--cv');
var CV = require(cvArg !== -1 ? path.resolve(process.argv[cvArg + 1]) : path.join(__dirname, '..', 'supabase', 'functions', '_shared', 'cite_verify.js'));
var UJ = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'cite_law_universe.json'), 'utf8'));
var U = UJ.families.slice();
U.typeIndex = new Map(Object.keys(UJ.types).map(function (f) { return [f, new Set(UJ.types[f])]; }));

var docOf = function (f) { return f + '(' + ((UJ.types[f] || ['법률'])[0]) + ')(제1호)(20250101)'; };
var art10 = function (f, id) {
  return { id: id, doc_name: docOf(f), article_no: '10조(신고)', chunk_index: 10,
    content: '제10조(신고) ① 사업자는 대통령령으로 정하는 바에 따라 장관에게 신고하여야 한다.\n② 제1항에 따라 일괄처리를 받은 사업자는 신고를 한 것으로 본다.' };
};
var lastWord = function (f) { var w = f.trim().split(/\s+/); return w[w.length - 1].replace(/[\s·ㆍ‧•]/g, ''); };
var widened = function (s, chunks, univ) {
  var c = CV.findCitations(s)[0];
  var r = CV.checkCitation(c, chunks, [], univ ? { universe: U } : undefined);
  return { wide: !!r.paraWide, doc: r.doc ? CV.docFamily(r.doc) : null, status: r.status, reach: r.status === 'ok' && !r.verbatim && !!c.wholeRef };
};
// 판정기로 가는 길이의 인용문(이름·조 번호를 빼고 24자↑) — 짧으면 noclaim이라 넓힘 판단 자리까지 못 간다
var CLAIM = '일괄처리를 받은 사업자는 관계 법령에 따른 신고를 별도로 하지 않아도 신고를 한 것으로 보아 절차가 끝납니다';
var famsOf = function (list, univ) { var a = list.slice(); a.typeIndex = new Map(list.map(function (f) { return [f, new Set(UJ.types[f] || [])]; })); if (univ) a.universe = U; return a; };

var byLast = new Map();
for (var f of UJ.families) { var k = lastWord(f); if (!byLast.has(k)) byLast.set(k, []); byLast.get(k).push(f); }
var pairs = [];
byLast.forEach(function (fams) { if (fams.length < 2) return; for (var A of fams) for (var B of fams) if (A !== B) pairs.push([A, B]); });

var COND = [
  { name: '① 자료 A·B + 목록', withB: true, univ: true, lock: true },
  { name: '② 자료 A만 + 목록', withB: false, univ: true, lock: true },
  { name: '③ 자료 A·B, 목록 없음', withB: true, univ: false, lock: true },
  { name: '④ 자료 A만, 목록 없음(fail-open)', withB: false, univ: false, lock: false },
];
var fails = 0;
console.log('끝 낱말이 같은 서로 다른 문서 순서쌍: ' + pairs.length);
for (var cd of COND) {
  var bad = [], misread = [], notA = 0, reach = 0;
  pairs.forEach(function (p) {
    var A = p[0], B = p[1];
    var ctx = [A].concat(cd.withB ? [B] : []);
    var chunks = [art10(A, 1)].concat(cd.withB ? [art10(B, 2)] : []);
    var r = widened(A + ' 제10조제2항에 따라 ' + CLAIM + '. 「' + B + ' 제10조」 [원문 확인됨]', chunks, cd.univ);
    if (r.doc !== A) notA++;
    if (r.reach) reach++;
    if (!r.wide) return;
    // B 이름만 따로 읽어도 A로 맞으면 이름 맞추기 자체의 오선택(P-3″ 밖) — 아니면 P-3″ 판단 오류
    var alone = CV.resolveLaw(CV.lawNameBefore(B + ' '), famsOf(ctx, cd.univ));
    (alone === B ? bad : misread).push(A + ' ⟷ ' + B + (alone !== B ? ' (B 이름만 읽어도 ' + alone + ')' : ''));
  });
  var line = cd.name + ': P-3″ 판단 오류(다른 문서를 같음으로 넓힘) ' + bad.length + ' / ' + pairs.length + ' · 넓힘 판단 자리 도달 ' + reach +
    (notA ? ' · 대표가 A 아님 ' + notA : '') + ' | 이름 읽기 자체 오선택(범위 밖·기록) ' + misread.length;
  if (bad.length || reach < pairs.length - notA) { fails++; console.log('FAIL  ' + line); bad.slice(0, 8).forEach(function (x) { console.log('      ' + x); }); }
  else console.log('ok    ' + line);
  misread.slice(0, cd.lock ? 5 : 3).forEach(function (x) { console.log('      기록: ' + x); });
}

// 대조군 — 같은 문서는 넓힌다(277 × 꼴 셋, 목록 있음·없음): 깨끗한 낫표 · 첫 언급 산문 · 양쪽 산문 머리말
var forms = [
  function (A) { return CLAIM + '(' + A + ' 제10조제2항). 「' + A + ' 제10조」 [원문 확인됨]'; },
  function (A) { return '사업자는 신고해야 하며 ' + A + ' 제10조제2항에 따라 ' + CLAIM + '. 「' + A + ' 제10조」 [원문 확인됨]'; },
  function (A) { return '앞서 살펴본 ' + A + ' 제10조제2항에 따라 ' + CLAIM + ' 방금 확인한 ' + A + ' 제10조 [원문 확인됨]'; },
];
[true, false].forEach(function (univ) {
  var miss = [];
  UJ.families.forEach(function (A) {
    forms.forEach(function (fm, i) { var r = widened(fm(A), [art10(A, 1)], univ); if (!r.wide && r.doc === A) miss.push('꼴' + (i + 1) + ' ' + A); });
  });
  var tot = UJ.families.length * forms.length;
  var line = '대조군(같은 문서는 넓힘, 목록 ' + (univ ? '있음' : '없음') + '): 못 넓힘 ' + miss.length + ' / ' + tot;
  if (miss.length) { fails++; console.log('FAIL  ' + line); miss.slice(0, 8).forEach(function (x) { console.log('      ' + x); }); }
  else console.log('ok    ' + line);
});
console.log(fails ? '\n실패 ' + fails : '\n모두 통과');
process.exit(fails ? 1 : 0);
