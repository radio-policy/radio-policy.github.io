// node tests/cite_verify.test.js — supabase/functions/_shared/cite_verify.js 순수 로직 검증 (프레임워크 없음, 네트워크 없음)
// 픽스처는 2026-09-10 실제 자문(#155 사고)과 그때의 청크다.
var fs = require('fs');
var path = require('path');
var CV = require(path.join(__dirname, '..', 'supabase', 'functions', '_shared', 'cite_verify.js'));
var FX = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'cite_verify_fixture.json'), 'utf8'));
var C = FX.chunks;

var fails = 0, total = 0;
function eq(name, got, want) {
  total++;
  var g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) console.log('ok    ' + name);
  else { fails++; console.log('FAIL  ' + name + '\n      got  ' + g + '\n      want ' + w); }
}
function ok(name, cond, extra) {
  total++;
  if (cond) console.log('ok    ' + name);
  else { fails++; console.log('FAIL  ' + name + (extra !== undefined ? '\n      ' + JSON.stringify(extra) : '')); }
}

(async function main() {
  // ── articleKey / docFamily ──
  eq('articleKey 조', CV.articleKey('50조(금지행위)'), '50조');
  eq('articleKey 조의', CV.articleKey('32조의14(판매점 선임에 대한 승낙 등)'), '32조의14');
  eq('articleKey 별표는 null', CV.articleKey('별표 3(주파수할당대가)'), null);
  eq('docFamily', CV.docFamily(C.c50_136.doc_name), '전기통신사업법');

  // ── mergeChunkTexts: 136→137 겹침(≈90자)이 한 번만 남는다 ──
  var merged = CV.mergeChunkTexts([C.c50_136.content, C.c50_137.content, C.c50_138.content]);
  ok('merge 겹침 제거', merged.indexOf('대가 등을 산정하는 행위') !== -1 && merged.split('대가 등을 산정').length === 2, merged.slice(900, 1100));
  ok('merge 5호·5호의2·②가 한 본문에', /\n5\.\s/.test(merged) && /\n5의2\.\s/.test(merged) && merged.indexOf('②') !== -1);
  eq('merge 겹침 없으면 줄바꿈으로', CV.mergeChunkTexts(['가나다라마바사아자차카타파하가나다라마바', '완전히 다른 본문입니다 완전히 다른 본문입니다']),
     '가나다라마바사아자차카타파하가나다라마바\n완전히 다른 본문입니다 완전히 다른 본문입니다');

  // ── lawNameBefore / resolveLaw ──
  var fams = ['전기통신사업법', '전기통신사업법 시행령', '방송통신사업 금지행위 등에 대한 업무처리규정', '전파법'];
  eq('법령명: 바로 앞 단어', CV.resolveLaw(CV.lawNameBefore('- 전기통신사업법 '), fams), '전기통신사업법');
  eq('법령명: 시행령은 법과 구분', CV.resolveLaw(CV.lawNameBefore('전기통신사업법 시행령 '), fams), '전기통신사업법 시행령');
  eq('법령명: 괄호 건너뛰고 긴 이름', CV.resolveLaw(CV.lawNameBefore('- 방송통신사업 금지행위 등에 대한 업무처리규정(방미통위고시 제2026-11호) '), fams), '방송통신사업 금지행위 등에 대한 업무처리규정');
  eq('법령명: 뒤 단어만 맞아도(업무처리규정)', CV.resolveLaw(CV.lawNameBefore('업무처리규정 '), fams), '방송통신사업 금지행위 등에 대한 업무처리규정');
  eq('법령명: 문장 속 이름', CV.resolveLaw(CV.lawNameBefore('실제 판례에서도 전기통신사업법 '), fams), '전기통신사업법');
  eq('법령명: 동법은 inherit', CV.lawNameBefore('동법 ').inherit, true);
  eq('법령명: 이름 없음(불릿 시작)', CV.lawNameBefore('- '), null);
  eq('법령명: 별칭', CV.resolveLaw(CV.lawNameBefore('정보통신망법 '), ['정보통신망 이용촉진 및 정보보호 등에 관한 법률']), '정보통신망 이용촉진 및 정보보호 등에 관한 법률');
  eq('법령명: 법만 있으면 inherit', CV.lawNameBefore('법 ').inherit, true);

  // ── parseSegment ──
  var p = CV.parseSegment('제50조(금지행위) 제1항 제5호·5호의2: 대리점·판매점을 통한 … 제50조제2항에 따라 원칙적으로 … 예외입니다. ');
  eq('parse 조', p.key, '50조');
  eq('parse 항 (두 언급 합산)', p.paras, [1, 2]);
  eq('parse 호', p.items, ['5', '5의2']);
  var p2 = CV.parseSegment('- 전기통신사업법 제32조의14(판매점 선임에 대한 승낙 등): 대리점은 … 제32조의4제5항에 따른 … 안 됩니다. ');
  eq('parse 첫 조가 주인공(뒤의 타 조 참조는 무시)', [p2.key, p2.paras], ['32조의14', []]);
  eq('parse 원문자 항은 조 바로 뒤만', CV.parseSegment('전파법 제5조① 무선국은 … ① 첫째 ② 둘째 ').paras, [1]);
  eq('parse 별표만', CV.parseSegment('전파법 시행령 별표 3에 따른 산정식 ').kind, 'annex');
  eq('parse 없음', CV.parseSegment('실무상 통상적입니다.').kind, 'none');

  // ── findCitations on the real answer ──
  var cites = CV.findCitations(FX.answer);
  eq('표시 3개', cites.length, 3);
  eq('1번: 사업법 32조의14', [cites[0].key, cites[0].lawText], ['32조의14', '전기통신사업법']);
  eq('2번: 50조 ①② 5·5의2 (법령명 없음)', [cites[1].key, cites[1].paras, cites[1].items, cites[1].lawText || null], ['50조', [1, 2], ['5', '5의2'], null]);
  eq('3번: 업무처리규정 11조 (앞 줄의 52조의3에 안 끌림)', [cites[2].key, cites[2].lawText], ['11조', '업무처리규정']);

  // ── checkCitation: 138 조각만 있던 그날 → 제1항 없음 = missing ──
  var thatDay = [C.c32_14, C.c50_138, C.c11];
  var r0 = CV.checkCitation(cites[0], thatDay, []);
  var r1 = CV.checkCitation(cites[1], thatDay, []);
  var r2 = CV.checkCitation(cites[2], thatDay, []);
  eq('그날: 32조의14 ok', r0.status, 'ok');
  eq('그날: 50조 missing(①·5호 없음)', r1.status, 'missing');
  ok('그날: missing 사유에 조문 일부', /50조 제1항 원문 없음/.test(r1.reason), r1.reason);
  eq('그날: 업무처리규정 11조 ok (문서 확정)', [r2.status, r2.lawDoc], ['ok', '방송통신사업 금지행위 등에 대한 업무처리규정']);
  // 전체가 있었다면 → ok
  var full = [C.c32_14, C.c50_136, C.c50_137, C.c50_138, C.c11];
  var r1f = CV.checkCitation(cites[1], full, []);
  eq('통째: 50조 ok', r1f.status, 'ok');
  ok('통째: 정본 텍스트에 ①②·5의2', /①/.test(r1f.text) && /\n5의2\.\s/.test(r1f.text));
  // 법령명이 다른 문서를 가리키면 missing
  var wrongLaw = CV.checkCitation(Object.assign({}, cites[0], { lawInfo: { candidates: ['전파법'] }, candidates: [{ key: '32조의14', paras: [], items: [], lawInfo: { candidates: ['전파법'] } }] }), full.concat([{ id: 1, doc_name: '전파법(법률)(제21065호)(20260102)', article_no: '29조(혼신)', chunk_index: 0, content: '제29조 …' }]), []);
  eq('법령명이 다른 문서: missing', wrongLaw.status, 'missing');
  ok('바꿔 쓴 설명은 verbatim이 아니다(겹침 <0.6)', CV.quoteOverlap(cites[0].segment, C.c32_14.content) < 0.6, CV.quoteOverlap(cites[0].segment, C.c32_14.content));

  // ── #155-보론3: 조문 통째 인용 + 교차참조 (2026-09-11 11:05 대시보드 답변에서 3/4 오판) ──
  var q50 = '대리점, 판매점 또는 그 밖에 전기통신사업자와의 협정에 따라 전기통신사업자와 이용자 간의 계약 체결(체결된 계약 내용을 변경하는 것을 포함한다) 등을 대리하는 자가 제1항제5호 및 제5호의2의 행위를 한 경우에 그 행위에 대하여 제52조제1항과 제53조를 적용할 때에는 전기통신사업자가 그 행위를 한 것으로 본다';
  var d1 = CV.findCitations('## 3. 핵심 쟁점 ② — 금지행위(제50조) 및 대리점·판매점 행위의 사업자 귀속\n\n' + q50 + '[원문 확인됨]고 규정되어 있습니다.');
  ok('통째 인용: 겹침 ≥0.9', CV.quoteOverlap(d1[0].segment, merged) >= 0.9, CV.quoteOverlap(d1[0].segment, merged));
  var r50 = CV.checkCitation(d1[0], full, []);
  eq('통째 인용: 교차참조(52·53조)에 안 끌리고 50조 verbatim ok', [r50.status, r50.key, r50.verbatim], ['ok', '50조', true]);
  var q11a = '전기통신사업자가 대리점등에 대하여 다음 각 호의 1과 같이 실질적인 사전 예방조치를 취하였음에도 불구하고 대리점등의 「전기통신사업법」 제50조제1항제5호 및 제5호의2의 규정을 위반한 행위가 발생한 경우 전기통신사업자는 「전기통신사업법」 제50조제2항 후단의 \'상당한 주의\'를 기울인 것으로 본다.';
  var q11b = '이동통신사업자 관련해서는 이동통신사업자가 대리점 또는 판매점에 대하여 다음 각 호와 같이 실질적인 사전 예방조치를 취하였음에도 불구하고 대리점 또는 판매점의 「전기통신사업법」 제32조의12제1항, 제32조의15제2항ㆍ제3항의 규정을 위반한 행위가 발생한 경우 이동통신사업자는 「전기통신사업법」 제52조의3제2항 후단의 \'상당한 주의와 감독을 게을리하지 아니한 경우\'로 본다';
  var d2 = CV.findCitations('방송통신사업 금지행위 등에 대한 업무처리규정 제11조는 다음과 같이 규정합니다.\n\n' + q11a + ' [원문 확인됨]\n\n' + q11b + ' [원문 확인됨]고 규정되어');
  var r11a = CV.checkCitation(d2[0], full, []), r11b = CV.checkCitation(d2[1], full, []);
  eq('11조 첫 문장(교차참조 50조)은 11조 verbatim', [r11a.status, r11a.key, r11a.verbatim], ['ok', '11조', true]);
  eq('11조 둘째 문장(앞 줄 못 봄, 교차참조 32조의12 등)도 verbatim으로 구제', [r11b.status, r11b.key, r11b.verbatim], ['ok', '11조', true]);
  // 바꿔 쓴 설명 + 앞 줄에만 조 번호: 앞 줄의 조가 후보에 든다
  var d3 = CV.findCitations('## 금지행위(제50조)\n\n대리점이 위반하면 제52조제1항을 적용할 때 사업자가 한 것으로 본다는 취지입니다. [원문 확인됨]');
  var r3 = CV.checkCitation(d3[0], full, []);
  eq('앞 줄 제목의 50조를 후보로(52조는 컨텍스트에 없음)', [r3.status, r3.key, !!r3.verbatim], ['ok', '50조', false]);
  // 후보가 전부 컨텍스트에 없고 바꿔 쓴 문장이면 missing
  var d4 = CV.findCitations('제52조의3제2항에 따라 이통사가 면책됩니다. [원문 확인됨]');
  eq('후보 전부 없음 + 바꿔 씀: missing', CV.checkCitation(d4[0], full, []).status, 'missing');
  // 종합: verbatim은 Haiku에 안 보낸다
  var sentItems = null;
  var vv = await CV.verifyCitations({ answer: '## 금지행위(제50조)\n\n' + q50 + '[원문 확인됨]', chunks: full, callHaiku: async function (s, u) { sentItems = u; return '[]'; } });
  eq('verbatim은 판정 생략', [vv.verdicts[0].status, vv.verdicts[0].verbatim, sentItems], ['ok', true, null]);
  // 단항 조문에 "제1항"이라고 써도 잡지 않는다
  var single = CV.checkCitation(CV.findCitations('업무처리규정 제11조 제1항: 상당한 주의 [원문 확인됨]')[0], [C.c11], []);
  eq('단항 조문의 항 표기는 허용', single.status, 'ok');
  // 별표
  var an = CV.findCitations('전파법 시행령 별표 3의 산식에 따르면 … [원문 확인됨]')[0];
  eq('별표 있음', CV.checkCitation(an, [], ['전파법 시행령 별표 3']).status, 'ok');
  eq('별표 없음', CV.checkCitation(an, [], ['전파법 시행령 별표 12']).status, 'missing');
  eq('별표 12는 별표 1이 아니다', CV.checkCitation(CV.findCitations('별표 1에 따라 [원문 확인됨]')[0], [], ['전파법 시행령 별표 12']).status, 'missing');
  eq('인용 못 읽으면 unparsed', CV.checkCitation(CV.findCitations('그렇습니다. [원문 확인됨]')[0], full, []).status, 'unparsed');

  // ── pseudoChunksFromPrompt ──
  var prompt = '…\n■ 전파법 제16조(재할당) [원문 확인됨]\n① 과기정통부장관은 …\n\n■ 전파법 시행령 제18조(재할당) [원문 확인됨]\n① 법 제16조제1항 …\n→ 핵심 기한\n\n■ 전파법 제24조 제2항 — 무선국 자기적합확인 [원문 확인됨]\n② 제1항에도 …';
  var ps = CV.pseudoChunksFromPrompt(prompt);
  eq('프롬프트 핵심 조문 3개', ps.map(function (x) { return [CV.docFamily(x.doc_name), x.article_no]; }), [['전파법', '16조'], ['전파법 시행령', '18조'], ['전파법', '24조']]);
  var pc = CV.checkCitation(CV.findCitations('전파법 시행령 제18조에 따라 만료 6개월 전 신청 [원문 확인됨]')[0], ps, []);
  eq('프롬프트 조문 인용은 ok', pc.status, 'ok');

  // ── expandArticles (fetchArticle 가짜) ──
  var store = { '전기통신사업법(법률)(제21652호)(20260519)|50조': [C.c50_136, C.c50_137, C.c50_138], '전기통신사업법(법률)(제21652호)(20260519)|32조의14': [C.c32_14] };
  var calls = 0;
  var fetchArticle = async function (doc, key) { calls++; return store[doc + '|' + key] || []; };
  var ex = await CV.expandArticles([C.c50_138, C.c32_14, C.c11, { id: 9, doc_name: '뉴스.md', content: '기사' }], fetchArticle, {});
  eq('보강: 50조 1건', ex.expanded, 1);
  eq('보강: 추가 id 136·137', ex.addedIds, [27303, 27304]);
  eq('보강: 원소 수 유지(같은 조 중복 없음)', ex.chunks.length, 4);
  ok('보강: 첫 원소가 전문', ex.chunks[0]._full === true && /제50조\(금지행위\)\n①/.test(ex.chunks[0].content) && /③ 제1항에 따른/.test(ex.chunks[0].content));
  ok('보강: 뉴스 청크는 그대로', ex.chunks[3].content === '기사');
  // 예산 0이면 아무것도 안 붙는다
  var ex0 = await CV.expandArticles([C.c50_138], fetchArticle, { maxAddedChunks: 0 });
  eq('보강 예산 0', [ex0.expanded, ex0.addedIds], [0, []]);
  // 같은 조 두 조각이 검색됐으면 하나로 합쳐진다
  var ex2 = await CV.expandArticles([C.c50_136, C.c50_138], fetchArticle, {});
  eq('같은 조 두 조각 → 1개', [ex2.chunks.length, ex2.addedIds], [1, [27304]]);
  // 상한: 조각 4개 초과 조문은 검색된 조각 + 앞쪽만
  var big = []; for (var i = 0; i < 9; i++) big.push({ id: 100 + i, doc_name: 'D', article_no: '7조(긴)', chunk_index: i, content: '조각' + i + ' 본문본문본문본문본문본문본문본문본문본문본문본문본문본문' });
  var ex3 = await CV.expandArticles([big[7]], async function () { return big; }, { maxChunksPerArticle: 4 });
  ok('긴 조문: 검색 조각 포함 + 생략 안내', ex3.chunks[0]._full === false && /조각7/.test(ex3.chunks[0].content) && /중략/.test(ex3.chunks[0].content) && /9조각 중 5조각/.test(ex3.chunks[0].content), ex3.chunks[0].content);

  // ── verifyCitations 종합 (가짜 Haiku) ──
  var judged = null;
  var fakeHaiku = async function (system, user) { judged = user; return '```json\n[{"id":1,"verdict":"일치","reason":""},{"id":2,"verdict":"불일치","reason":"주체가 이통사인데 대리점으로 씀"},{"id":3,"verdict":"판단불가","reason":""}]\n```'; };
  var v = await CV.verifyCitations({ answer: FX.answer, chunks: full, annexSources: [], callHaiku: fakeHaiku });
  eq('종합: 판정 3건 상태', v.verdicts.map(function (x) { return x.status; }), ['ok', 'mismatch', 'unclear']);
  eq('종합: 바뀐 표시 1개', v.changed, 1);
  ok('종합: 50조 표시가 불일치 문구로', v.answer.indexOf('[⚠️ 원문과 다르게 설명됨 — 확인 필요]') !== -1 && v.answer.indexOf('[원문 확인됨, 참조4]') === -1);
  ok('종합: 다른 표시는 그대로', v.answer.indexOf('[원문 확인됨] 즉 명칭이') !== -1 && v.answer.indexOf('[원문 확인됨, 참조1]') !== -1);
  ok('종합: Haiku에 원문·인용문 3항목', /### 항목 3/.test(judged) && /\[원문\]\n제50조\(금지행위\)/.test(judged));
  // 그날 상황: 50조 missing → Haiku에는 2건만, 표시는 미확인 문구
  var v2 = await CV.verifyCitations({ answer: FX.answer, chunks: thatDay, annexSources: [], callHaiku: async function (s, u) { judged = u; return '[{"id":1,"verdict":"일치"},{"id":2,"verdict":"일치"}]'; } });
  eq('그날: 상태', v2.verdicts.map(function (x) { return x.status; }), ['ok', 'missing', 'ok']);
  ok('그날: 미확인 문구', v2.answer.indexOf('[⚠️ 원문 미확인 — 검색 결과에 해당 조문 없음]') !== -1);
  ok('그날: Haiku 2항목', /### 항목 2/.test(judged) && !/### 항목 3/.test(judged));
  // Haiku 실패는 표시 유지(fail-open)
  var v3 = await CV.verifyCitations({ answer: FX.answer, chunks: full, annexSources: [], callHaiku: async function () { throw new Error('boom'); } });
  eq('Haiku 실패: 표시 유지', [v3.changed, v3.answer === FX.answer], [0, true]);
  // callHaiku 없음 → 2안만
  var v4 = await CV.verifyCitations({ answer: FX.answer, chunks: thatDay, annexSources: [] });
  eq('판정 없이 대조만', v4.verdicts.map(function (x) { return x.status; }), ['ok', 'missing', 'ok']);
  eq('표시 없는 답변은 무변경', (await CV.verifyCitations({ answer: '표시 없음', chunks: full })).changed, 0);

  // ── 역참조 발췌 (#155-보론4) ──
  var art20 = { id: 27210, doc_name: C.c50_136.doc_name, article_no: '20조(등록의 취소 등)', chunk_index: 35, content: '제20조(등록의 취소 등)\n① 과학기술정보통신부장관은 기간통신사업자가 다음 각 호의 어느 하나에 해당하면 그 등록의 전부 또는 일부를 취소하거나 1년 이내의 기간을 정하여 사업의 전부 또는 일부의 정지를 명할 수 있다.\n1.  속임수나 그 밖의 부정한 방법으로 등록을 한 경우\n5의2.  제32조의4제5항에 따른 관리ㆍ감독 또는 같은 조 제6항에 따른 모니터링을 소홀히 하여 타인의 명의를 사용하거나 그 밖의 부정한 방법으로 전기통신역무 제공계약이 대통령령으로 정하는 기준 이상 다수 체결된 경우' };
  var art51 = { id: 27306, doc_name: C.c50_136.doc_name, article_no: '51조(사실조사 등)', chunk_index: 139, content: '제51조(사실조사 등)\n① 방송미디어통신위원회는 … 제32조의14제1항ㆍ제3항ㆍ제5항, 제32조의15제2항ㆍ제3항 또는 제50조제1항을 위반한 행위가 있다고 인정하면 … 조사를 하게 할 수 있다.\n② …\n4.  제2호의 대리점ㆍ판매점을 제외하고 그 밖에 전기통신사업자의 업무를 위탁받아 취급하는 자' };
  var art32_40 = { id: 9, doc_name: C.c50_136.doc_name, article_no: '99조(가짜)', chunk_index: 300, content: '제99조 이 조는 제32조의40을 인용한다' };
  var bu = { id: 10, doc_name: C.c50_136.doc_name, article_no: '부칙 제21652호(20260519)', chunk_index: 400, content: '부칙 제1조 제32조의4의 개정규정은 …' };
  var citingStore = { '32조의4': [art20, bu, art32_40], '32조의14': [art51], '50조': [art51] };
  var fetchCiting = async function (doc, key) { return citingStore[key] || []; };
  ok('citeRegex: 32조의4는 32조의40과 구분', CV.citeRegex('32조의4').test('제32조의4제5항') && !CV.citeRegex('32조의4').test('제32조의40'));
  ok('citeRegex: 32조는 32조의4와 구분', CV.citeRegex('32조').test('제32조제1항') && !CV.citeRegex('32조').test('제32조의4'));
  eq('excerptAround: 인용 줄만', CV.excerptAround(art20.content, CV.citeRegex('32조의4'), 300).slice(0, 12), '5의2.  제32조의4');
  var ce = await CV.buildCitingExcerpts([C.c32_14, C.c50_138, { id: 27241, doc_name: C.c50_136.doc_name, article_no: '32조의4(부정이용)', chunk_index: 74, content: '…' }], fetchCiting, {});
  eq('역참조: 20조·51조 2건(부칙·자기참조 제외, 51조 중복 1회)', ce.chunks.map(function (x) { return CV.articleKey(x.article_no); }), ['51조', '20조']);
  ok('역참조: 블록 텍스트에 제목·인용 문장', /\[역참조 1\] .*제51조\(사실조사 등\) — 제32조의14 인용/.test(ce.text) && /제20조\(등록의 취소 등\) — 제32조의4 인용\n5의2\.  제32조의4제5항/.test(ce.text), ce.text);
  eq('역참조: 원본 조각 id', ce.ids, [27306, 27210]);
  // 발췌 의사청크로 검증이 통과한다(호 줄이 발췌에 있음)
  var d20 = CV.findCitations('전기통신사업법 제20조 제1항 제5호의2: 관리·감독을 소홀히 하면 등록취소·영업정지 사유 [원문 확인됨]');
  eq('발췌만으로 20조①5호의2 인용 ok', CV.checkCitation(d20[0], full.concat(ce.chunks), []).status, 'ok');
  eq('발췌에 없는 호는 missing', CV.checkCitation(CV.findCitations('전기통신사업법 제20조 제1항 제3호 [원문 확인됨]')[0], full.concat(ce.chunks), []).status, 'missing');
  eq('역참조 없음', (await CV.buildCitingExcerpts([C.c11], fetchCiting, {})).text, '');
  eq('역참조 상한 total', (await CV.buildCitingExcerpts([C.c32_14, C.c50_138, { id: 27241, doc_name: C.c50_136.doc_name, article_no: '32조의4(부정이용)', chunk_index: 74, content: '…' }], fetchCiting, { maxTotal: 1 })).chunks.length, 1);

  console.log('\n' + (total - fails) + '/' + total + ' passed');
  process.exit(fails ? 1 : 0);
})().catch(function (e) { console.error(e); process.exit(2); });
