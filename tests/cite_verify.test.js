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
  var wrongLaw = CV.checkCitation(Object.assign({}, cites[0], { lawInfo: { candidates: ['전파법'] } }), full.concat([{ id: 1, doc_name: '전파법(법률)(제21065호)(20260102)', article_no: '29조(혼신)', chunk_index: 0, content: '제29조 …' }]), []);
  eq('법령명이 다른 문서: missing', wrongLaw.status, 'missing');
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

  console.log('\n' + (total - fails) + '/' + total + ' passed');
  process.exit(fails ? 1 : 0);
})().catch(function (e) { console.error(e); process.exit(2); });
