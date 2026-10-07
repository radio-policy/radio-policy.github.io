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
  'rankLawHits', 'NAMED_ARTICLE_MAX', 'namedArticleRefs', 'pickNamedArticles', 'fetchNamedArticles', 'buildRagContext', 'buildKbContext',
  // 자문 빠뜨림 1차 덧붙이기(#283)
  'ADDON_OPTS', 'DELEG_OPTS', 'NEIGHBOR_OPTS', 'NOTICE_DOC_RE', 'unitKey', 'capSpill', 'pickSpill', 'delegationBases', 'pickDelegations',
  'neighborTarget', 'pickNeighbors', 'buildAddOnContext', 'fetchAddOns', 'trimAddOns',
  // 2차(#283-보론2)
  'XREF_OPTS', 'pickXrefs', 'xrefTargets', 'annexWanted', 'annexBlock', 'docDate',
  // 법령 용어 동의어(L5′, #289)
  'LAW_TERM_SYNONYMS', 'LAW_TERM_MAX', 'lawTermKeywords'];
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
// 법령 용어 동의어(L5′, #289) — 기존 두 표 출력 뒤에 붙고, 이 표 출신만 질문당 LAW_TERM_MAX(4)개
eq('L5′ IDC → 집적정보통신시설', RC.lawSynonymKeywords('재난대비 IDC 관련 규정은?'), ['집적정보통신시설']);
eq('L5′ 소문자 idc도', RC.lawSynonymKeywords('idc 보호조치'), ['집적정보통신시설']);
eq('L5′ 데이터 센터(띄어 씀) → 집적정보통신시설', RC.lawSynonymKeywords('데이터 센터 재난 대비'), ['집적정보통신시설']);
eq('L5′ IDC·데이터센터 함께 → 한 번만', RC.lawSynonymKeywords('IDC(데이터센터) 등급'), ['집적정보통신시설']);
eq('L5′ 면허세 → 등록면허세', RC.lawSynonymKeywords('무선국 면허세 납기'), ['등록면허세']);
eq('L5′ 질문에 이미 든 말은 내지 않음(등록면허세 — 사전 출신 가중으로 정밀검색만 흔들지 않게)', RC.lawSynonymKeywords('무선국 등록면허세 감면'), []);
eq('L5′ 질문에 이미 든 말은 내지 않음(집적정보통신시설)', RC.lawSynonymKeywords('IDC 집적정보통신시설 보호지침'), []);
eq('L5′ 기존 표 출력 뒤에 붙음(3G 종료 8개는 그대로 + 1)', RC.lawSynonymKeywords('3G 서비스 종료 때 IDC 이전'),
  ['휴업', '폐업', '폐지', '휴지', '운용휴지', '주파수회수', '주파수할당의 취소', '이용기간', '집적정보통신시설']);
eq('L5′ 기존 표가 이미 낸 말은 이 표 몫에서 뺀다', RC.lawTermKeywords('IDC', ['집적정보통신시설']), []);
eq('L5′ 질문 글귀만 있는 쌍은 없음(장비 세금)', RC.lawSynonymKeywords('이동통신회사가 장비관련해서 내는 세금은 무엇이 있나?'), []);
eq('L5′ 질문 글귀만 있는 쌍은 없음(보관)', RC.lawSynonymKeywords('개인정보 보관 기관에 대한 내용'), []);
(function () {   // 상한·두 글자 표제어 규칙 — 시험용 표로 바꿔 끼워 본다(운영 표엔 두 글자 표제어가 아직 없다)
  var T = RC.LAW_TERM_SYNONYMS, saved = T.splice(0, T.length);
  T.push(['보관', ['보관기간']], ['가나다', ['ㄱ1', 'ㄱ2', 'ㄱ3']], ['라마바', ['ㄴ1', 'ㄴ2']]);
  try {
    eq('L5′ 두 글자 표제어 — 낱말이 같으면', RC.lawTermKeywords('개인정보 보관 기관'), ['보관기간']);
    eq('L5′ 두 글자 표제어 — 조사 뗀 낱말이 같으면', RC.lawTermKeywords('자료를 보관은 어디에'), ['보관기간']);
    eq('L5′ 두 글자 표제어 — 낱말 안에 들어 있기만 하면 안 걸림(정보관리)', RC.lawTermKeywords('정보관리 책임자 지정'), []);
    eq('L5′ 이 표 출신 질문당 4개 상한', RC.lawTermKeywords('가나다 라마바'), ['ㄱ1', 'ㄱ2', 'ㄱ3', 'ㄴ1']);
  } finally { T.splice(0, T.length); saved.forEach(function (x) { T.push(x); }); }
})();
eq('L5′ 시험 뒤 운영 표 복구', RC.LAW_TERM_SYNONYMS.length, 3);
eq('L5′ 개발 20문항엔 이 표가 걸리는 질문 없음(자리 앞·뒤가 결과를 안 바꾸는 근거)',
  JSON.parse(require('fs').readFileSync(require('path').join(__dirname, 'fixtures', 'rag_regression_set.json'), 'utf8')).questions
    .filter(function (q) { return RC.lawTermKeywords(q.question).length; }).map(function (q) { return q.id; }), []);

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
  // Fable 재검토(2026-09-27): '제' 없는 꼴은 법령명이 바로 앞일 때만 — 앞 법령을 이어받으면 「3조 규모」「2조를 넘는다」가 제3조·제2조가 됐다
  eq('namedArticleRefs 제 없는 N조는 앞 법령을 이어받지 않음(3조 규모)', refs('전파법 제11조 기준 할당대가가 3조 규모인데 적정한가'), [['11조', '전파법', null]]);
  eq('namedArticleRefs 제 없는 N조는 앞 법령을 이어받지 않음(2조를)', refs('전기통신사업법 제50조 위반 과징금 2조를 넘는다'), [['50조', '전기통신사업법', null]]);
  eq('namedArticleRefs 「전파법 16조와 17조」의 17조는 잃는다(제17조는 됨)', [refs('전파법 16조와 17조 차이').length, refs('전파법 16조와 제17조 차이').length], [1, 2]);
  // 법령 종류 낱말로 끝나지 않는 이름(「…세부사항」 제9조, 사내 회신) — 약한 이름은 후보로 읽되 이어받을 법령은 되지 않는다
  var wkRefs = RC.namedArticleRefs('주파수할당 신청 절차 및 방법 등 세부사항 제9조와 제10조');
  eq('namedArticleRefs 약한 이름(…세부사항)은 후보로 읽는다(weak 표지, 이어받을 법령은 못 됨 — 제10조는 ctx 없음)', [wkRefs[0].key, wkRefs[0].info.weak, wkRefs[1].key, wkRefs[1].ctx], ['9조', true, '10조', null]);

  var D = { law: '전파법(법률)(제21065호)(20260102)', dec: '전파법 시행령(대통령령)(제35801호)(20251001)', etc: '전기통신기본법(법률)(제16019호)(20190625)',
    net: '정보통신망 이용촉진 및 정보보호 등에 관한 법률(법률)(제21445호)(20260911)', pdf: '실행계획(안).pdf' };
  var rows = {
    '16조': [{ doc_name: D.etc, article_no: '16조(가)' }, { doc_name: D.law, article_no: '16조(재할당)' }, { doc_name: D.law, article_no: '16조의2(주파수 재할당 대가)' },
             { doc_name: D.dec, article_no: '16조(나)' }, { doc_name: D.pdf, article_no: '16조' }],
    '18조': [{ doc_name: D.dec, article_no: '18조(재할당 신청)' }, { doc_name: D.law, article_no: '18조(다)' }],
    '48조의3': [{ doc_name: D.net, article_no: '48조의3(침해사고의 신고 등)' }],
  };
  var pick = function (q) { return RC.pickNamedArticles(RC.namedArticleRefs(q), rows).map(function (p) { return p.doc_name.split('(')[0] + ' ' + p.key; }); };
  var pick2 = function (q, r2) { return RC.pickNamedArticles(RC.namedArticleRefs(q), r2).map(function (p) { return p.doc_name.split('(')[0] + ' ' + p.key; }); };
  eq('pickNamedArticles 법·시행령 한 질문', pick('전파법 제16조와 시행령 제18조는 무엇이 다른가'), ['전파법 16조', '전파법 시행령 18조']);
  eq('pickNamedArticles 앞 법령 없는 시행령은 안 고름', pick('시행령 제18조 내용'), []);
  eq('pickNamedArticles 약칭(정보통신망법)', pick('정보통신망법 제48조의3 신고 기한'), ['정보통신망 이용촉진 및 정보보호 등에 관한 법률 48조의3']);
  eq('pickNamedArticles 번호를 가진 문서가 없으면 안 고름', pick('전파법 제99조'), []);
  eq('pickNamedArticles 16조의2는 16조로 치지 않음', RC.pickNamedArticles(RC.namedArticleRefs('전파법 제16조'), { '16조': [{ doc_name: D.law, article_no: '16조의2(x)' }] }), []);
  // '개정 전파법(안).pdf'는 문서군 '개정 전파법'이라 이름 끝 일치로 '전파법'에 붙을 수 있다 — 파일 문서 필터가 막는다
  eq('pickNamedArticles 파일 문서 제외', RC.pickNamedArticles(RC.namedArticleRefs('전파법 제16조'), { '16조': [{ doc_name: '개정 전파법(안).pdf', article_no: '16조(재할당)' }] }), []);
  var gosiSD = '주파수할당 신청 절차 및 방법 등 세부사항(과학기술정보통신부고시)(제2025-10호)(20250301)';
  eq('pickNamedArticles 약한 이름(…세부사항 제9조) → 그 고시(전파법 제9조 아님)', pick2('주파수할당 신청 절차 및 방법 등 세부사항 제9조 실제매출액', { '9조': [{ doc_name: D.law, article_no: '9조(주파수분배)' }, { doc_name: gosiSD, article_no: '9조(실제매출액)' }] }), ['주파수할당 신청 절차 및 방법 등 세부사항 9조']);
  eq('pickNamedArticles 약한 이름을 못 맞추고 앞 법령도 없으면 안 고름', pick2('산정 방식 제9조', { '9조': [{ doc_name: D.law, article_no: '9조(주파수분배)' }, { doc_name: gosiSD, article_no: '9조(실제매출액)' }] }), []);
  // 약칭은 법률에만(#240·#246): 단통법은 폐지돼 현행 문서가 없다 — 그 법률 이름을 담은 고시의 제4조에 붙지 않는다(사내 회신)
  eq('pickNamedArticles 약칭(단통법)이 고시에 붙지 않음', pick2('단통법 제4조 과징금', { '4조': [{ doc_name: '이동통신단말장치 유통구조 개선에 관한 법률 위반 과징금 부과 세부기준(방송미디어통신위원회고시)(제2026-1호)(20260101)', article_no: '4조(과징금 산정)' }] }), []);
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

// ── 자문 빠뜨림 1차 덧붙이기(#283) — 상한 구제·위임 따라가기·같은 고시 이웃 조 ──
(function () {
  eq('unitKey 조·별표·그 밖', [RC.unitKey('16조의2(대가)'), RC.unitKey('별표 13(제96조 관련)'), RC.unitKey('부칙'), RC.unitKey(null)], ['16조의2', '별표13', null, null]);
  // capSpill: rankChunks와 같은 순서로 훑어 15칸이 차기 전 문서당 상한(3)으로만 빠진 조문·별표. 파일 문서·부칙은 뺀다.
  var D = '전파법 시행령(대통령령)(제1호)(20250101)', F = '논문.pdf';
  var rs = [];
  for (var i = 0; i < 5; i++) rs.push({ id: i + 1, doc_name: D, article_no: (95 + i) + '조(수수료)', _hybrid_score: 1 - i * 0.01 });
  rs.push({ id: 10, doc_name: D, article_no: '부칙', _hybrid_score: 0.5 });
  for (var j = 0; j < 4; j++) rs.push({ id: 20 + j, doc_name: F, article_no: '3조(x)', _hybrid_score: 0.4 - j * 0.01 });
  eq('capSpill 상한으로만 빠진 조문(파일·부칙 제외)', RC.capSpill(rs).map(function (r) { return r.id; }), [4, 5]);
  // rankChunks 결과는 그대로(계약 불변) — 같은 입력에서 채택분과 상한 구제 후보가 겹치지 않는다
  var rs2 = rs.map(function (r) { return Object.assign({}, r, { content: '' }); });
  var picked = RC.rankChunks(rs2, [], [], '');
  ok('capSpill과 rankChunks 채택분이 겹치지 않음', RC.capSpill(rs2).every(function (r) { return picked.indexOf(r) < 0; }));
  // 15칸이 다 찬 뒤의 조각은 후보가 아니다
  var many = [];
  for (var k = 0; k < 20; k++) many.push({ id: 100 + k, doc_name: '법' + k + '(법률)(a)(b)', article_no: '1조(x)', _hybrid_score: 1 - k * 0.01 });
  many.push({ id: 999, doc_name: '법0(법률)(a)(b)', article_no: '2조(x)', _hybrid_score: 0.01 });
  many.push({ id: 998, doc_name: '법0(법률)(a)(b)', article_no: '3조(x)', _hybrid_score: 0.005 });
  many.push({ id: 997, doc_name: '법0(법률)(a)(b)', article_no: '4조(x)', _hybrid_score: 0.001 });
  eq('capSpill 15칸이 찬 뒤는 후보 아님', RC.capSpill(many), []);
  // pickSpill: 이미 든 조각 id·같은 단위 제외, 자기끼리도 한 번, 상한
  var cands = [{ id: 4, doc_name: D, article_no: '98조(a)' }, { id: 7, doc_name: D, article_no: '98조(a)' }, { id: 5, doc_name: D, article_no: '99조(b)' },
    { id: 6, doc_name: D, article_no: '96조(c)' }, { id: 8, doc_name: D, article_no: '별표 13(d)' }];
  eq('pickSpill 이미 든 단위 제외·중복 제외·상한', RC.pickSpill(cands, [{ id: 5, doc_name: D, article_no: '97조(z)' }, { id: 9, doc_name: D, article_no: '96조(c)' }], 2).map(function (r) { return r.id; }), [4, 8]);
})();

(function () {
  var L = '전파법(법률)(제1호)(20260102)', R = '전파법 시행령(대통령령)(제2호)(20251001)', N = '재난문자방송 기준 및 운영규정(행정안전부예규)(제3호)(20250101)';
  var bases = RC.delegationBases([[{ doc_name: L, article_no: '24조(검사)' }, { doc_name: 'x.pdf', article_no: '24조' }],
    [{ doc_name: R, article_no: '별표 13(a)' }, { doc_name: L, article_no: '24조(검사)' }, { doc_name: N, article_no: '5조(송출)' }]]);
  eq('delegationBases 순서·조만·파일 제외·중복 제외', bases.map(function (b) { return [b.fam, b.key, b.notice]; }),
    [['전파법', '24조', false], ['재난문자방송 기준 및 운영규정', '5조', true]]);
  var rows = [
    { parent_law: '전파법', parent_article: '24조', child_law: '전파법 시행령', child_article: '45조', child_title: '검사의 시기', child_kind: '시행령' },
    { parent_law: '전파법', parent_article: '24조', child_law: '전파법 시행령', child_article: '44조', child_title: '정기검사의 유효기간', child_kind: '시행령' },
    { parent_law: '전파법', parent_article: '24조', child_law: '전파법 시행규칙', child_article: '10조', child_title: '검사 신청', child_kind: '시행규칙' },
    { parent_law: '전파법', parent_article: '24조', child_law: '전파법 시행령', child_article: '2조', child_title: '정의', child_kind: '시행령' },
    { parent_law: '전파법', parent_article: '24조', child_law: '무선국 검사업무 처리기준', child_article: '전체', child_kind: '고시' },
    { parent_law: '재난 및 안전관리 기본법 시행령', parent_article: '46조의2', child_law: '재난문자방송 기준 및 운영규정', child_article: '전체', child_kind: '예규' },
    { parent_law: '재난 및 안전관리 기본법', parent_article: '38조의2', child_law: '재난문자방송 기준 및 운영규정', child_article: '전체', child_kind: '예규' },
    { parent_law: '전파법', parent_article: '69조', parent_title: '수수료', child_law: '전파법', child_article: '24조', child_kind: '시행령' },
  ];
  var pd = RC.pickDelegations(bases, rows, new Set(['전파법 시행령|44조']), { perBase: 2, down: 4, up: 4, spare: 0 });
  eq('pickDelegations 아래: 이미 든 조·정의·고시 전체 제외, 시행령 먼저·번호 순, 근거당 2', pd.down.map(function (x) { return x.fam + ' ' + x.key; }),
    ['전파법 시행령 45조', '전파법 시행규칙 10조']);
  eq('pickDelegations 위: 법률 먼저, 고시 조면 그 고시 전체 행의 부모', pd.up.map(function (x) { return x.fam + ' ' + x.key + (x.whole ? ' (전체)' : ''); }),
    ['전파법 69조', '재난 및 안전관리 기본법 38조의2 (전체)', '재난 및 안전관리 기본법 시행령 46조의2 (전체)']);
  var pd1 = RC.pickDelegations(bases, rows, new Set(), { perBase: 2, down: 1, up: 4, spare: 1 });
  eq('pickDelegations 방향 상한 + 예비 후보', pd1.down.length, 2);

  var nt = RC.neighborTarget([[{ doc_name: N, article_no: '5조(a)' }, { doc_name: N, article_no: '5조(a)' }, { doc_name: L, article_no: '1조' }],
    [{ doc_name: N, article_no: '12조(b)' }]]);
  eq('neighborTarget 고시에 서로 다른 조 2개 이상', nt, { doc_name: N, keys: ['5조', '12조'] });
  eq('neighborTarget 1개뿐이면 없음', RC.neighborTarget([[{ doc_name: N, article_no: '5조(a)' }, { doc_name: L, article_no: '1조' }, { doc_name: L, article_no: '2조' }]]), null);
  var doc = [];
  ['1조(목적)', '4조(a)', '5조(a)', '6조(b)', '6조의2(c)', '7조(준용)', '11조(d)', '12조(e)', '13조(f)'].forEach(function (a, i) {
    doc.push({ id: 500 + i, doc_name: N, article_no: a, chunk_index: i, content: a + ' 본문' });
  });
  doc.push({ id: 600, doc_name: N, article_no: '별표 1(x)', chunk_index: 20, content: '표' });
  eq('pickNeighbors 작으면 남은 조 전부(별표 제외)', RC.pickNeighbors(doc, ['5조', '12조'], { wholeChars: 6000, max: 4 }).map(function (x) { return x.key; }),
    ['1조', '4조', '6조', '6조의2', '7조', '11조', '13조']);
  eq('pickNeighbors 크면 문서 순서상 앞뒤 조·준용 조만, max', RC.pickNeighbors(doc, ['5조', '12조'], { wholeChars: 10, max: 4 }).map(function (x) { return x.key; }),
    ['4조', '6조', '7조', '11조']);
})();

var addOnTests = (async function () {
  var L = '전파법(법률)(제1호)(20260102)', R = '전파법 시행령(대통령령)(제2호)(20251001)', R0 = '전파법 시행령(대통령령)(제1호)(20240101)';
  var calls = [];
  var fetchers = {
    delegations: function (fams, keys) {
      calls.push('deleg:' + fams.join('/') + ':' + keys.join('/'));
      return Promise.resolve([
        { parent_law: '전파법', parent_article: '24조', child_law: '전파법 시행령', child_article: '44조', child_title: '정기검사의 유효기간', child_kind: '시행령' },
        { parent_law: '전파법', parent_article: '24조', child_law: '전파법 시행령', child_article: '99조', child_title: '없는 조', child_kind: '시행령' },
        { parent_law: '전파법', parent_article: '24조', child_law: '전파법 시행령', child_article: '45조', child_title: '검사의 시기', child_kind: '시행령' }]);
    },
    familyArticle: function (fam, key) {
      calls.push('art:' + fam + ':' + key);
      if (key === '99조') return Promise.resolve([]);   // 위임 표가 낡음 — 현행 문서에 없음
      if (key === '45조') return Promise.reject(new Error('x'));
      return Promise.resolve([
        { id: 71, doc_name: R, article_no: '44조(정기검사의 유효기간)', chunk_index: 2, content: '② 별표 13에 따른다.' },
        { id: 70, doc_name: R, article_no: '44조(정기검사의 유효기간)', chunk_index: 1, content: '제44조(정기검사의 유효기간) ①' },
        { id: 72, doc_name: R, article_no: '44조(정기검사의 유효기간)', chunk_index: 3, content: '③ 셋째' },
        { id: 60, doc_name: R0, article_no: '44조(옛판)', chunk_index: 1, content: '옛 판' },
        { id: 61, doc_name: R, article_no: '44조의2(딴 조)', chunk_index: 4, content: '딴 조' }]);
    },
    docArticles: function () { calls.push('doc'); return Promise.resolve([]); },
  };
  var r = await RC.fetchAddOns({ extra: [{ id: 1, doc_name: L, article_no: '24조(검사)', content: '제24조' }], spill: [], rag: [{ id: 2, doc_name: 'a.pdf', article_no: '3조', content: 'x' }] }, fetchers, { deleg: { perBase: 3 } });
  eq('fetchAddOns 조회 순서(고시 없으면 문서 조회 안 함)', calls, ['deleg:전파법:24조', 'art:전파법 시행령:44조', 'art:전파법 시행령:45조', 'art:전파법 시행령:99조']);
  eq('fetchAddOns 없는 조·조회 실패는 건너뜀, 최신 판 앞 2조각', r.ids, [70, 71]);
  eq('fetchAddOns 항목 기록', r.items, [{ sec: 'deleg', dir: 'down', fam: '전파법 시행령', key: '44조' }]);
  ok('fetchAddOns 구역 머리·위임 꼬리·잘림 표시', r.text.indexOf('[위임 관계로 이어진 조문') >= 0 && r.text.indexOf('[위임 1] ' + R + ' 44조(정기검사의 유효기간) — 전파법 제24조의 위임을 받은 조문') >= 0
    && r.text.indexOf('전체 3조각 중 앞 2조각만') >= 0 && r.text.indexOf('옛 판') < 0, r.text);
  eq('fetchAddOns 별표 동반 입력(deleg)·별표 인용', [r.deleg.map(function (c) { return c.id; }), r.annexCites], [[70], ['전파법 시행령 별표 13']]);
  var r2 = await RC.fetchAddOns({ extra: [{ id: 1, doc_name: L, article_no: '24조(검사)' }] }, {
    delegations: function () { return Promise.reject(new Error('표 없음')); }, familyArticle: function () { throw new Error('불림'); }, docArticles: function () { return []; } });
  eq('fetchAddOns 위임 표 조회 실패 → 빈 결과(지금과 같음)', [r2.text, r2.ids], ['', []]);
  var r3 = await RC.fetchAddOns({ extra: [{ id: 1, doc_name: L, article_no: '24조(검사)' }] }, fetchers, { budget: 10 });
  eq('fetchAddOns 예산을 넘는 항목은 넣지 않음', r3.text, '');
  // trimAddOns: 전체 상한을 넘으면 같은 고시 → 위 → 아래 순으로 뒤에서 덜어 다시 묶는다
  var mk = function (dir, key) { return { dir: dir, fam: '전파법 시행령', key: key, base: { fam: '전파법', key: '24조' }, doc_name: R, article_no: key + '(x)', content: 'x'.repeat(100), ids: [Number(key.replace(/\D/g, ''))] }; };
  var nb = { doc_name: '어느 고시(과학기술정보통신부고시)(제1호)(20260101)', article_no: '3조(y)', key: '3조', content: 'y'.repeat(100), ids: [903] };
  var full = { text: '', parts: null };
  full = RC.trimAddOns(Object.assign({}, full), 0, 1);   // text 없으면 그대로
  eq('trimAddOns 빈 결과는 그대로', full.text, '');
  var whole = await RC.fetchAddOns({ extra: [{ id: 1, doc_name: L, article_no: '24조(검사)' }] }, fetchers, { deleg: { perBase: 3 } });
  eq('trimAddOns 상한 안이면 그대로(같은 객체)', RC.trimAddOns(whole, 0, 1e9) === whole, true);
  var t1 = RC.trimAddOns(whole, 0, 10);
  eq('trimAddOns 상한을 못 맞추면 덧붙인 것을 모두 덜어 냄', [t1.text, t1.ids, t1.trimmed], ['', [], 1]);
  ok('trimAddOns 덜어 낸 결과에 parts 유지', !!(t1.parts && t1.parts.deleg));
  var packed = RC.trimAddOns({ text: 'z'.repeat(999), parts: { deleg: [mk('down', '44조'), mk('up', '45조')], neighbor: [nb], spillItems: [] } }, 0, 400);
  eq('trimAddOns 같은 고시 → 위 순으로 덜어 냄', [packed.items.map(function (x) { return x.sec + '/' + (x.dir || '') + x.key; }), packed.ids, packed.trimmed], [['deleg/down44조'], [44], 2]);
})();

// ── 자문 빠뜨림 2차(#283-보론2) — 형제 순서·공통 인용(L3′)·덧붙인 조문의 별표 1칸·채우는/덜어 내는 순서 ──
(function () {
  var L = '전파법(법률)(제1호)(20260102)', R = '전파법 시행령(대통령령)(제2호)(20251001)';
  eq('docDate 문서명 끝 8자리', [RC.docDate(R), RC.docDate('x.pdf')], [20251001, 0]);

  // xrefTargets — 같은 법령 인용 · 다른 법령 인용 거르기(isOtherLawRef) · 시행령의 「법 제N조」→ 모법 · 시행규칙의 「영 제N조」→ 시행령
  var t = function (fam, content) { return RC.xrefTargets({ content: content }, fam).map(function (x) { return x.fam + ' ' + x.key; }); };
  eq('xrefTargets 같은 법령·자기 조 머리', t('전파법', '제24조(검사) ① 제19조에 따라 허가를 받은 자는 제21조의2를 따른다.'), ['전파법 24조', '전파법 19조', '전파법 21조의2']);
  eq('xrefTargets 다른 법령(낫표·같은 법·법령명)은 뺀다', t('전파법', '「전기통신사업법」 제5조, 같은 법 제6조, 방송법 제7조 및 이 법 제8조'), ['전파법 8조']);
  eq('xrefTargets 시행령의 「법 제N조」는 모법, 나열 뒤도', t('전파법 시행령', '법 제89조의2, 제89조의3 및 제90조에 따라 이 영 제5조를 적용한다.'),
    ['전파법 89조의2', '전파법 89조의3', '전파법 90조', '전파법 시행령 5조']);
  eq('xrefTargets 시행령의 「같은 법 제N조」는 앞 법령 — 모법으로 옮기지 않음', t('전파법 시행령', '「전기통신사업법」 제2조 및 같은 법 제6조'), []);
  eq('xrefTargets 시행규칙의 「영 제N조」→ 시행령, 「법 제N조」→ 모법', t('전파법 시행규칙', '영 제14조와 법 제16조에 따라'), ['전파법 시행령 14조', '전파법 16조']);
  eq('xrefTargets 법률 본문의 「법 제N조」는 다른 법령으로 둔다', t('전파법', '법 제3조'), []);

  // pickXrefs — 서로 다른 근거 2곳 이상, 가리킨 곳 수 ↓ → 앞선 근거, 이미 든 조·위임 고른 조·자기 자신·정의 조 출발 제외
  var lists = [[{ doc_name: L, article_no: '24조(검사)', content: '제24조(검사) 제19조·제20조·제30조' }],
    [{ doc_name: R, article_no: '44조(유효기간)', content: '법 제19조 및 법 제30조, 이 영 제50조' }],
    [{ doc_name: L, article_no: '25조(x)', content: '제19조, 제20조, 제24조' }, { doc_name: L, article_no: '2조(정의)', content: '제30조 제50조' },
     { doc_name: R, article_no: '46조(y)', content: '제50조' }, { doc_name: 'a.pdf', article_no: '1조', content: '제30조' }]];
  var present = new Set(['전파법|24조', '전파법 시행령|44조', '전파법|25조', '전파법|2조', '전파법 시행령|46조']);
  var px = RC.pickXrefs(lists, present, { '전파법|20조': 1 }, { max: 5, spare: 0 });
  eq('pickXrefs 2곳 이상·곳 수 순·제외 규칙', px.map(function (x) { return x.fam + ' ' + x.key + ' ' + x.bases.length; }), ['전파법 19조 3', '전파법 30조 2', '전파법 시행령 50조 2']);
  eq('pickXrefs 같은 법령 인용은 근거 문서명을 대상 문서로', [px[0].doc, px[2].doc], [L, R]);
  eq('pickXrefs max', RC.pickXrefs(lists, present, {}, { max: 1, spare: 0 }).length, 1);

  // annexWanted / annexBlock — 별표 동반(#90)과 같은 규칙·꼴
  eq('annexWanted 다른 법령 별표·별표 조각 제외·중복 제외', RC.annexWanted([{ doc_name: R, article_no: '96조', content: '별표 13에 따른다. 「전기통신사업법 시행령」 별표 4 및 별표 13' },
    { doc_name: R, article_no: '별표 2(x)', content: '별표 9' }, { doc_name: L, article_no: '5조', content: '별표 제2' }]), [{ doc_name: R, no: '13' }, { doc_name: L, no: '2' }]);
  var arows = [];
  for (var i = 0; i < 9; i++) arows.push({ id: 900 + i, chunk_index: i, article_no: '별표 13(검사수수료(제96조제1항 관련))', content: i === 0 ? '표 머리' : (i === 7 ? '변경신고 수수료' : '칸' + i) });
  var blk = RC.annexBlock(R, '13', arows, '무선국 변경신고 수수료');
  ok('annexBlock 첫 조각·질문 낱말 조각·생략 표시·출처', blk.ids[0] === 900 && blk.ids.indexOf(907) >= 0 && blk.ids.length === RC.ANNEX_MAX_CHUNKS
    && blk.text.indexOf('[' + R + ' 별표 13(검사수수료(제96조제1항 관련))]\n※ 이 별표는 전체 9개 조각 중') === 0 && blk.source === '전파법 시행령 별표 13', blk);
  eq('annexBlock 빈 입력', RC.annexBlock(R, '13', [], 'x'), null);
})();

var addOnTests2 = (async function () {
  var L = '전파법(법률)(제1호)(20260102)', R9 = '전파법 시행령(대통령령)(제9999호)(20240101)', R10 = '전파법 시행령(대통령령)(제10000호)(20250101)';
  var calls = [];
  var fetchers = {
    delegations: function () { return Promise.resolve([
      { parent_law: '전파법', parent_article: '24조', child_law: '전파법 시행령', child_article: '44조', child_title: 'a', child_kind: '시행령' }]); },
    familyDocs: function (fams) { calls.push('docs:' + fams.join('/')); return Promise.resolve([{ law_name: '전파법 시행령', doc_name: R10 }]); },
    familyArticle: function (fam, key, doc) {
      calls.push('art:' + fam + ':' + key + ':' + (doc || '-'));
      if (fam === '전파법 시행령') return Promise.resolve([
        { id: 61, doc_name: R9, article_no: key + '(옛)', chunk_index: 1, content: '옛 판' },
        { id: 62, doc_name: R10, article_no: key + '(새)', chunk_index: 1, content: '제' + key + ' 별표 13에 따른다.' }]);
      return Promise.resolve([{ id: 70 + Number(key.replace(/\D/g, '')), doc_name: L, article_no: key + '(x)', chunk_index: 1, content: '제' + key + ' 본문' }]);
    },
    docArticles: function () { return Promise.resolve([]); },
    annexRows: function (doc, no) { calls.push('annex:' + no); return Promise.resolve([{ id: 800, chunk_index: 0, article_no: '별표 ' + no + '(수수료)', content: 'x'.repeat(50) }]); },
  };
  var lists = { extra: [{ id: 1, doc_name: L, article_no: '24조(검사)', content: '제19조 및 제22조' }],
    rag: [{ id: 2, doc_name: L, article_no: '25조(x)', content: '제19조와 제22조, 별표 5' }] };
  var r = await RC.fetchAddOns(lists, fetchers, { question: '수수료' });
  ok('fetchAddOns 문서명 모르는 법령군만 한 번에 받아 그 문서로 조회, 같은 법령 인용은 근거 문서', calls.indexOf('docs:전파법 시행령') >= 0 && calls.indexOf('art:전파법 시행령:44조:' + R10) >= 0
    && calls.indexOf('art:전파법:19조:' + L) >= 0, calls);
  eq('fetchAddOns 시행일이 늦은 판(문자열로는 제9999호가 뒤)', r.parts.deleg[0].doc_name, R10);
  eq('fetchAddOns 항목 — 위임·공통 인용·별표', r.items.map(function (x) { return x.sec + ':' + x.key; }), ['deleg:44조', 'xref:19조', 'xref:22조', 'annex:별표13']);
  ok('fetchAddOns 공통 인용 구역 머리·꼬리', r.text.indexOf('[위 조문 여러 곳이 함께 가리키는 조문') >= 0 && r.text.indexOf('[공통 인용 1] ' + L + ' 19조(x) — 위 전파법 제24조·전파법 제25조에서 가리킨 조문') >= 0, r.text);
  ok('fetchAddOns 별표 구역은 맨 끝·출처·조각 id', /\[위에 덧붙인 조문이 가리키는 별표 원문\][\s\S]*\[전파법 시행령\(대통령령\)\(제10000호\)\(20250101\) 별표 13\(수수료\)\]/.test(r.text)
    && r.annexSources[0] === '전파법 시행령 별표 13' && r.ids.indexOf(800) >= 0, r);
  // 종전 별표 2칸(RAG → 정밀검색 순 앞 두 개)에 든 별표는 덧붙인 별표 칸에서 뺀다
  calls = [];
  var r2 = await RC.fetchAddOns({ extra: lists.extra, rag: [{ id: 2, doc_name: R10, article_no: '30조(y)', content: '별표 13' }] }, fetchers, {});
  ok('fetchAddOns 종전 별표 칸에 든 별표는 다시 싣지 않음', calls.every(function (c) { return c.indexOf('annex:') !== 0; }) && !r2.parts.annex, calls);
  var r3 = await RC.fetchAddOns(lists, fetchers, { annex: false });
  eq('fetchAddOns annex:false면 별표 칸 없음', r3.items.filter(function (x) { return x.sec === 'annex'; }).length, 0);
  var r4 = await RC.fetchAddOns(lists, { delegations: fetchers.delegations, familyArticle: fetchers.familyArticle, docArticles: fetchers.docArticles }, {});
  eq('fetchAddOns familyDocs·annexRows 없으면 문서명 없이 조회·별표 칸 없음(사내판 조회 shim 그대로 돈다)', [r4.parts.deleg.length, !!r4.parts.annex], [1, false]);
  // 예산 순서 — fillOrder에서 별표를 공통 인용보다 앞에 두면 예산이 작을 때 별표가 먼저 들어간다
  var small = await RC.fetchAddOns(lists, fetchers, { budget: 250, fillOrder: ['down', 'up', 'annex', 'xref', 'neighbor'] });
  var small2 = await RC.fetchAddOns(lists, fetchers, { budget: 250, fillOrder: ['down', 'up', 'xref', 'annex', 'neighbor'] });
  eq('fetchAddOns fillOrder — 예산이 모자라면 순서가 앞선 것만', [small.items.map(function (x) { return x.sec; }), small2.items.map(function (x) { return x.sec; })], [['deleg', 'annex'], ['deleg', 'xref']]);
  // trimAddOns — 별표 → 같은 고시 → 공통 인용 → 위 → 아래
  var mk = function (sec, dir, key) { return { sec: sec, dir: dir, fam: '전파법', key: key, base: { fam: '전파법', key: '24조' }, bases: ['전파법|1조', '전파법|2조'], doc_name: L, article_no: key + '(x)', content: 'x'.repeat(100), ids: [Number(key.replace(/\D/g, ''))] }; };
  var full = { text: 'z'.repeat(2000), parts: { deleg: [mk(undefined, 'down', '1조'), mk(undefined, 'up', '2조')], xref: [mk('xref', undefined, '3조')],
    neighbor: [{ doc_name: '어느 고시(과학기술정보통신부고시)(제1호)(20260101)', article_no: '4조(y)', key: '4조', content: 'y'.repeat(100), ids: [4] }],
    annex: { doc_name: L, key: '별표5', no: '5', article_no: '별표 5(z)', content: 'w', text: 'w'.repeat(600), ids: [5], source: '전파법 별표 5' }, spillItems: [] } };
  var t1 = RC.trimAddOns(full, 0, 1200);
  eq('trimAddOns 별표부터 덜어 냄', [t1.items.map(function (x) { return x.sec + (x.dir ? '/' + x.dir : ''); }), t1.trimmed], [['deleg/down', 'deleg/up', 'xref', 'neighbor'], 1]);
  var t2 = RC.trimAddOns(full, 0, 400);
  eq('trimAddOns 별표 → 같은 고시 → 공통 인용 → 위 순', [t2.items.map(function (x) { return x.sec + (x.dir ? '/' + x.dir : ''); }), t2.trimmed], [['deleg/down'], 4]);
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

// ── 대시보드 전체 상한(#283-보론2, 운영자 결정 10-06) — app.js만 maxTotalChars + dashboardExtraChars로 덜어 낸다, rag.ts는 기본 상한 ──
(function () {
  var app = fs.readFileSync(path.join(ROOT, 'app.js'), 'utf8');
  var ragTs = fs.readFileSync(path.join(ROOT, 'supabase', 'functions', '_shared', 'rag.ts'), 'utf8');
  ok('app.js trimAddOns에 대시보드 몫', app.indexOf('RagCore.trimAddOns(await addOnsP, restLen, RagCore.ADDON_OPTS.maxTotalChars + RagCore.ADDON_OPTS.dashboardExtraChars)') >= 0);
  ok('rag.ts trimAddOns는 기본 상한(봇)', /RagCore\.trimAddOns\(await addOnsP, restLen\);/.test(ragTs));
  eq('ADDON_OPTS 대시보드 몫 8,000자', RC.ADDON_OPTS.dashboardExtraChars, 8000);
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

Promise.all([asyncTests, addOnTests, addOnTests2]).catch(function (e) { fails++; total++; console.log('FAIL  비동기 검사 예외 ' + (e && e.message)); }).then(function () {
  console.log('\n' + (fails ? 'FAIL ' + fails + '/' + total : 'ALL OK ' + total + '/' + total));
  process.exit(fails ? 1 : 0);
});
