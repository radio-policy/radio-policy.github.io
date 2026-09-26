// node tests/rag_core.test.js — supabase/functions/_shared/rag_core.js 순수 규칙 검증 (#215, 2026-09-25, 프레임워크·네트워크 없음)
//
// 두 가지를 본다. ① 규칙 자체(키워드 추출·어휘 대응·제외어·RRF 융합·조문 정밀검색 순위·컨텍스트 문구)가 기대대로인가.
// ② 구조 가드 — app.js·rag.ts가 여기 있는 이름을 다시 정의하지 않았나(재정의는 곧 '두 벌'로 되돌아가는 것).
var fs = require('fs');
var path = require('path');
var ROOT = path.join(__dirname, '..');
// 번호로 지목한 조문(#245)은 인용 검증기의 법령명 읽기(lawNameBefore·lawScope)를 쓴다 — 브라우저·Edge처럼 먼저 싣는다
require(path.join(ROOT, 'supabase', 'functions', '_shared', 'cite_verify.js'));
var RC = require(path.join(ROOT, 'supabase', 'functions', '_shared', 'rag_core.js'));

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

// ── 내보내기 목록 ──
var NAMES = ['PRIORITY_KW_RE', 'VERB_TAIL', 'extractKeywords', 'LAW_SYNONYMS', 'PRACTICE_TERMS', 'lawSynonymKeywords',
  'expandQueryForSemantic', 'GENERIC_QUERY_WORDS', 'QUERY_TITLE_STOP', 'isTitleStop', 'lawRank', 'DOMAIN_DOC_RE',
  'extractNewsKeywords', 'PERDOC_LIMIT', 'TOTAL_CHUNK_CUT', 'STREAM_IDLE_MS', 'EXPAND_OPTS', 'CITING_OPTS',
  'ANNEX_MAX_UNITS', 'ANNEX_MAX_CHUNKS', 'ASM_RARE_MAX', 'RRF_K', 'articleBonus', 'rankChunks', 'titleActWeights',
  'rankLawHits', 'NAMED_ARTICLE_MAX', 'namedArticleRefs', 'pickNamedArticles', 'fetchNamedArticles', 'buildRagContext', 'buildKbContext'];
NAMES.forEach(function (n) { ok('export ' + n, RC[n] !== undefined); });

// ── 법령 키워드 추출 ──
eq('extractKeywords 법령 명사 우선·상한 5', RC.extractKeywords('우리 회사가 직접 운영하는 대리점에서 추가지원금을 이용자에 따라 다르게 지급하면 문제인가요'),
  ['대리점', '추가지원금', '이용자', '우리', '회사']);   // '지급하면'은 우선 명사가 아니라 뒤로 밀려 잘린다
eq('extractKeywords 용언 어미를 조사보다 먼저(#244, "운영하는"→"운영")', RC.extractKeywords('주파수를 할당하고 운영하는 경우'), ['주파수', '할당', '운영', '경우']);
eq('extractKeywords 어미 확장(#244, 변경하려면)', RC.extractKeywords('기간통신사업 등록을 변경하려면'), ['등록', '기간통신사업', '변경']);
eq('extractKeywords 어미 확장(#244, 산정하나요)', RC.extractKeywords('주파수 재할당 대가는 어떻게 산정하나요'), ['주파수', '재할당', '대가', '산정']);
eq('extractKeywords 낱말 전체가 어미면 버림(#244, 해야)', RC.extractKeywords('주파수 반납 해야 하나'), ['주파수', '반납']);
eq('extractKeywords 취소하는→취소(#244)', RC.extractKeywords('위치정보사업 허가를 취소하는 경우'), ['위치정보사업', '허가', '취소', '경우']);
eq('extractKeywords 요청 말투 제외(#244, 알려줘)', RC.extractKeywords('적합성평가 면제 대상 기자재를 알려줘'), ['적합성평', '면제', '대상', '기자재']);
eq('extractKeywords 요청 말투는 조사 떼기 전 낱말로도(#244, 다른가·무엇인가)', RC.extractKeywords('전파법 제16조와 시행령 제18조는 무엇인가 다른가'), ['전파법', '제16조', '시행령', '제18조']);
// 기각 가드(#244): 상투어를 추출에서 버리면 대응표·확장어가 10칸 안으로 들어와 조문 정밀검색 순위를 흔든다(전파법 제25조의2 탈락 실측)
eq('extractKeywords 상투어는 추출에서 버리지 않음(#244 기각안)', RC.extractKeywords('3G 종료 관련 조항은?'), ['3G', '종료', '관련', '조항']);

// ── 뉴스 키워드 추출 (2026-09-25 합집합) ──
eq('extractNewsKeywords 조사 절단·분야어 우선', RC.extractNewsKeywords('같은 지하철인데 통신사 와이파이 속도 차이 분석해줘'), ['지하철', '와이파이', '속도']);
eq('extractNewsKeywords 대시보드에만 있던 분야어(해킹·유출)', RC.extractNewsKeywords('해킹 유출 사고 대응 방법'), ['해킹', '유출', '사고']);
eq('extractNewsKeywords 봇에만 있던 분야어(3G·종료·IoT)', RC.extractNewsKeywords('3G 종료 이후 IoT 회선은 처리'), ['3G', '종료', 'IoT', '이후', '회선', '처리']);
eq('extractNewsKeywords 분야어 밖은 긴 단어 먼저', RC.extractNewsKeywords('가나 가나다라 가나다 전망'), ['가나다라', '가나다', '가나']);
eq('extractNewsKeywords 조사 나는', RC.extractNewsKeywords('경쟁사는 어떻게'), ['경쟁사']);

// ── 어휘 대응 ──
eq('lawSynonymKeywords 3G 종료', RC.lawSynonymKeywords('3G 서비스 종료 절차'), ['휴업', '폐업', '폐지', '휴지', '운용휴지', '주파수회수', '주파수할당의 취소', '이용기간']);
eq('lawSynonymKeywords 없음', RC.lawSynonymKeywords('무선국 검사 주기'), []);
eq('expandQueryForSemantic 리파밍', RC.expandQueryForSemantic('리파밍 관련 법'), '리파밍 관련 법 주파수회수 주파수재배치 주파수 회수 주파수 재배치');
eq('expandQueryForSemantic 원문 유지', RC.expandQueryForSemantic('무선국 검사'), '무선국 검사');
eq('PRACTICE_TERMS 기관명 별칭', RC.lawSynonymKeywords('방통위 의결'), ['방송통신위원회', '방통위', '방송미디어통신위원회', '방미통위']);
eq('LAW_SYNONYMS 폐업→휴업·폐업(#244)', RC.lawSynonymKeywords('기간통신사업을 폐업하려면'), ['휴업', '폐업']);
eq('LAW_SYNONYMS 휴업→휴업·폐업(#244)', RC.lawSynonymKeywords('역무 휴업 승인 요건'), ['휴업', '폐업']);

// ── 제외어·위계 ──
ok('isTitleStop 일반어', RC.isTitleStop('직접', '직접 운영') === true);
ok('isTitleStop 법령 행위어는 제외 안 함', RC.isTitleStop('할당', '주파수 할당') === false);
ok('isTitleStop 목록에 없는 말(지원금)은 제외 안 함', RC.isTitleStop('지원금', '기지국 설치 지원금') === false);
ok('isTitleStop 목록의 말(지원)은 제외', RC.isTitleStop('지원', '기지국 설치 지원') === true);
eq('lawRank', [RC.lawRank('전파법(법률)'), RC.lawRank('전파법 시행령(대통령령)'), RC.lawRank('전파법 시행규칙(과학기술정보통신부령)'), RC.lawRank('무선설비규칙(고시)'), RC.lawRank(undefined)], [4, 3, 2, 1, 1]);
ok('GENERIC ⊂ QUERY_TITLE_STOP', RC.GENERIC_QUERY_WORDS.every(function (w) { return RC.QUERY_TITLE_STOP.indexOf(w) >= 0; }));
ok('isTitleStop 다른(#244 — 「다른 법령과의 관계」 제목 가점 차단)', RC.isTitleStop('다른', '다른 사업자와 무엇이 다른가') === true);
(function () {
  // rankLawHits 주제 점수에서 '다른'이 빠진다(#244): '다른' 한 낱말만 겹치는 조문은 주제 점수 0
  var h = [{ id: 1, doc_name: '어느 고시(고시)', article_no: '3조(다른 법령과의 관계)', content: '', _act: 0, _hits: 0, _top: 0 }];
  RC.rankLawHits(h, '다른 사업자', 5);
  ok('rankLawHits 주제 점수에서 상투어 제외(#244)', h[0]._top === 0, h[0]._top);   // 변경 전엔 '다른'(2)이 걸렸다
})();

// ── 상한 상수 ──
eq('PERDOC_LIMIT', RC.PERDOC_LIMIT, { '추가지식': 8, 'default': 3 });
eq('상한 상수', [RC.TOTAL_CHUNK_CUT, RC.STREAM_IDLE_MS, RC.ANNEX_MAX_UNITS, RC.ANNEX_MAX_CHUNKS, RC.ASM_RARE_MAX, RC.RRF_K], [15, 180000, 2, 6, 40, 60]);
eq('EXPAND_OPTS', RC.EXPAND_OPTS, { maxArticles: 10, maxChunksPerArticle: 4, maxAddedChunks: 14 });
eq('CITING_OPTS', RC.CITING_OPTS, { maxPerArticle: 4, maxTotal: 8, maxLen: 300 });

// ── RRF 융합 ──
var U = 0.5 / 61;
ok('articleBonus 조문 +', RC.articleBonus('25조의2') === U);
ok('articleBonus 별표 0', RC.articleBonus('별표 3') === 0 && RC.articleBonus('붙임 1') === 0);
ok('articleBonus 부칙 −', RC.articleBonus('부칙 제2조') === -U && RC.articleBonus('별지 서식') === -U);
ok('articleBonus 없음 0', RC.articleBonus(undefined) === 0);
(function () {
  var q = '3G 종료 시 휴업 절차';
  var chunks = [
    { id: 1, doc_name: '전기통신사업법(법률)', doc_category: '법령', article_no: '19조(사업의 휴업·폐업)', content: '휴업 또는 폐업하려면 신고' },
    { id: 2, doc_name: '주파수정책연구.pdf', doc_category: '기타', article_no: null, content: '3G 종료 논의', _semantic_score: 0.9 },
    { id: 3, doc_name: '전파법 시행령(대통령령)', doc_category: '법령', article_no: '부칙 제1조', content: '시행일', _trgm_score: 0.3 },
    { id: 4, doc_name: '전파법(법률)', doc_category: '법령', article_no: '25조의2(무선국의 폐지)', content: '폐지 또는 운용휴지', _semantic_score: 0.6 },
  ];
  var picked = RC.rankChunks(chunks, ['종료', '휴업', '폐업', '폐지'], ['종료', '휴업'], q);
  // id4 = 키워드 목록 + 시맨틱 목록 두 곳에서 순위(RRF 합) > id1 = 키워드 목록 1위만 > pdf(시맨틱 1위지만 파일 감점) > 부칙(감점)
  eq('rankChunks 순위(두 목록 합 > 한 목록 1위 > pdf > 부칙)', picked.map(function (c) { return c.id; }), [4, 1, 2, 3]);
  var byId = {}; chunks.forEach(function (c) { byId[c.id] = c; });
  ok('rankChunks _score 표제어 가중 4(사전 출신)+본문', byId[1]._score === (2 + 4) + (1 + 4) && byId[4]._score === 1 + 4, [byId[1]._score, byId[4]._score]);
  var many = [];
  for (var i = 0; i < 6; i++) many.push({ id: 10 + i, doc_name: '같은문서', doc_category: '보도자료', content: '휴업 ' + i });
  eq('rankChunks 문서당 상한 3', RC.rankChunks(many, ['휴업'], ['휴업'], '휴업').length, 3);
  var deep = [];
  for (var j = 0; j < 20; j++) deep.push({ id: 100 + j, doc_name: '논문A', doc_category: '추가지식', content: '휴업' });
  eq('rankChunks 추가지식 8·전체 15', RC.rankChunks(deep.concat(many), ['휴업'], ['휴업'], '휴업').length, 8 + 3);
  // 기각 가드(#244): 파일 감점은 분류를 가리지 않는다 — '기타'만으로 좁히면 회의록·보도자료가 조문 자리를 15~21% 가져갔다
  var pair = [
    { id: 201, doc_name: '이슈사례_3G_종료.md', doc_category: '이슈사례', content: '휴업' },
    { id: 202, doc_name: '과기정통부_보도자료_2025.md', doc_category: '보도자료', content: '휴업' },
    { id: 203, doc_name: '어느 공고', doc_category: '기타', content: '휴업' },
  ];
  var p = {}; pair.forEach(function (c) { p[c.id] = c; });   // rankChunks는 배열을 제자리 정렬한다
  RC.rankChunks(pair, ['휴업'], ['휴업'], '휴업');
  ok('rankChunks 파일 감점은 분류 무관(#244 기각안)', p[201]._hybrid_score < p[203]._hybrid_score && p[202]._hybrid_score < p[203]._hybrid_score,
    pair.map(function (c) { return [c.id, c._hybrid_score]; }));
})();

// ── 조문 정밀검색 순수부 ──
eq('titleActWeights', RC.titleActWeights(['종료', '휴업', '직접', '3G'], '3G 종료'), { kwActive: ['종료', '휴업', '3G'], actOf: [5, 7, 5] });
(function () {
  var hits = [
    { id: 1, doc_name: '전기통신사업법(법률)', article_no: '19조(사업의 휴업·폐업)', content: '', _act: 7, _hits: 0, _top: 0 },
    { id: 2, doc_name: '전기통신사업법(법률)', article_no: '19조(사업의 휴업·폐업)', content: '둘째 조각', _act: 7, _hits: 0, _top: 0 },
    { id: 3, doc_name: '선박안전법 시행규칙(해양수산부령)', article_no: '5조(운용 종료 통보)', content: '', _act: 5, _hits: 0, _top: 0 },
    { id: 4, doc_name: '전파법(법률)', article_no: '25조의2(무선국의 폐지)', content: '', _act: 7, _hits: 0, _top: 0 },
    { id: 5, doc_name: '지방세법(법률)', article_no: '3조(신고)', content: '', _act: 0, _hits: 0, _top: 0 },
  ];
  var out = RC.rankLawHits(hits, '기간통신사업 3G 종료 폐지', 5);
  eq('rankLawHits 행위·주제·도메인·위계 정렬 + 같은 조문 대표 1건', out.map(function (h) { return h.id; }), [1, 4, 3, 5]);
  ok('rankLawHits _top 부분문자열(통신사업)', hits[0]._top >= 4, hits[0]._top);
  eq('rankLawHits limit', RC.rankLawHits(hits, '종료', 2).length, 2);
})();

// ── 번호로 지목한 조문 직접 인출(#245) ──
(function () {
  var refs = function (q) {
    return RC.namedArticleRefs(q).map(function (r) {
      var i = r.info ? (r.info.candidates ? r.info.candidates[r.info.candidates.length - 1] : (r.info.subord ? 'subord:' + r.info.subord : 'inherit')) : null;
      return [r.key, i, r.ctx ? r.ctx.candidates[r.ctx.candidates.length - 1] : null];
    });
  };
  eq('namedArticleRefs 법령명+제N조', refs('전파법 제16조'), [['16조', '전파법', null]]);
  eq('namedArticleRefs 시행령만 적으면 앞 법령 이어받기', refs('전파법 제16조와 시행령 제18조는 무엇이 다른가'), [['16조', '전파법', null], ['18조', 'subord:시행령', '전파법']]);
  eq('namedArticleRefs 제 생략(37조)', refs('전기통신사업법 37조 망공동이용은 5G 공동망만 해당하는 건가?'), [['37조', '전기통신사업법', null]]);
  eq('namedArticleRefs 조의N·낫표·항호', refs('「전기통신사업법」 제32조의14제1항제2호'), [['32조의14', '전기통신사업법', null]]);
  eq('namedArticleRefs 이름 없는 번호는 뺌', refs('제16조가 뭐야'), []);
  eq('namedArticleRefs 금액(조 원·조N천억)은 뺌', refs('할당대가 3조 원 규모인데 2조5천억은 전파법 제11조 기준인가'), [['11조', '전파법', null]]);
  // #246-보론(2026-09-27 사내 회신): '제'가 붙은 번호는 금액 거르기를 안 한다 — 종전엔 아래가 모두 빈 배열이었다
  eq('namedArticleRefs 제N조 원문(원≠금액)', refs('전파법 제16조 원문 보여줘'), [['16조', '전파법', null]]);
  eq('namedArticleRefs 제N조 원칙·원인', refs('전파법 제3조 원칙과 전기통신사업법 제50조 원인'), [['3조', '전파법', null], ['50조', '전기통신사업법', '전파법']]);
  eq('namedArticleRefs 제N조만(조사 만)', refs('전파법 제16조만 보면'), [['16조', '전파법', null]]);
  eq('namedArticleRefs 제N조 뒤 금액', refs('전파법 제16조 3천억 원'), [['16조', '전파법', null]]);
  eq('namedArticleRefs 제 없는 N조 원문', refs('전기통신사업법 37조 원문'), [['37조', '전기통신사업법', null]]);
  eq('namedArticleRefs 제 없는 N조 원을(금액)은 뺌', refs('전파법 제16조에 따라 대가 3조 원을 냈다'), [['16조', '전파법', null]]);
  eq('namedArticleRefs 제 없는 N조만(금액과 못 가름)은 뺌', refs('전기통신사업법 37조만 보면'), []);
  eq('namedArticleRefs 나열·동법 이어받기', refs('전파법 제16조, 제17조 및 동법 시행령 제18조'),
    [['16조', '전파법', null], ['17조', null, '전파법'], ['18조', 'subord:시행령', '전파법']]);
  eq('namedArticleRefs 16조 1항(뒤 숫자가 항)', refs('전파법 16조 1항'), [['16조', '전파법', null]]);

  var D = { law: '전파법(법률)(제21065호)(20260102)', dec: '전파법 시행령(대통령령)(제35801호)(20251001)', etc: '전기통신기본법(법률)(제16019호)(20190625)',
    net: '정보통신망 이용촉진 및 정보보호 등에 관한 법률(법률)(제21445호)(20260911)', pdf: '실행계획(안).pdf' };
  var rows = {
    '16조': [{ doc_name: D.etc, article_no: '16조(가)' }, { doc_name: D.law, article_no: '16조(재할당)' }, { doc_name: D.law, article_no: '16조의2(주파수 재할당 대가)' },
             { doc_name: D.dec, article_no: '16조(나)' }, { doc_name: D.pdf, article_no: '16조' }],
    '18조': [{ doc_name: D.dec, article_no: '18조(재할당 신청)' }, { doc_name: D.law, article_no: '18조(다)' }],
    '48조의3': [{ doc_name: D.net, article_no: '48조의3(침해사고의 신고 등)' }],
  };
  var pick = function (q) { return RC.pickNamedArticles(RC.namedArticleRefs(q), rows).map(function (p) { return p.doc_name.split('(')[0] + ' ' + p.key; }); };
  eq('pickNamedArticles 법·시행령 한 질문', pick('전파법 제16조와 시행령 제18조는 무엇이 다른가'), ['전파법 16조', '전파법 시행령 18조']);
  eq('pickNamedArticles 앞 법령 없는 시행령은 안 고름', pick('시행령 제18조 내용'), []);
  eq('pickNamedArticles 약칭(정보통신망법)', pick('정보통신망법 제48조의3 신고 기한'), ['정보통신망 이용촉진 및 정보보호 등에 관한 법률 48조의3']);
  eq('pickNamedArticles 번호를 가진 문서가 없으면 안 고름', pick('전파법 제99조'), []);
  eq('pickNamedArticles 16조의2는 16조로 치지 않음', RC.pickNamedArticles(RC.namedArticleRefs('전파법 제16조'), { '16조': [{ doc_name: D.law, article_no: '16조의2(x)' }] }), []);
  // '개정 전파법(안).pdf'는 문서군 '개정 전파법'이라 이름 끝 일치로 '전파법'에 붙을 수 있다 — 파일 문서 필터가 막는다
  eq('pickNamedArticles 파일 문서 제외', RC.pickNamedArticles(RC.namedArticleRefs('전파법 제16조'), { '16조': [{ doc_name: '개정 전파법(안).pdf', article_no: '16조(재할당)' }] }), []);
})();

// 조회 순서·첫 조각만(통째 보강이 나머지를 합친다)·실패 시 빈 배열 — 비동기라 끝에서 기다린다
var asyncTests = (async function () {
  var calls = [];
  var got = await RC.fetchNamedArticles('전파법 제16조',
    function (k) { calls.push('rows:' + k); return Promise.resolve([{ doc_name: '전파법(법률)(a)(b)', article_no: '16조(재할당)' }]); },
    function (d, k) {
      calls.push('art:' + d.split('(')[0] + ':' + k);
      return Promise.resolve([
        { id: 2, doc_name: d, article_no: '16조(재할당)', chunk_index: 33, content: '뒤' },
        { id: 1, doc_name: d, article_no: '16조(재할당)', chunk_index: 32, content: '제16조(재할당) ①' },
        { id: 3, doc_name: d, article_no: '16조의2(대가)', chunk_index: 34, content: '딴 조' }]);
    });
  eq('fetchNamedArticles 첫 조각 하나·지목 표시', got.map(function (r) { return [r.id, r._named]; }), [[1, true]]);
  eq('fetchNamedArticles 조회 순서', calls, ['rows:16조', 'art:전파법:16조']);
  eq('fetchNamedArticles 조 언급 없으면 조회 안 함', await RC.fetchNamedArticles('주파수 재할당 대가', function () { throw new Error('불림'); }, function () { throw new Error('불림'); }), []);
  eq('fetchNamedArticles 조회 실패는 빈 배열', await RC.fetchNamedArticles('전파법 제16조', function () { return Promise.reject(new Error('x')); }, function () { return []; }), []);
})();

// ── 컨텍스트 문구 ──
(function () {
  var t = RC.buildRagContext([
    { doc_name: '전파법(법률)', doc_category: '법령', article_no: '25조', notice_no: null, effective_date: '2026-01-01', content: '본문', _semantic_score: 0.87 },
    { doc_name: '과기정통부_보도자료', doc_category: '보도자료', effective_date: '2026-09-01', content: '기사' },
  ]);
  ok('buildRagContext 점수 표기 없음', t.indexOf('시맨틱') === -1 && t.indexOf('trgm') === -1);
  ok('buildRagContext 시행일/발표일 구분', t.indexOf('[조항: 25조 | 시행일: 2026-01-01]') >= 0 && t.indexOf('[발표일: 2026-09-01]') >= 0);
  ok('buildRagContext 참조 번호', t.indexOf('[참조 1] 출처: 전파법(법률) (법령)') >= 0 && t.indexOf('[참조 2]') >= 0);
  eq('buildRagContext 빈 입력', RC.buildRagContext([]), '');
  var k = RC.buildKbContext([{ title: '전파법 요약', law_type: '법률', law_number: '제20000호', enforcement_date: '2026-01-01', content: '요약' }]);
  ok('buildKbContext 3문장 지시문', k.indexOf('법의 취지·실무 대응·담당부처를 물을 때 활용하세요') >= 0 && k.indexOf('[법령요약 1] 전파법 요약 [법률 | 법령번호: 제20000호 | 시행일: 2026-01-01]') >= 0);
  eq('buildKbContext 빈 입력', RC.buildKbContext(null), '');
})();

// ── 구조 가드: app.js·rag.ts에 같은 이름을 다시 정의하지 않았나 ──
(function () {
  var files = { 'app.js': path.join(ROOT, 'app.js'), 'rag.ts': path.join(ROOT, 'supabase', 'functions', '_shared', 'rag.ts') };
  Object.keys(files).forEach(function (label) {
    var lines = fs.readFileSync(files[label], 'utf8').split('\n');
    var bad = [];
    lines.forEach(function (l, i) {
      var m = l.match(/^(?:export\s+)?(?:async\s+)?(?:function\s+(\w+)\b|(?:const|let|var)\s+(\w+)\s*=)/);
      if (!m) return;
      var name = m[1] || m[2];
      if (NAMES.indexOf(name) < 0) return;
      if (/=\s*(RagCore|RC)\.\w+\s*;/.test(l)) return;                       // 별칭(var X = RagCore.X;)
      var wraps = lines.slice(i + 1, i + 12).some(function (b) { return b.indexOf('RagCore.' + name + '(') >= 0; });
      if (m[1] && wraps) return;                                              // 위임 래퍼(화면 상태만 얹고 RagCore.X()를 부름)
      bad.push((i + 1) + ': ' + name);
    });
    ok('재정의 없음 ' + label, bad.length === 0, bad);
  });
})();

asyncTests.catch(function (e) { fails++; total++; console.log('FAIL  비동기 검사 예외 ' + (e && e.message)); }).then(function () {
  console.log('\n' + (fails ? 'FAIL ' + fails + '/' + total : 'ALL OK ' + total + '/' + total));
  process.exit(fails ? 1 : 0);
});
