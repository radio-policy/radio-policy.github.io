// node tests/lawmap_desc.test.js — 관계도 질문 매칭 순수 함수(app.js) 검증 (#285, 2026-10-06, 프레임워크·네트워크 없음)
//   선 설명의 자기 법령 조 번호(Fable 판정 Q2 ㄴ 허상 건너뛰기·ㄷ 범위·인용 수 폭), 조문 질문 정렬((a) 인접 선 뒤로),
//   주제 매칭(Q3 ⓐ 긴 낱말 안의 짧은 낱말 제외·ⓑⓒ 동점), 약칭 풀이(Q4 (b)). 예문은 local_docs/관계도_IDC주제_재검토_판정_261006.md 그대로.
//   살아 있는 관계도 대조는 node tools_lawmap_match.js (기대값 tests/fixtures/lawmap_match_cases.json).
var fs = require('fs');
var path = require('path');
var ROOT = path.join(__dirname, '..');
require(path.join(ROOT, 'supabase', 'functions', '_shared', 'cite_verify.js'));
require(path.join(ROOT, 'supabase', 'functions', '_shared', 'rag_core.js'));
var appSrc = fs.readFileSync(path.join(ROOT, 'app.js'), 'utf8');

function grabFn(name) {
  var i = appSrc.indexOf('function ' + name + '(');
  if (i < 0) throw new Error('app.js에 없음: ' + name);
  var j = appSrc.indexOf('{', i);
  for (var k = j, d = 0; k < appSrc.length; k++) {
    if (appSrc[k] === '{') d++;
    else if (appSrc[k] === '}') { d--; if (d === 0) return appSrc.slice(i, k + 1); }
  }
  throw new Error('괄호 짝 없음: ' + name);
}
function grabVar(name) {
  var m = appSrc.match(new RegExp('(?:var|let) ' + name + ' = ([\\s\\S]*?);[ \\t]*(?://[^\\n]*)?\\n'));
  if (!m) throw new Error('app.js에 없음: ' + name);
  return 'var ' + name + ' = ' + m[1] + ';';
}
var FNS = ['lmNormName', 'lawmapTopicWords', 'lawmapParseArticleQuery', 'lawmapNodeByName', 'lawmapDescOwnRefs', 'lawmapRefCovers', 'lawmapDescCites',
  'lawmapDescNormRange', 'lawmapDescArticleCount', 'lawmapIsAdjacent', 'lawmapArticleHits', 'lawmapTopicDegree', 'lawmapAliasNode',
  'lawmapTopicWordSet', 'lawmapWordShadowed', 'lawmapMatchQuery', 'lawmapArtNums'];
var VARS = ['LAWMAP_MATCH_STOP', 'LAWMAP_DESC_ART_RE', 'LAWMAP_KIND_WORDS', 'LAWMAP_PREFIX_WORD_RE', 'LAWMAP_LAWISH_RE', 'LAWMAP_LIST_GAP_RE', '_lawMapTopicDeg', '_lawMapTopicWordSet'];
function load(citeVerify) {
  var src = VARS.map(grabVar).concat(FNS.map(grabFn)).join('\n') + '\nreturn {' + FNS.join(',') + '};';
  return new Function('extractKeywords', 'CiteVerify', src)(globalThis.RagCore.extractKeywords, citeVerify);
}
var L = load(globalThis.CiteVerify);

var fails = 0, total = 0;
function eq(name, got, want) {
  total++;
  var g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) console.log('ok    ' + name);
  else { fails++; console.log('FAIL  ' + name + '\n      got  ' + g + '\n      want ' + w); }
}
function ownKeys(desc, law) {   // 자기 조로 친 매치를 「N조」·「N~M조」·「N조의K」 꼴로
  return L.lawmapDescOwnRefs(desc, law).filter(function(r) { return r.own; }).map(function(r) {
    return r.parts.map(function(p) { return p.lo === p.hi ? p.lo : p.lo + '~' + p.hi; }).join('·') + '조' +
      (r.ui !== null ? '의' + r.ui + (r.uiEnd !== null ? '~의' + r.uiEnd : '') : '');
  });
}
function cites(desc, law, keys) { return keys.map(function(k) { return L.lawmapDescCites(desc, k, law); }); }

// ── ㄴ 허상 건너뛰기 (판정 Q2-2 예문) ──
var D1 = '[인접 제도] 전파법 제37조·제45조·제47조 위임, 제1조';
eq('전파법 목록 위임 → 자기 조 1조만', ownKeys(D1, '무선설비규칙'), ['1조']);
eq('전파법 목록 위임 — 37·45·47 아님, 1 맞음', cites(D1, '무선설비규칙', ['37조', '45조', '47조', '1조']), [false, false, false, true]);
eq('전파법 목록 위임 — 인용 수 1', L.lawmapDescArticleCount(D1, '무선설비규칙'), 1);
var D2 = '정보통신망법 제46조·영 제37조제2항에 따른 집적정보통신시설(IDC) 보호조치 세부기준 (제1조)';
eq('정보통신망법·영 → 지침 자기 조 1조만', ownKeys(D2, '집적정보 통신시설 보호지침'), ['1조']);
eq('보호지침 제46조 허상 아님', L.lawmapDescCites(D2, '46조', '집적정보 통신시설 보호지침'), false);
eq('「사업법 제38조」 in 전기통신사업법 → 38조(이름 끝 일치)', ownKeys('사업법 제38조로 맺은 도매제공 대가', '전기통신사업법'), ['38조']);
eq('「사업법 제38조」 in 방발법 → 다른 법령', ownKeys('사업법 제38조로 맺은 도매제공 대가(방발법 제37조의2제3항)', '방송통신발전 기본법'), []);
eq('「같은 법 제18조」 in 분산에너지법 → 없음', ownKeys('AIDC법 제19조, 같은 법 제18조에 따른 특례', '분산에너지 활성화 특별법'), []);
eq('「법 제23조①」 in 법률 선 → 23조', ownKeys('법 제23조① 보안인증', '클라우드컴퓨팅 발전 및 이용자 보호에 관한 법률'), ['23조']);
eq('「법 제24조제2항」 in 시행령 선 → 다른 법령', ownKeys('법 제24조제2항에 따른 지하철 와이파이', '전파법 시행령'), []);
eq('「시행령 제23조의2」 in 시행령 선 → 자기', ownKeys('시행령 제23조의2', '방송통신발전 기본법 시행령'), ['23조의2']);
eq('「영 제37조」 in 시행령 선 → 자기', ownKeys('영 제37조', '정보통신망 이용촉진 및 정보보호 등에 관한 법률 시행령'), ['37조']);
eq('「고시 제3조」 in 고시 선 → 자기', ownKeys('고시 제3조', '방송통신기자재등의 적합성평가에 관한 고시'), ['3조']);
eq('「기준 제2조」 in 지침 선 → 다른 법령', ownKeys('기준 제2조제2호', '집적정보 통신시설 보호지침'), []);
eq('「등급기준 제2조」 in 지침 선 → 다른 법령', ownKeys('등급기준 제2조제2호', '집적정보 통신시설 보호지침'), []);
eq('「이 법 제5조」 in 시행령 선 → 자기', ownKeys('이 법 제5조', '전파법 시행령'), ['5조']);
eq('「동법 제5조」 → 다른 법령', ownKeys('동법 제5조', '전파법'), []);
eq('「」 낫표 앞머리 「전파법」 제37조 → 다른 법령', ownKeys('「전파법」 제37조', '무선설비규칙'), []);
eq('앞머리 없는 조 → 자기', ownKeys('(제3조·제4조)', '무선설비규칙'), ['3조', '4조']);
eq('법령 없이 부르면 모두 자기 조(종전 동작)', ownKeys(D1, null), ['37조', '45조', '47조', '1조']);
// 목록 전파: ①②·제N항 사이도
var D3 = '클라우드컴퓨팅법 제23조②·제23조의2~의4 위임 — 공공부문 클라우드 보안인증(CSAP)';
eq('「제23조②·제23조의2~의4」 앞머리 → 전부 건너뜀', ownKeys(D3, '클라우드컴퓨팅서비스 보안인증에 관한 고시'), []);
eq('「제23조의2」 허상 아님', L.lawmapDescCites(D3, '23조의2', '클라우드컴퓨팅서비스 보안인증에 관한 고시'), false);
eq('「제N조제M항·제K조」 목록 전파', ownKeys('영 제15조제5항·제18조제1항 위임, 제1조', '방송통신발전기금 운용·관리규정'), ['1조']);

// ── ㄷ 범위 표기 + 인용 수 폭 ──
var D4 = '방송통신재난관리기본계획·통신재난관리심의위원회·재난 보고 (제6장, 제35조~제39조의2)';
eq('「제35조~제39조의2」 덮는 조', cites(D4, '방송통신발전 기본법', ['35조', '36조', '39조', '39조의2', '35조의2', '39조의3', '40조']),
  [true, true, true, true, true, false, false]);
eq('「제35조~제39조의2」 인용 수 5(폭)', L.lawmapDescArticleCount(D4, '방송통신발전 기본법'), 5);
eq('「제35~38조」 의 없는 범위는 의 없는 조만', cites('(제35~38조)', '방송통신발전 기본법', ['36조', '36조의2', '38조']), [true, false, true]);
eq('「제23조의2~의4」(앞머리 없음) 덮는 조', cites('(제23조의2~의4)', '어느 법률', ['23조', '23조의2', '23조의3', '23조의4', '23조의5']), [false, true, true, true, false]);
eq('「제23조의2~제23조의4」 접기', L.lawmapDescNormRange('제23조의2~제23조의4'), '제23조의2~의4');
eq('「제23조의2~의4」 인용 수 3', L.lawmapDescArticleCount('(제23조의2~의4)', '어느 법률'), 3);
eq('「제37조」≠「제37조의2」', cites('(제37조)', '전기통신사업법', ['37조', '37조의2']), [true, false]);
eq('「제35·37조」 목록', cites('(제35·37조)', '전기통신사업법', ['35조', '36조', '37조']), [true, false, true]);
eq('기본계획 선 인용 수 4', L.lawmapDescArticleCount('제35조 기본계획 수립(제1항제5호: …), 제35조의2 통신재난관리심의위원회, 제36조 수립절차, 제36조의2 이행', '방송통신발전 기본법'), 4);

// ── 카드 발췌 첫 자기 조 ──
eq('lawmapArtNums 첫 자기 조(앞머리 건너뜀)', L.lawmapArtNums(D1, { name: '무선설비규칙' }), { nums: [1], wants: ['1조'] });
eq('lawmapArtNums 법령 없이 = 종전(첫 조)', L.lawmapArtNums(D1), { nums: [37], wants: ['37조'] });
eq('lawmapArtNums 범위', L.lawmapArtNums('제24~25조'), { nums: [24, 25], wants: ['24조', '25조'] });
eq('lawmapArtNums 의N', L.lawmapArtNums('제24조의2'), { nums: [24], wants: ['24조의2'] });
eq('lawmapArtNums 조 없는 「제1항」은 안 읽음', L.lawmapArtNums('제1항제5호'), { nums: [], wants: [] });
eq('lawmapArtNums Q1(b) 새 문안 → 제1조', L.lawmapArtNums('[인접 제도] 주요 집적정보통신시설 사업자등의 중요통신시설에는 등급기준 고시가 먼저 적용되고(등급기준 2조2호), 거기에 없는 IDC 재난관리·보호조치는 이 지침의 세부기준을 따른다(등급기준 3조의2) — 지침 본문은 \'IDC 보호\' 주제 (제1조)', { name: '집적정보 통신시설 보호지침' }), { nums: [1], wants: ['1조'] });

// ── 인접 선 판정 ──
eq('[인접 제도]로 시작', L.lawmapIsAdjacent('[인접 제도] 정보통신공사업법 …'), true);
eq('[시행예정] 뒤 [인접 제도]', L.lawmapIsAdjacent('[시행예정 — 2027.3.10 시행] [인접 제도] AIDC 사업자등의 신고'), true);
eq('중간의 [인접 제도]는 본래 선', L.lawmapIsAdjacent('보호조치(제46조) — [인접 제도] ISMS 인증 의무(제47조②2)'), false);

// ── 조문 질문 정렬 (Q2 (a)) — 가짜 관계도 ──
var T = function(id, name, desc) { return { id: id, name: name, node_type: 'topic', description: desc || '' }; };
var N = function(id, name, doc) { return { id: id, name: name, node_type: 'law', doc_name: doc === undefined ? name + '(법률)' : doc }; };
var E = function(id, s, t, desc, w) { return { id: id, source_id: s, target_id: t, description: desc, weight: w || 1 }; };
var nodes = [T('t1', '방송통신재난관리기본계획'), T('t2', '통신재난 대응'), T('t3', '집적정보통신시설(IDC·데이터센터) 보호'),
  N('l1', '방송통신발전 기본법')];
var edges = [E('e1', 't1', 'l1', '제35조 기본계획 수립(제1항제5호: …), 제35조의2 …, 제36조 수립절차, 제36조의2 이행', 1),
  E('e2', 't2', 'l1', '… (제6장, 제35조~제39조의2)', 3),
  E('e3', 't3', 'l1', '[인접 제도] 큰 IDC를 주요방송통신사업자로(제35조제1항제5호)', 1)];
var h = L.lawmapArticleHits(nodes[3], '35조', nodes, edges).map(function(x) { return x.topic.name + (x.adj ? '(인접)' : ''); });
eq('방발법 제35조 → 기본계획, 통신재난 대응, IDC(인접)', h, ['방송통신재난관리기본계획', '통신재난 대응', '집적정보통신시설(IDC·데이터센터) 보호(인접)']);
eq('인접 선만 인용하면 인접 선 1위', L.lawmapArticleHits(nodes[3], '35조', nodes, [edges[2]]).map(function(x) { return x.topic.name; }), ['집적정보통신시설(IDC·데이터센터) 보호']);
var r1 = L.lawmapMatchQuery('방송통신발전 기본법 제35조', nodes, edges);
eq('lawmapMatchQuery 조문 갈래', [r1.mode, r1.via, r1.hits[0].topic.name], ['article', 'name', '방송통신재난관리기본계획']);

// ── 약칭 풀이 (Q4 (b)) ──
var an = [T('a1', '집적정보통신시설(IDC·데이터센터) 보호'), T('a2', '재난안전통신망'),
  N('b1', '정보통신망 이용촉진 및 정보보호 등에 관한 법률'), N('b2', '정보통신망법', null), N('b3', '재난안전통신망법'),
  N('b4', '정보통신망 이용촉진 및 정보보호 등에 관한 법률 시행령')];
var ae = [E('f1', 'a1', 'b1', '보호조치(제46조)', 2), E('f2', 'a2', 'b3', '재난안전통신망(제7조)', 1), E('f3', 'a1', 'b4', '대상 규모(제37조)', 1),
  E('f4', 'b2', 'b1', '조문 인용 12회', 12)];
var q1 = L.lawmapMatchQuery('정보통신망법 46조', an, ae);
eq('「정보통신망법 46조」 스텁(주제 선 0) → 정식 노드', [q1.mode, q1.via, q1.lawNode.id, q1.hits.length && q1.hits[0].topic.id], ['article', 'alias', 'b1', 'a1']);
var q2 = L.lawmapMatchQuery('망법 제46조', an, ae);
eq('「망법」 끝 일치(재난안전통신망법)보다 약칭 표', [q2.mode, q2.lawNode && q2.lawNode.id], ['article', 'b1']);
var q3 = L.lawmapMatchQuery('정보통신망법 시행령 제37조', an, ae);
eq('「정보통신망법 시행령」 → 정식 시행령', [q3.mode, q3.lawNode && q3.lawNode.id], ['article', 'b4']);
var L0 = load(undefined);
var q4 = L0.lawmapMatchQuery('정보통신망법 46조', an, ae);
eq('CiteVerify 없으면 종전(스텁 노드, 주제 없음)', [q4.mode, q4.via, q4.lawNode.id, q4.hits.length], ['article', 'name', 'b2', 0]);
var an2 = an.concat([N('b5', '방송법')]);   // 원문 있는 노드는 주제 선 0이어도 바꾸지 않음
var q5 = L.lawmapMatchQuery('방송법 제5조', an2, ae);
eq('원문 있는 노드(주제 선 0)는 약칭 풀이 안 함', [q5.mode, q5.via, q5.lawNode.id], ['article', 'name', 'b5']);
var q6 = L.lawmapMatchQuery('방발법 제35조', an, ae);
eq('「방발법」(약칭 표에 없음) → 주제 갈래', q6.mode, 'topic');

// ── 주제 매칭 (Q3 ⓐⓑⓒ) ──
var tn = [T('c1', '통신시설 등급·관리', '주요통신사업자 중요통신시설 등급 지정 및 관리'), T('c2', '집적정보통신시설(IDC·데이터센터) 보호', '집적정보통신시설(데이터센터·IDC) 사업자등의 의무 — 출입 통제·재난 대비'),
  T('c3', 'AI 규제·진흥', '인공지능 기본법'), T('c4', '적합성평가', '적합성평가 절차'), T('c5', '적합성평가 국제상호인정(MRA)', '상호인정 절차'), T('c6', '정보보호 인증·공시', '')];
function top(q) { var r = L.lawmapMatchQuery(q, tn, []); return r.best && r.score >= 3 ? r.best.name : null; }
eq('ⓐ 「통신시설」 ⊂ 「집적정보통신시설」 제외', L.lawmapWordShadowed('통신시설', '집적정보통신시설재난관리', L.lawmapTopicWordSet(tn)), true);
eq('ⓐ 따로도 나오면 유지', L.lawmapWordShadowed('통신시설', '통신시설등급과집적정보통신시설', L.lawmapTopicWordSet(tn)), false);
eq('「집적정보통신시설 재난관리」 → IDC', top('집적정보통신시설 재난관리'), '집적정보통신시설(IDC·데이터센터) 보호');
eq('「통신시설 등급」 → 통신시설 등급·관리', top('통신시설 등급'), '통신시설 등급·관리');
eq('ⓑ 「AI 데이터센터」 길이 합 5 > 2 → IDC', top('AI 데이터센터'), '집적정보통신시설(IDC·데이터센터) 보호');
eq('ⓑ 「AIDC 특별법」 3 > 2 → IDC', top('AIDC 특별법'), '집적정보통신시설(IDC·데이터센터) 보호');
eq('ⓒ 「적합성평가 절차」 비율 1/1 > 1/3', top('적합성평가 절차'), '적합성평가');
eq('주제 낱말 나누기(괄호 낱말 없음)', L.lawmapTopicWords('집적정보통신시설(IDC·데이터센터) 보호'), ['집적정보통신시설', 'IDC', '데이터센터', '보호']);

console.log('\n' + (total - fails) + '/' + total + ' 통과');
process.exit(fails ? 1 : 0);
