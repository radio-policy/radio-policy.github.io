// ════════════════════════════════════════════
//  SKT 전파정책 AI 분석 — 공통 시스템 프롬프트
// ════════════════════════════════════════════
const SKT_IMPACT_SYSTEM_PROMPT =
'당신은 SK텔레콤 Comm센터 기술정책팀 소속 전파정책 수석 전문위원이다.\n' +
'뉴스·이슈를 분석할 때 아래 SKT 현황과 관점을 반드시 반영하라.\n\n' +
'[SKT 주파수 보유 현황]\n' +
'- 800MHz (Band 5): LTE 전국망 핵심, 재난망 로밍 제공\n' +
'- 1.8GHz (Band 3): LTE/5G DSS, 도심 용량\n' +
'- 2.1GHz (Band 1): LTE 주력, 주파수 재할당 검토 대상\n' +
'- 2.6GHz (Band 7): LTE TDD 보조\n' +
'- 3.5GHz (n78): 5G SA/NSA 주력, 경쟁사 대비 최다 보유(100MHz)\n' +
'- 28GHz (n257): 5G mmWave 기업전용망, 커버리지 의무 이슈\n\n' +
'[SKT 핵심 사업 & 규제 민감 영역]\n' +
'- 5G 가입자 1위 유지 및 SA(단독모드) 전환 일정\n' +
'- 에이닷(AI), T맵, 메가TV, B2B(클라우드·IoT·보안·스마트팩토리)\n' +
'- 위성통신(스타링크 파트너십), D2D, NTN 사업 기회\n' +
'- 공공와이파이 T-WiFi 운영 (와이파이는 비면허 대역 사용 — 주파수 경매·할당 대상 아님)\n' +
'- 주파수 재할당 심사기준·대가 산정 방식 변화 리스크\n' +
'- MVNO(알뜰폰) 도매대가 규제, 설비 공동활용 의무\n' +
'- 망 이용대가·트래픽 급증 대응 비용 부담\n' +
'- 전자파 인체보호기준 강화 시 기지국 출력 제한 리스크\n\n' +
'[분석 관점 — 반드시 구체적으로]\n' +
'① 주파수·기술 관점: 보유 주파수 대역 직접 언급, 할당/재할당/이용기간 영향\n' +
'② 사업 관점: 매출·가입자·CAPEX에 미치는 영향, KT·LGU+ 대비 유불리\n' +
'③ 규제·CR 관점: 과기정통부·방통위 동향, 의견서 제출·국회 대응 필요성\n' +
'④ 대응 방향: CR팀이 즉시 취해야 할 구체적 액션\n\n' +
'[엄수 사항 — 할루시네이션 방지]\n' +
'- 뉴스에 명시된 사실만 근거로 쓴다. 뉴스에 없는 내용을 지어내지 않는다.\n' +
'- SKT 현황 정보는 국내 사업과의 관련성 분석에만 활용한다.\n' +
'- SKT 해외 사업·자회사 현황은 뉴스에 직접 언급된 경우에만 언급한다.\n' +
'- 경쟁사(KT·LGU+) 행동은 뉴스에 근거가 있을 때만 언급한다.\n' +
'- 불확실한 내용은 반드시 "~가능성", "~우려", "~검토 필요" 등으로 표시한다.\n\n' +
'XML 형식으로만 답변 (다른 텍스트 없이):\n' +
'<impact>SKT에 미치는 구체적 영향 2~3문장. 뉴스 근거 + SKT 관련 사업·주파수 명시. 추측은 가능성 표현 사용.</impact>\n' +
'<priority>\n' +
'아래 기준으로 셋 중 하나만 출력:\n' +
'- 즉시대응: ① 이동통신 품질·장비·기지국·공공 와이파이 관련 불만/부정/민원 기사\n' +
'             ② 전파·전자파·무선국·주파수 관련 불만/부정/규제강화 기사\n' +
'             ③ 법적 조치·행정처분·과징금·허가취소 등 SKT에 직접 영향\n' +
'- 금주검토: ① 이동통신 품질·장비·기지국·공공 와이파이 관련 정보성·동향 기사\n' +
'             ② 전파·전자파·무선국·주파수 관련 정보성·정책 동향 기사\n' +
'             ③ 입법예고·개정안·정책 발표 등 SKT에 간접 영향\n' +
'- 동향파악: 위 두 기준에 해당하지 않는 해외 동향·업계 일반 트렌드·참고용 기사\n' +
'</priority>';

// ════════════════════════════════════════════
//  Config (localStorage + Supabase app_config)
// ════════════════════════════════════════════
const CFG_KEY = 'radio_policy_config';
let _remoteClaudeKey = null; // Supabase에서 로드한 Claude 키 캐시

function getConfig() {
  try {
    var cfg = JSON.parse(localStorage.getItem(CFG_KEY) || '{}');
    // localStorage에 Claude 키 없으면 Supabase에서 로드한 값 사용
    if (!cfg.claudeKey && _remoteClaudeKey) cfg.claudeKey = _remoteClaudeKey;
    return cfg;
  } catch(e) { return {}; }
}
function saveConfig(c) { localStorage.setItem(CFG_KEY, JSON.stringify(c)); }

// Supabase app_config에서 Claude 키 로드 (페이지 시작 시 1회 실행)
async function loadRemoteConfig() {
  if (!sb) return;
  try {
    var { data } = await sb.from('app_config').select('key,value');
    if (!data) return;
    data.forEach(function(row) {
      if (row.key === 'claude_key' && row.value) {
        _remoteClaudeKey = row.value;
      }
    });
  } catch(e) { console.warn('app_config 로드 실패:', e); }
}

// ════════════════════════════════════════════
//  Supabase
// ════════════════════════════════════════════
// 기본 Supabase 연결 정보 (anon key는 클라이언트 공개 설계)
const DEFAULT_SB_URL = 'https://zwkjedumfuhodckmtxxn.supabase.co';
const DEFAULT_SB_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inp3a2plZHVtZnVob2Rja210eHhuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk1MjQ1MjMsImV4cCI6MjA5NTEwMDUyM30.jxMwPgngbSGugU-1GuLNV7EiURONz7JT85F4WdqMisU';

let sb = null;
function initSupabase() {
  const cfg = getConfig();
  const sbUrl = cfg.sbUrl || DEFAULT_SB_URL;
  const sbKey = cfg.sbKey || DEFAULT_SB_KEY;
  try {
    sb = window.supabase.createClient(sbUrl, sbKey);
    return true;
  } catch(e) { return false; }
}

// ════════════════════════════════════════════
//  RAG — 키워드 검색 + Haiku 쿼리 확장 (동의어·법령 용어)
// ════════════════════════════════════════════
let lastRagSources = [];
let lastLawmapData = null;        // 직전 자문 답변의 <lawmap> 블록 파싱 결과 (법령 관계도 자동 축적용)
let lastNewsSources = [];         // 직전 자문에 '본문 발췌로 실제 들어간' 수집 뉴스 (출처 표시·검증용)
let lastKbSources = [];           // 직전 자문에 들어간 요약·실무 문서(kb_chunks) — 동일 목적

function extractKeywords(text) {
  // 한국어 조사·어미·불용어 제거
  var stopwords = ['이','가','은','는','을','를','의','에','에서','으로','로','과','와','도',
    '만','그','이것','저것','그것','있다','없다','하다','되다','이다','어떻게','어떤',
    '무엇','언제','어디','왜','누가','대해','관해','통해','위해','따라','대한','관한',
    '통한','위한','있는','없는','하는','되는','인','이란','이라는','라는','라고',
    '이고','이며','하고','이나','이나','또는','그리고','하지만','그러나','따라서'];
  // 조사 어미 제거 (예: "면허세에" → "면허세") — 잘린 어간도 ilike 부분일치로 검색됨
  var josa = /(에서는|으로는|에서의|이라는|에서도|에서|에는|으로|로는|보다|부터|까지|처럼|마다|조차|밖에|은|는|이|가|을|를|의|에|와|과|도|만)$/;
  var words = text.split(/[\s,\.·\·\(\)\[\]\「\」\『\』\<\>\:;\!\?]+/)
    .map(function(w) { return w.replace(/[^가-힣a-zA-Z0-9\.]/g, '').trim(); })
    .map(function(w) { var s = w.replace(josa, ''); return s.length >= 2 ? s : w; })
    .filter(function(w) { return w.length >= 2 && !stopwords.includes(w); });
  // 법령 키워드 우선 (조문번호, 주제어)
  var priority = words.filter(function(w) {
    return /제\d+조|주파수|할당|재할당|전자파|ITU|5G|6G|EMC|SAR|고시|시행령|시행규칙|적합성|기술기준|무선국|면허|허가|신청|승인|폐업|폐지|이용기간/.test(w);
  });
  var rest = words.filter(function(w) { return !priority.includes(w); });
  var all = priority.concat(rest);
  // 중복 제거
  return all.filter(function(v, i, a) { return a.indexOf(v) === i; }).slice(0, 5);
}

// ── 정책 어휘 → 법령 조문 표제어 대응표 (rag.ts LAW_SYNONYMS와 동일 유지 — 한쪽만 고치지 말 것) ──
// LLM 확장만으로는 이 간극을 못 넘는다(실측: Haiku·Sonnet 모두 "3G 종료"에서 '휴업·폐업'을 못 냄).
// 법은 '서비스 종료'라 쓰지 않는다 — 전기통신사업법은 '휴업·폐업', 전파법은 '폐지·운용휴지'다.
var LAW_SYNONYMS = {
  '종료': ['휴업', '폐업', '폐지', '휴지', '운용휴지'],
  '중단': ['휴업', '휴지', '정지', '중지'],
  '폐지': ['폐업', '폐지', '휴지'],
  '개시': ['개설', '허가', '등록', '신고'],
  '시작': ['개설', '허가', '등록'],
  '변경': ['변경허가', '변경등록', '변경신고'],
  '취소': ['취소', '정지', '철회'],
  '반납': ['반납', '회수', '재할당'],
};
// 질문에 정책 동사가 있으면 대응하는 법령 표제어를 돌려준다 (검색 키워드에 추가 투입용)
function lawSynonymKeywords(query) {
  var out = [];
  Object.keys(LAW_SYNONYMS).forEach(function(k) {
    if ((query || '').indexOf(k) >= 0) {
      LAW_SYNONYMS[k].forEach(function(s) { if (out.indexOf(s) === -1) out.push(s); });
    }
  });
  return out;
}
// 질문 상투어 — 조문 제목 가점·주제 매칭에서 제외 ('절차'가 「규제심사 절차」 같은
// 무관 조문 제목에 걸려 상위를 차지하는 것 방지. rag.ts와 동일 목록 유지)
var GENERIC_QUERY_WORDS = ['방법', '방안', '절차', '하는', '관련', '대한'];
// 법령 위계 (동점 정렬용): 법률 > 대통령령 > 부령·총리령 > 고시·훈령 등 — rag.ts와 동일 유지
function lawRank(docName) {
  var d = docName || '';
  if (/\(법률\)/.test(d)) return 4;
  if (/\(대통령령\)/.test(d)) return 3;
  if (/(부령|총리령)\)/.test(d)) return 2;
  return 1;
}
// 도메인 사전확률: 이 KB는 전파·통신 정책용이라, 행위·주제 점수가 같으면 전파·통신 계열
// 법령이 국가재정법·위치정보법 같은 부수 수록 문서보다 근거일 확률이 높다 (질문과 무관한 상수 가점)
var DOMAIN_DOC_RE = /전파|통신|무선|주파수/;

// 뉴스 전용 키워드 추출 — 위 extractKeywords(법령 검색용)와 반드시 분리해서 쓴다.
// 여기 불용어('통신사','영향','분석' 등)를 extractKeywords에 넣으면 법령 RAG 검색 품질이 함께 망가진다.
// (사고: "같은 지하철인데 통신사 와이파이 속도…" 질문에서 키워드가 '같은/지하철인데/통신사'로 뽑혀
//  정작 질문이 인용한 기사 본문이 프롬프트에 못 들어갔음 — '인데'가 조사 목록에 없어 0건)
function extractNewsKeywords(text) {
  // 뉴스 본문 어디에나 나오는 저변별력 단어 + 질문 상투어는 버린다
  var stopwords = ['같은','같이','최대','최소','정도','이유','영향','분석','분석해','분석해줘','차이',
    '통신사','통신','관련','현황','상황','내용','문제','방안','대응','전망','의미','비교','평가','수준','규모',
    '최근','요즘','지금','현재','올해','작년','국내','해외','업계','우리','회사','부분','경우','전체',
    '해줘','알려줘','설명','설명해줘','정리','정리해줘','작성','검토','어떻게','어떤','무엇','언제','어디','왜',
    '있다','없다','하다','되다','이다','대해','관해','통해','위해','따라','대한','관한','그리고','하지만'];
  // 조사·어미 (extractKeywords보다 넓게 — 뉴스 질문 말투를 벗긴다: "지하철인데" → "지하철")
  var tail = /(이라는데|이라는|이라며|이라고|인데도|에서는|으로는|에서의|에서도|라는데|인데|인가|인지|라며|라고|는데|에서|에는|으로|로는|보다|부터|까지|처럼|마다|조차|밖에|이나|나는|은|는|이|가|을|를|의|에|와|과|도|만)$/;
  // 통신·전파 도메인어 — 우선순위 부여 + 조사 절단 보호에 함께 쓴다
  var domain = /주파수|대역|백홀|기지국|중계기|와이파이|WiFi|5G|6G|LTE|위성|전파|간섭|품질평가|재할당|할당|요금|보조금|단말|로밍|알뜰폰|MVNO|망중립|해킹|유출|과징금|지하철|철도|국회|고시|시행령|입법예고/i;
  var words = text.split(/[\s,\.·\(\)\[\]\「\」\『\』\<\>\:;\!\?\"\']+/)
    .map(function(w) { return w.replace(/[^가-힣a-zA-Z0-9]/g, '').trim(); })
    .map(function(w) {
      var s = w.replace(tail, '');
      if (domain.test(s)) return s;                 // "지하철인데"→"지하철", "와이파이에서는"→"와이파이"
      if (domain.test(w)) return w;                 // "와이파이"의 끝 '이'를 조사로 오인해 자르는 것 방지
      return s.length >= 2 ? s : w;
    })
    .filter(function(w) { return w.length >= 2 && stopwords.indexOf(w) === -1; });
  var uniq = words.filter(function(v, i, a) { return a.indexOf(v) === i; });
  var pri  = uniq.filter(function(w) { return domain.test(w); });
  var rest = uniq.filter(function(w) { return !domain.test(w); })
    .sort(function(a, b) { return b.length - a.length; });
  return pri.concat(rest).slice(0, 6);
}

// ── 자문 출처 표기 ──────────────────────────────────────────
// chat_logs.sources는 text 1개 컬럼이라, 종류별 접두사로 구분해 같은 배열에 담는다 (스키마 변경 없음).
// 조문 원문(document_chunks)은 접두사 없음 / 뉴스 / 요약·실무(kb_chunks) / 별표 4종.
var NEWS_SRC_PREFIX = '[뉴스] ';
var KB_SRC_PREFIX = '[요약] ';
var ANNEX_SRC_PREFIX = '[별표] ';
function splitSources(arr) {
  var laws = [], news = [], kb = [], annex = [];
  (arr || []).forEach(function(s) {
    if (typeof s !== 'string' || !s) return;
    if (s.indexOf(NEWS_SRC_PREFIX) === 0) { if (news.indexOf(s) === -1) news.push(s); }
    else if (s.indexOf(KB_SRC_PREFIX) === 0) { if (kb.indexOf(s) === -1) kb.push(s); }
    else if (s.indexOf(ANNEX_SRC_PREFIX) === 0) { if (annex.indexOf(s) === -1) annex.push(s); }
    else if (laws.indexOf(s) === -1) laws.push(s);
  });
  return { laws: laws, news: news, kb: kb, annex: annex };
}
function stripNewsPrefix(s) { return s.indexOf(NEWS_SRC_PREFIX) === 0 ? s.slice(NEWS_SRC_PREFIX.length) : s; }
function stripKbPrefix(s) { return s.indexOf(KB_SRC_PREFIX) === 0 ? s.slice(KB_SRC_PREFIX.length) : s; }
function stripAnnexPrefix(s) { return s.indexOf(ANNEX_SRC_PREFIX) === 0 ? s.slice(ANNEX_SRC_PREFIX.length) : s; }
function kbTagsHtml(list) {
  return list.map(function(s) { return '<span class="rag-tag">' + chEsc(stripKbPrefix(s)) + '</span>'; }).join(' ');
}
function annexTagsHtml(list) {
  return list.map(function(s) { return '<span class="rag-tag">' + chEsc(stripAnnexPrefix(s)) + '</span>'; }).join(' ');
}
// 법령·문서 태그 — limit 초과분은 "… 등 N개"로 접는다 (무관 청크 12건이 화면을 뒤덮는 것 방지)
function sourceTagsHtml(list, limit) {
  var lim = limit || 6;
  var html = list.slice(0, lim).map(function(s) { return '<span class="rag-tag">' + chEsc(s) + '</span>'; }).join(' ');
  if (list.length > lim) html += ' <span class="rag-tag rag-tag-more">… 등 ' + list.length + '개</span>';
  return html;
}
function newsTagsHtml(list) {
  return list.map(function(s) { return '<span class="rag-tag">' + chEsc(stripNewsPrefix(s)) + '</span>'; }).join(' ');
}

// 쿼리 확장 — Haiku로 동의어·법령 공식 용어 키워드 생성 (실패 시 빈 배열 → 기존 키워드만 사용)
// 같은 질문에 대해 searchKeywords·searchLawArticles가 동시에 부르므로 프라미스 캐시로 1회만 호출
var _expandCache = { q: null, p: null };
function expandQueryKeywords(query) {
  if (_expandCache.q === query && _expandCache.p) return _expandCache.p;
  _expandCache.q = query;
  _expandCache.p = _expandQueryKeywordsRaw(query);
  return _expandCache.p;
}
async function _expandQueryKeywordsRaw(query) {
  try {
    var { claudeKey } = getConfig();
    if (!claudeKey) return [];
    var res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'x-api-key': claudeKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json', 'anthropic-dangerous-direct-browser-access': 'true' },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 200,
        system: '당신은 한국 전파·통신 법령 검색 전문가입니다. 사용자 질문을 법령·고시 원문에서 실제 쓰이는 공식 용어로 확장합니다.',
        messages: [{ role: 'user', content: '다음 질문을 법령·고시 문서 검색용 키워드로 확장해줘. 질문 표현과 다른 동의어, 법령 공식 용어, 관련 조문 주제어 위주로 6~8개. 쉼표로만 구분해 한 줄로 출력하고 설명은 금지:\n\n' + query }]
      })
    });
    if (!res.ok) return [];
    var data = await res.json();
    var text = (data.content && data.content[0] && data.content[0].text) || '';
    return text.split(',')
      .map(function(w) { return w.trim().replace(/^["'\d\.\)\s]+|["'\s]+$/g, ''); })
      .filter(function(w) { return w.length >= 2 && w.length <= 25; })
      .slice(0, 8);
  } catch(e) { console.warn('쿼리 확장 실패 (기본 키워드로 진행):', e); return []; }
}

async function getQueryEmbedding(query, model) {
  // Supabase Edge Function(voyage-embed)으로 질의 임베딩 생성 (키 노출 없음)
  // model 미지정=voyage-4-lite(document_chunks 조문) / 'voyage-law-2'(kb_chunks 법령요약).
  // 저장·질의 모델은 반드시 일치해야 함(모델별 임베딩 공간이 달라 혼용 시 검색 무의미).
  try {
    if (!sb) return null;
    var body = { query: query };
    if (model) body.model = model;
    var result = await sb.functions.invoke('voyage-embed', { body: body });
    if (result.error) { console.warn('voyage-embed 오류:', result.error); return null; }
    return (result.data && result.data.embedding) ? result.data.embedding : null;
  } catch(e) { console.warn('시맨틱 임베딩 실패 (폴백):', e); return null; }
}

async function searchKeywords(query, lawOnly) {
  if (!sb) return [];
  if (lawOnly === undefined) lawOnly = false;
  var baseKeywords = extractKeywords(query);
  var expanded = await expandQueryKeywords(query);
  // 기본 키워드 → 법령 표제어(LAW_SYNONYMS) → 확장 키워드 순으로 합친다.
  // 표제어를 확장보다 앞에 두는 이유: 아래 slice(0,10) 상한에서 LLM 확장어에 밀려
  // '휴업·폐업' 같은 결정적 법령 어휘가 잘리면 안 되기 때문(어휘 간극은 LLM이 못 메운다).
  var keywords = [];
  var seenKw = new Set();
  baseKeywords.concat(lawSynonymKeywords(query)).concat(expanded).forEach(function(w) {
    var norm = w.replace(/\s+/g, '').toLowerCase();
    if (norm.length >= 2 && !seenKw.has(norm)) { seenKw.add(norm); keywords.push(w); }
  });
  if (keywords.length === 0) return [];

  var seen = new Set();
  var results = [];

  // trgm + 시맨틱 검색 병렬 실행 (키워드 루프와 동시 진행)
  var trgmPromise = null;
  var semanticPromise = null;
  if (query && query.length >= 3) {
    // only_current를 명시적으로 넘긴다 — 기본값에 기대면 인자 개수가 다른 오버로드가
    // 생겼을 때 status 필터 없는 쪽으로 조용히 해석된다(배경역사 #31 후속 사고).
    trgmPromise = sb.rpc('search_chunks_trgm', {
      query_text: query,
      match_threshold: 0.12,
      match_count: 8,
      only_current: true
    }).then(function(r) { return r.data || []; }).catch(function(e) {
      console.warn('trgm 검색 오류:', e); return [];
    });
    // 시맨틱: Edge Function으로 임베딩 → pgvector 코사인 유사도
    semanticPromise = getQueryEmbedding(query).then(function(emb) {
      if (!emb) return [];
      return sb.rpc('match_chunks_semantic', {
        query_embedding: emb,
        match_threshold: 0.45,
        match_count: 8,
        only_current: true
      }).then(function(r) { return r.data || []; }).catch(function(e) {
        console.warn('시맨틱 검색 오류:', e); return [];
      });
    });
  }

  // 키워드별로 검색 (최대 10개 키워드, 키워드당 4청크) — 전 키워드 동시 조회 후 원래 순서로 병합
  var kwList = [];
  for (var ki = 0; ki < Math.min(keywords.length, 10); ki++) {
    if (keywords[ki].length >= 2) kwList.push(keywords[ki]);
  }
  var kwResults = await Promise.all(kwList.map(function(kw) {
    return sb
      .from('document_chunks')
      .select('id, doc_name, doc_category, chunk_index, content, notice_no, article_no, effective_date')
      .eq('is_approved', true)  // 승인 게이트: trgm·시맨틱 RPC와 동일하게 승인 전 문서 제외
      .eq('status', 'current')  // 구버전(superseded)·시행예정본(pending) 제외 — RPC 2종과 동일 기준
      .ilike('content', '%' + kw + '%')
      .limit(4)
      .then(function(resp) { return resp.data || []; })
      .catch(function(e) { console.warn('키워드 검색 오류:', kw, e); return []; });
  }));
  kwResults.forEach(function(rows) {
    for (var ri = 0; ri < rows.length; ri++) {
      var row = rows[ri];
      if (!seen.has(row.id)) {
        seen.add(row.id);
        results.push(row);
      }
    }
  });

  // trgm 결과 병합
  if (trgmPromise) {
    var trgmRows = await trgmPromise;
    trgmRows.forEach(function(row) {
      if (!seen.has(row.id)) {
        seen.add(row.id);
        row._trgm_score = row.trgm_score || 0;
        results.push(row);
      } else {
        for (var ri = 0; ri < results.length; ri++) {
          if (results[ri].id === row.id) {
            results[ri]._trgm_score = row.trgm_score || 0;
            if (!results[ri].article_no && row.article_no) results[ri].article_no = row.article_no;
            if (!results[ri].notice_no && row.notice_no) results[ri].notice_no = row.notice_no;
            if (!results[ri].effective_date && row.effective_date) results[ri].effective_date = row.effective_date;
            break;
          }
        }
      }
    });
    console.log('trgm 검색:', trgmRows.length + '개 청크');
  }

  // 시맨틱 결과 병합
  if (semanticPromise) {
    var semanticRows = await semanticPromise;
    semanticRows.forEach(function(row) {
      if (!seen.has(row.id)) {
        seen.add(row.id);
        row._semantic_score = row.similarity || 0;
        results.push(row);
      } else {
        for (var ri = 0; ri < results.length; ri++) {
          if (results[ri].id === row.id) {
            results[ri]._semantic_score = row.similarity || 0;
            if (!results[ri].article_no && row.article_no) results[ri].article_no = row.article_no;
            if (!results[ri].notice_no && row.notice_no) results[ri].notice_no = row.notice_no;
            if (!results[ri].effective_date && row.effective_date) results[ri].effective_date = row.effective_date;
            break;
          }
        }
      }
    });
    console.log('시맨틱 검색:', semanticRows.length + '개 청크');
  }

  // ── RRF(Reciprocal Rank Fusion) 융합 ──
  // 종전(배경역사 #23)에는 키워드 정규화(0~1)+trgm(0.12~0.5)+시맨틱×2(0.9~1.5)를 그대로
  // 합산해 척도가 다른 점수끼리 싸웠다(시맨틱 상위=논문이어도 합산 우승). 각 검색을 '순위'로
  // 환산해 1/(K+순위) 합으로 융합하면 척도 문제가 사라진다(K=60 관례) — 점수 크기가 아니라
  // "몇 개의 검색에서 얼마나 상위였나"가 결정한다.
  var synNormSet = new Set(lawSynonymKeywords(query).map(function(s) { return s.toLowerCase(); }));
  results.forEach(function(r) {
    var score = 0;
    for (var ki = 0; ki < Math.min(keywords.length, 10); ki++) {
      var kw = keywords[ki].toLowerCase();
      var w = baseKeywords.includes(keywords[ki]) ? 2 : 1;
      if ((r.content || '').toLowerCase().includes(kw)) score += w;
      if ((r.doc_name || '').toLowerCase().includes(kw)) score += w;
      // 조문 표제어 일치는 결정적 신호 (rag.ts searchLawArticles의 행위 가점 이식).
      // 단 '절차' 같은 질문 상투어는 제외 — 「규제심사 절차」 같은 무관 조문이 올라온다(실측).
      // 표제어 대응표(LAW_SYNONYMS) 출신 행위어는 더 크게: 법령이 실제 쓰는 어휘로 번역된 말이라
      // 원어 그대로의 우연 일치('조난통신 종료')보다 신뢰도가 높다.
      if ((r.article_no || '').toLowerCase().includes(kw) && GENERIC_QUERY_WORDS.indexOf(keywords[ki]) === -1) {
        score += synNormSet.has(kw) ? 4 : w * 2;
      }
    }
    r._score = score;          // RRF 순위 산출용 (절대값은 융합에 안 쓴다)
    r._hybrid_score = 0;
  });
  var RRF_K = 60;
  var addRrf = function(list) {
    list.forEach(function(r, idx) { r._hybrid_score += 1 / (RRF_K + idx + 1); });
  };
  addRrf(results.filter(function(r) { return (r._score || 0) > 0; })
    .slice().sort(function(a, b) { return b._score - a._score; }));
  addRrf(results.filter(function(r) { return (r._trgm_score || 0) > 0; })
    .slice().sort(function(a, b) { return b._trgm_score - a._trgm_score; }));
  addRrf(results.filter(function(r) { return (r._semantic_score || 0) > 0; })
    .slice().sort(function(a, b) { return b._semantic_score - a._semantic_score; }));
  // 일반 가점·감점 (rag.ts /law 검색 계층 이식 — 특정 질문·특정 조문 하드코딩 아님):
  //  · 조문번호(article_no) 있는 청크 = 법령·고시 원문 → 가점
  //  · 파일 확장자 문서(.pdf/.md 등) = 논문·계획서류 → 감점
  //    (doc_category '기타'에 고시와 박사논문이 섞여 카테고리로는 못 거른다 — rag.ts 실측 주석)
  //  크기 0.5/(K+1) = 목록 1개 1위 기여의 절반: 논문이 조문을 이기려면 한 목록 상위만큼 더 필요.
  var FILE_DOC_RE = /\.(pdf|md|docx|hwp)$/i;
  results.forEach(function(r) {
    if (r.article_no) r._hybrid_score += 0.5 / (RRF_K + 1);
    if (FILE_DOC_RE.test(r.doc_name || '')) r._hybrid_score -= 0.5 / (RRF_K + 1);
  });
  results.sort(function(a, b) { return b._hybrid_score - a._hybrid_score; });

  // 문서당 청크 상한 — 같은 doc_name 최대 3청크만 상위에 (논문 1편이 상위 12개를 독식하는 것 방지)
  var perDocCount = {};
  var picked = [];
  for (var pi = 0; pi < results.length && picked.length < 12; pi++) {
    var dn = results[pi].doc_name || '';
    perDocCount[dn] = (perDocCount[dn] || 0) + 1;
    if (perDocCount[dn] <= 3) picked.push(results[pi]);
  }

  console.log('3중 하이브리드 RRF (키워드확장 ' + expanded.length + '개 + trgm + 시맨틱):', keywords.slice(0,10).join(', '), '->', results.length + '개 청크 (문서당 ≤3, 상위 ' + picked.length + '개 사용)');
  return picked;
}

// ── 조문 정밀검색 (rag.ts searchLawArticles 이식 — 봇 /law·자문과 동일 계층) ──
// RAG 하이브리드는 논문·보도자료도 섞여 정작 근거 조문을 놓치는 일이 있다(실측).
// ① 키워드 확장 + 정책어휘→법령표제어 표(LAW_SYNONYMS)로 어휘 간극을 메우고
// ② 조문번호(article_no) 있는 청크만 보고 ③ .pdf/.md 등 파일 문서를 제외한 뒤
// ④ 행위(조문 표제어)와 주제(문서명)를 분리해 점수를 매긴다.
// 점수 규칙은 rag.ts와 동일하게 유지할 것 — 한쪽만 고치면 봇과 대시보드 답이 갈라진다.
async function searchLawArticles(query, limit) {
  if (!sb) return [];
  limit = limit || 5;
  var base = extractKeywords(query);
  var expanded = await expandQueryKeywords(query);

  var seenNorm = new Set();
  var keywords = [];
  var push = function(w) {
    var norm = w.replace(/\s+/g, '').toLowerCase();
    if (norm.length >= 2 && !seenNorm.has(norm)) { seenNorm.add(norm); keywords.push(w); }
  };
  // 표제어(LAW_SYNONYMS)를 확장어보다 앞에 — 아래 slice(0,10) 상한에서 잘리면 안 된다
  base.forEach(push);
  lawSynonymKeywords(query).forEach(push);
  expanded.forEach(push);
  if (!keywords.length) return [];

  // .pdf/.md 등 파일 문서 제외 — '실행계획(안).pdf'도 '6조'라는 article_no를 갖고 있어
  // 조문번호 유무만으로는 못 거른다(실측). 법령·고시 문서명은 확장자로 끝나지 않는다.
  var FILE_SUFFIX = ['%.pdf', '%.md', '%.docx', '%.hwp'];
  var hitQ = function(col, kw, take) {
    var q = sb.from('document_chunks')
      .select('id, doc_name, article_no, content')
      .eq('is_approved', true).eq('status', 'current')
      .not('article_no', 'is', null)
      .ilike(col, '%' + kw + '%');
    FILE_SUFFIX.forEach(function(f) { q = q.not('doc_name', 'ilike', f); });
    return q.limit(take)
      .then(function(r) { return r.data || []; })
      .catch(function(e) { console.warn('조문 정밀검색 오류:', kw, e); return []; });
  };

  // 점수는 '행위'와 '주제'를 분리해 매긴다(rag.ts 실측으로 도달한 구조).
  //   행위 = 폐업·휴지 같은 조문 표제어 → 조문 제목에 걸리면 결정적(×5)
  //   주제 = 기간통신사업·무선국 같은 대상 → 문서명·조문제목에 걸리면 가산
  // ★ limit을 작게 주면 안 된다: PostgREST는 정렬 없이 임의의 N건을 돌려주므로
  //   '폐업'으로 6건만 받으면 엉뚱한 법이 자리를 채우고 정작 근거 조문이 빠진다(실측: 6에서 누락, 40에서 포함).
  var acc = new Map();
  var putHit = function(r, act) {
    var cur = acc.get(r.id);
    if (cur) { if (act > cur._act) cur._act = act; }
    else { acc.set(r.id, Object.assign({}, r, { _hits: 0, _act: act, _top: 0 })); }
  };
  // 행위 가중은 어휘의 출처로 차등한다: LAW_SYNONYMS 출신(정책어→법령표제어로 '번역'된 말,
  // 예: 종료→휴업·폐업)은 7, 그 외(질문 원어·LLM 확장)는 5. 원어가 조문 제목에 우연히
  // 있는 경우('조난통신 종료 통보')는 대개 다른 제도라, 번역된 표제어보다 낮게 본다.
  var synNorms = new Set(lawSynonymKeywords(query).map(function(s) { return s.replace(/\s+/g, '').toLowerCase(); }));
  var jobs = [];
  keywords.slice(0, 10).forEach(function(kw) {
    var act = synNorms.has(kw.replace(/\s+/g, '').toLowerCase()) ? 7 : 5;
    jobs.push(hitQ('article_no', kw, 40).then(function(rows) { rows.forEach(function(r) { putHit(r, act); }); }));
    jobs.push(hitQ('content', kw, 10).then(function(rows) { rows.forEach(function(r) { putHit(r, 0); }); }));
  });
  await Promise.all(jobs);

  // 주제 일치는 부분문자열로 본다 — '기간통신사업'과 '전기통신사업법'은 앞글자가 달라
  // 접두 비교로는 안 잡히고 '통신사업'이라는 공통 조각으로만 이어진다.
  var topics = (query.match(/[가-힣A-Za-z0-9]{2,}/g) || [])
    .filter(function(t) { return GENERIC_QUERY_WORDS.indexOf(t) === -1; });
  acc.forEach(function(h) {
    var hay = h.doc_name + ' ' + (h.article_no || '');
    var best = 0;
    for (var ti = 0; ti < topics.length; ti++) {
      var t = topics[ti];
      if (t.length <= 3) { if (hay.indexOf(t) >= 0 && t.length > best) best = t.length; continue; }
      for (var i = 0; i < t.length; i++) {
        for (var j = t.length; j - i >= 4; j--) {
          if (hay.indexOf(t.slice(i, j)) >= 0) { if (j - i > best) best = j - i; break; }
        }
      }
    }
    h._top = best;
    // 행위를 우선하되 주제로 갈래를 좁히고, 동점은 도메인(전파·통신 계열) 문서를 앞세운다
    h._hits = h._act * 2 + best + (DOMAIN_DOC_RE.test(h.doc_name) ? 1 : 0);
  });

  // 정렬: 점수 → (동점이면) 법령 위계(법률>대통령령>부령>고시) → 문서명·조문번호(결정적 순서).
  // 위계 동점 처리는 특정 법 우대가 아니라 일반 규칙 — 같은 점수면 상위 법령의 조문이 근거로 더 낫다.
  var sorted = Array.from(acc.values()).sort(function(a, b) {
    if (b._hits !== a._hits) return b._hits - a._hits;
    var lr = lawRank(b.doc_name) - lawRank(a.doc_name);
    if (lr !== 0) return lr;
    if (a.doc_name !== b.doc_name) return a.doc_name < b.doc_name ? -1 : 1;
    return (a.article_no || '') < (b.article_no || '') ? -1 : 1;
  });
  // 같은 조문이 여러 청크로 쪼개져 있으면 대표 1건만 — 목록이 중복으로 채워지는 것 방지
  var byArticle = new Map();
  sorted.forEach(function(h) {
    var key = h.doc_name + '|' + (h.article_no || '');
    if (!byArticle.has(key)) byArticle.set(key, h);
  });
  return Array.from(byArticle.values()).slice(0, limit);
}

async function fetchLawTrackContext() {
  // AI 자문 보조용: 최근 법령·고시 개정 + 입법예고 동향(요약). 조문 인용은 지식베이스 원문 우선.
  if (!sb) return '';
  try {
    var resp = await sb.from('law_amendments')
      .select('law_nm,law_type,ann_type,public_dt,enf_dt,summary')
      .order('public_dt', { ascending: false }).limit(500);
    var rows = resp.data || [];
    var dg = function(v) { return String(v || '').replace(/\D/g, ''); };
    var latest = {};
    rows.forEach(function(r) {
      if (r.law_type === 'lsAnc') { latest['lsAnc::' + (r.law_nm || '')] = r; return; }
      var k = r.law_nm || '';
      if (!latest[k] || dg(r.public_dt) > dg(latest[k].public_dt)) latest[k] = r;
    });
    var now = new Date();
    var todayStr = now.toISOString().slice(0,10).replace(/-/g,'');
    var d180 = new Date(now - 180 * 86400000).toISOString().slice(0,10).replace(/-/g,'');
    var items = Object.keys(latest).map(function(k) { return latest[k]; }).filter(function(r) {
      if (r.law_type === 'lsAnc') return true;
      if (dg(r.enf_dt) >= todayStr) return true;
      return dg(r.public_dt) >= d180;
    }).sort(function(a, b) { return dg(b.public_dt).localeCompare(dg(a.public_dt)); }).slice(0, 25);
    if (!items.length) return '';
    var fmt = function(v) { var d = dg(v); return d.length === 8 ? d.slice(0,4)+'.'+d.slice(4,6)+'.'+d.slice(6) : '—'; };
    var lines = items.map(function(r) {
      var typ = r.law_type === 'lsAnc' ? '입법예고' : (r.ann_type || '개정');
      var dates = r.law_type === 'lsAnc' ? ('의견마감 ' + fmt(r.enf_dt)) : ('공포 ' + fmt(r.public_dt) + ', 시행 ' + fmt(r.enf_dt));
      var sm = (r.summary || '').trim();
      return '\u2022 [' + typ + '] ' + (r.law_nm || '') + ' (' + dates + ')' + (sm ? ': ' + sm : '');
    });
    return '\n\n---\n\n[최근 행정부 법령·고시 개정·입법예고 동향]\n' +
      '(최근 추적된 변경/입법예고 요약. 정확한 조문 인용은 지식베이스 법령 원문을 우선하세요.)\n' +
      lines.join('\n');
  } catch (e) {
    console.warn('lawtrack context 로드 실패:', e);
    return '';
  }
}

function buildRagContext(chunks) {
  if (!chunks || chunks.length === 0) return '';
  const items = chunks.map(function(c, i) {
    var meta = [];
    if (c.article_no) meta.push('조항: ' + c.article_no);
    if (c.notice_no) meta.push('고시번호: ' + c.notice_no);
    if (c.effective_date) meta.push('시행일: ' + c.effective_date);
    var metaStr = meta.length ? ' [' + meta.join(' | ') + ']' : '';
    var sim = c._semantic_score ? ' (시맨틱: ' + (c._semantic_score * 100).toFixed(0) + '%)' : (c._trgm_score ? ' (trgm: ' + (c._trgm_score * 100).toFixed(0) + '%)' : '');
    return '[참조 ' + (i+1) + '] 출처: ' + c.doc_name + ' (' + c.doc_category + ')' + metaStr + sim + '\n' + c.content;
  });
  return '\n\n---\n\n[RAG 검색 결과 — 질문과 관련된 실제 법령·고시 원문]\n아래 내용은 질문과 의미적으로 유사한 문서 청크를 검색한 결과입니다. 반드시 아래 원문을 최우선으로 인용하고, 조항 번호와 내용이 일치하는지 확인하여 답변하세요:\n\n' + items.join('\n\n---\n\n');
}

// ── 시행예정 개정본 컨텍스트 (Phase 3) ─────────────────────────────
//
// RAG가 가져온 것은 '현행' 조문뿐이다(only_current=true). 그런데 법령은 공포 후
// 시행 전인 개정본이 이미 확정돼 있는 경우가 많고(정보통신망법은 2026.9.11 /
// 2026.10.1 / 2027.4.1 세 시점), 실무 답변은 "지금은 A인데 언제부터 B가 된다"까지
// 알려줘야 쓸모가 있다. 여기서 인용된 조문에 대응하는 시행예정 조문 원문을 붙인다.
//
// 문자열 diff는 하지 않는다 — 현행 등재본의 다수가 PDF 추출본이라 줄바꿈·따옴표·
// 날짜 표기가 API본과 달라 기계 비교는 위양성이 100% 난다. 양쪽 원문을 나란히 주고
// 무엇이 달라지는지는 모델이 읽어 판단하게 한다.
var lastPendingNotice = null;   // 답변 하단 배지용 [{law_name, enf_date}]

// ── 별표 동반 인출 ────────────────────────────────────────────────
//
// 조문과 별표는 별개 청크라 서로 끌어주지 못한다. "무선국 변경신고 금액?"에
// 시행령 제95조("변경허가를 신청하는 자는 별표 12에 따른 수수료를 낸다")는
// 잡혔는데 정작 금액이 적힌 별표12는 안 따라와, 자문이 "원문을 별도 확인하라"고
// 답했다 — DB에 있는 자료를 두고 사용자를 밖으로 내보낸 것이다. (배경역사 #43)
//
// 왜 검색으로는 못 잡나(실측): 별표12 첫 청크의 시맨틱 유사도가 그 질문에서
// 0.408로 임계값 0.45 미달. 별표 제목을 머리말로 붙여 재임베딩해도 0.406으로
// 그대로였다 — 「변경신고」(법 제22조의2)와 「변경허가」(제21조)는 다른 제도라
// 어휘를 손봐도 좁혀지지 않는다. 반면 둘을 잇는 다리인 제95조는 이미 잡혔다.
// 그래서 검색 확률을 올리는 대신 **인용 관계를 규칙으로 따라간다**.
var lastAnnexSources = [];       // 답변 하단 '참조 별표' 배지용
var ANNEX_MAX_UNITS  = 2;        // 질문당 별표 개수
var ANNEX_MAX_CHUNKS = 6;        // 별표당 청크 (별표 하나가 최대 812청크라 상한 필수)

async function buildAnnexContext(chunks, question) {
  lastAnnexSources = [];
  if (!sb || !chunks || !chunks.length) return '';
  try {
    // 1) 검색된 '조문' 청크에서 별표 인용을 뽑는다. 별표·별지 청크 자신은 제외(자기 참조 방지).
    //    「다른 법령」 별표 N 형태는 건너뛴다 — 같은 문서의 같은 번호 별표를 붙이면
    //    엉뚱한 표가 들어간다(전체 인용 978건 중 90건이 타 법령 인용).
    var wanted = [], seen = {};
    var reCite = /(「[^」]{2,40}」[^\n]{0,20}?)?별표\s*제?\s*(\d+(?:의\d+)?)/g;
    chunks.forEach(function(c) {
      if (/^(별표|별지)/.test(c.article_no || '')) return;
      var m; reCite.lastIndex = 0;
      while ((m = reCite.exec(String(c.content || '')))) {
        if (m[1]) continue;                       // 타 법령 인용 — 건너뜀
        var key = c.doc_name + '|' + m[2];
        if (seen[key]) continue;
        seen[key] = 1;
        wanted.push({ doc_name: c.doc_name, no: m[2], from: c.article_no || '' });
      }
    });
    // 인용이 없어도 그냥 끝내면 안 된다 — 아래 2)의 '표 머리 보충'이 필요한 경우가
    // 바로 이 경우다(별표 조각만 검색되고 조문은 안 잡힌 질문). 실측에서 놓칠 뻔했다.
    wanted = wanted.slice(0, ANNEX_MAX_UNITS);    // chunks가 순위순이라 앞쪽이 상위 조문

    var qWords = extractKeywords(question || '');
    var blocks = [];
    for (var i = 0; i < wanted.length; i++) {
      var w = wanted[i];
      var r = await sb.from('document_chunks')
        .select('chunk_index,article_no,content')
        .eq('doc_name', w.doc_name).eq('status', 'current')
        .like('article_no', '별표 ' + w.no + '(%')
        .order('chunk_index', { ascending: true });
      if (r.error || !r.data || !r.data.length) continue;

      // 첫 청크는 무조건 넣는다 — 표의 열 이름이 여기에만 있어서,
      // 가운데 청크만 넣으면 '1만원 │― │―'처럼 무슨 숫자인지 알 수 없다.
      var all = r.data;
      var picked = [all[0]];
      var rest = all.slice(1).map(function(c) {
        var t = String(c.content || '');
        var hit = qWords.reduce(function(a, kw) { return a + (t.indexOf(kw) >= 0 ? 1 : 0); }, 0);
        return { c: c, hit: hit };
      }).sort(function(a, b) {
        return b.hit !== a.hit ? b.hit - a.hit : a.c.chunk_index - b.c.chunk_index;
      });
      rest.slice(0, ANNEX_MAX_CHUNKS - 1).forEach(function(x) { picked.push(x.c); });
      picked.sort(function(a, b) { return a.chunk_index - b.chunk_index; });

      var title = (all[0].article_no || ('별표 ' + w.no));
      var omitted = all.length - picked.length;
      blocks.push('[' + w.doc_name + ' ' + title + ']'
        + (omitted > 0 ? '\n※ 이 별표는 전체 ' + all.length + '개 조각 중 질문과 가까운 ' + picked.length + '개만 실었습니다. 표의 일부만 보이면 그렇게 밝히세요.' : '')
        + '\n' + picked.map(function(c) { return c.content; }).join('\n'));
      lastAnnexSources.push(w.doc_name.split('(')[0].trim() + ' ' + title.split('(')[0].trim());
    }
    // 2) 별표 청크가 검색으로 직접 잡혔는데 '첫 조각'이 빠진 경우 그것만 보충한다.
    //    표의 열 이름은 첫 조각에만 있어서, 가운데 조각만 들어가면 모델은
    //    '│1만원 │― │―│' 같은 숫자열만 보고 무슨 항목인지 모른다(실측: 별표 27이 그랬다).
    //    대상은 **검색 상위 5위 안에 든 별표**로 좁힌다. 검색에 걸린 모든 별표에
    //    머리를 붙였더니 질문과 무관한 표(적합성평가 시험수수료, 상호인정협정 별표)까지
    //    딸려 왔다. 하위권 별표는 어차피 근거로 안 쓰인다.
    //    그리고 '첫 조각이 빠진 것'만 먼저 추린 뒤에 개수 상한을 건다 —
    //    먼저 자르면 이미 충족된 별표가 자리를 차지해 정작 필요한 것이 잘린다(실측 사고).
    var needHead = {}, headBlocks = [];
    chunks.slice(0, 5).forEach(function(c) {
      if (!/^별표/.test(c.article_no || '')) return;
      var k = c.doc_name + '|' + String(c.article_no).split('(')[0];
      if (!needHead[k]) needHead[k] = c;
    });
    var heads = Object.keys(needHead);
    for (var j = 0; j < heads.length && headBlocks.length < 2; j++) {
      var hc = needHead[heads[j]];
      var prefix = String(hc.article_no).split('(')[0];
      var hr = await sb.from('document_chunks')
        .select('chunk_index,article_no,content')
        .eq('doc_name', hc.doc_name).eq('status', 'current')
        .like('article_no', prefix + '(%')
        .order('chunk_index', { ascending: true }).limit(1);
      if (hr.error || !hr.data || !hr.data.length) continue;
      var first = hr.data[0];
      // 이미 검색 결과에 첫 조각이 들어 있으면 중복이므로 건너뛴다
      if (chunks.some(function(c) { return c.doc_name === hc.doc_name && c.chunk_index === first.chunk_index; })) continue;
      // 1)에서 이 별표를 통째로 실었다면 머리도 이미 들어갔다
      if (lastAnnexSources.indexOf(hc.doc_name.split('(')[0].trim() + ' ' + prefix) >= 0) continue;
      headBlocks.push('[' + hc.doc_name + ' ' + (first.article_no || prefix) + ' — 표 머리(열 이름)]\n' + first.content);
      lastAnnexSources.push(hc.doc_name.split('(')[0].trim() + ' ' + prefix + ' 머리');
    }
    if (headBlocks.length) {
      blocks.push('※ 아래는 위 검색 결과에 열 이름 없이 일부만 실린 표의 머리 부분입니다. 숫자가 어느 항목인지 여기서 확인하세요.\n\n'
        + headBlocks.join('\n\n'));
    }

    if (!blocks.length) return '';
    return '\n\n---\n\n[인용 조문이 가리키는 별표 원문]\n'
      + '위 조문이 "별표 N에 따른다"고 한 그 별표를 함께 싣습니다. **금액·기준·요율은 조문이 아니라 이 별표가 정본**이므로 여기서 인용하세요. '
      + '단, 질문이 묻는 항목이 이 별표에 없으면 없다고 답하고 임의로 유추하지 마세요.\n\n'
      + blocks.join('\n\n---\n\n');
  } catch(e) {
    console.warn('별표 동반 인출 실패(건너뜀):', e);
    return '';
  }
}

async function buildPendingContext(chunks) {
  lastPendingNotice = null;
  if (!sb || !chunks || !chunks.length) return '';
  try {
    // (문서, 조번호) 쌍으로 모은다. 문서 목록과 조번호 목록을 따로 넘기면 교차곱이 되어
    // 시행령의 제58조의2를 인용했는데 본법 제58조의2가 딸려 오는 식의 오매칭이 난다.
    var docs = [], pairs = [], seen = {};
    chunks.forEach(function(c) {
      if (!c.doc_name) return;
      if (docs.indexOf(c.doc_name) < 0) docs.push(c.doc_name);
      var m = String(c.article_no || '').replace(/^제/, '').match(/^([0-9]+조(?:의[0-9]+)?)/);
      if (!m) return;
      var k = c.doc_name + '|' + m[1];
      if (seen[k]) return;
      seen[k] = 1;
      pairs.push({ doc: c.doc_name, key: m[1] });
    });
    if (!docs.length) return '';

    var res = await Promise.all([
      sb.rpc('pending_versions_for_docs', { p_docs: docs }),
      pairs.length ? sb.rpc('fetch_pending_articles', { p_pairs: pairs, p_limit: 16 })
                   : Promise.resolve({ data: [] })
    ]);
    var vers = (res[0] && !res[0].error) ? (res[0].data || []) : [];
    var arts = (res[1] && !res[1].error) ? (res[1].data || []) : [];
    if (!vers.length) return '';

    function fmtD(v) { return v && v.length === 8 ? v.slice(0,4)+'.'+v.slice(4,6)+'.'+v.slice(6,8) : (v || ''); }

    // 법령별 시행 일정 요약 — 조문이 매칭되지 않아도 이건 알려줄 수 있어야 한다
    var byLaw = {};
    vers.forEach(function(v) { (byLaw[v.law_name] = byLaw[v.law_name] || []).push(v); });
    var schedule = Object.keys(byLaw).map(function(nm) {
      return '· ' + nm + ': ' + byLaw[nm].map(function(v) {
        return fmtD(v.enf_date) + ' 시행(제' + v.law_no + '호)';
      }).join(' → ');
    }).join('\n');

    // 총량 상한 — 과태료 조문처럼 긴 조문이 몇 개만 걸려도 수만 자가 된다.
    // 조문을 중간에서 자르면 모델이 잘린 문구를 인용할 수 있으므로 조문 단위로 끊고,
    // 빠진 건수는 명시한다(조용한 누락 금지).
    var BUDGET = 24000, used = 0, kept = [], dropped = 0;
    arts.forEach(function(a) {
      var s = '[시행예정 조문] ' + a.law_name + ' 제' + a.law_no + '호 — ' + fmtD(a.enf_date)
        + ' 시행 예정 | ' + a.article_no + '\n' + a.content;
      if (used + s.length > BUDGET && kept.length) { dropped++; return; }
      used += s.length; kept.push(s);
    });
    var body = kept.join('\n\n---\n\n')
      + (dropped ? '\n\n(분량 상한으로 시행예정 조문 ' + dropped + '건 생략 — 필요하면 해당 조문을 지목해 다시 질문하도록 안내하세요)' : '');

    lastPendingNotice = vers.map(function(v) { return { law_name: v.law_name, enf_date: v.enf_date }; });

    return '\n\n---\n\n[시행예정 개정본 — 아직 시행되지 않은 조문]\n'
      + '위 RAG 검색 결과는 모두 **현행** 조문입니다. 아래는 이미 공포되었으나 시행일이 도래하지 않은 개정본입니다.\n\n'
      + '■ 관련 법령의 시행 일정\n' + schedule + '\n\n'
      + (body ? '■ 인용 조문의 시행예정 원문\n\n' + body + '\n\n' : '')
      + '[사용 지침]\n'
      + '- 답변의 기본은 반드시 **현행 조문**입니다. 시행예정 내용을 현재 효력이 있는 것처럼 서술하지 마세요.\n'
      + '- 인용한 조문에 시행예정 개정이 있으면, 해당 설명 뒤에 "다만 YYYY.M.D.부터는 …로 개정 시행 예정" 형태로 한두 문장 덧붙이세요.\n'
      + '- 위 시행예정 원문과 현행 원문의 문구가 사실상 같다면(줄바꿈·따옴표·날짜 표기 차이뿐이면) 개정된 것이 아니므로 언급하지 마세요. 현행본 다수가 PDF에서 추출돼 표기가 다를 수 있습니다.\n'
      + '- 시행일이 여러 단계면 단계별로 무엇이 언제부터 달라지는지 구분해 쓰세요.\n'
      + '- 위 목록에 없는 조문의 개정 여부는 알 수 없습니다. 추측해서 "개정 예정 없음"이라고 단정하지 마세요.';
  } catch (e) {
    console.warn('시행예정 컨텍스트 조회 실패:', e);
    return '';   // 페일소프트 — 시행예정 조회가 실패해도 자문은 현행 기준으로 정상 동작
  }
}

// ── 법령·규제 요약 지식베이스(regulatory-kb / kb_chunks) ──
// document_chunks(조문 원문)와 별개 레이어. 조문 원문 인용은 RAG 우선, 여기는 요약·적용범위·실무 맥락.
// 시맨틱은 법률 특화 voyage-law-2로 질의 임베딩(저장도 law-2) + trgm 병행. 기본 현행본(current)만.
async function searchKbSummaries(query) {
  try {
    if (!sb || !query || query.trim().length < 2) return [];
    var trgmP = sb.rpc('search_kb_chunks_trgm', { query_text: query, match_threshold: 0.10, match_count: 6, only_current: true })
      .then(function(r) { return r.data || []; }).catch(function(e) { console.warn('kb trgm 오류(건너뜀):', e); return []; });
    var semP = getQueryEmbedding(query, 'voyage-law-2').then(function(emb) {
      if (!emb) return [];
      return sb.rpc('match_kb_chunks_semantic', { query_embedding: emb, match_threshold: 0.35, match_count: 6, only_current: true })
        .then(function(r) { return r.data || []; }).catch(function(e) { console.warn('kb 시맨틱 오류(건너뜀):', e); return []; });
    });
    var trgm = await trgmP, sem = await semP;
    var seen = {}, out = [];
    var key = function(r) { return r.doc_id + ':' + r.chunk_idx; };
    sem.forEach(function(r) { r._score = (r.similarity || 0) * 10; out.push(r); seen[key(r)] = r; });
    trgm.forEach(function(r) {
      var k = key(r);
      if (seen[k]) { seen[k]._score += (r.trgm_score || 0) * 5; }
      else { r._score = (r.trgm_score || 0) * 5; out.push(r); seen[k] = r; }
    });
    out.sort(function(a, b) { return b._score - a._score; });
    return out.slice(0, 5);
  } catch(e) { console.warn('법령요약 검색 실패(건너뜀):', e); return []; }
}

function buildKbContext(rows) {
  lastKbSources = [];
  if (!rows || rows.length === 0) return '';
  // 실제 프롬프트에 들어간 요약·실무 문서만 출처로 남긴다 — 그동안 kb 레이어(법령요약 165 + 실무안내 38)는
  // 배지에 전혀 표시되지 않아 "쓰였는지" 확인할 방법이 없었다. 뉴스(#35)와 같은 무음 구멍. (배경역사 #41)
  rows.forEach(function(r) {
    var t = (r.title || '').trim();
    if (t && lastKbSources.indexOf(KB_SRC_PREFIX + t) === -1) lastKbSources.push(KB_SRC_PREFIX + t);
  });
  var items = rows.map(function(r, i) {
    var meta = [];
    if (r.law_type) meta.push(r.law_type);
    if (r.law_number) meta.push('법령번호: ' + r.law_number);
    if (r.enforcement_date) meta.push('시행일: ' + r.enforcement_date);
    var metaStr = meta.length ? ' [' + meta.join(' | ') + ']' : '';
    return '[법령요약 ' + (i+1) + '] ' + (r.title || '') + metaStr + '\n' + (r.content || '');
  });
  return '\n\n---\n\n[법령·규제 요약 지식베이스 — 현행 법령·고시·훈령 요약/실무]\n' +
    '아래는 우리 팀이 정리한 법령·고시·훈령의 요약·적용범위·실무 체크리스트·소관부처 문서(현행본)입니다. ' +
    '법의 취지·실무 대응·담당부처를 물을 때 활용하세요. ' +
    '단, 정확한 조문 번호·문구 인용은 위 RAG 조문 원문을 최우선으로 하고, 이 요약은 실무 맥락 보강용으로 쓰세요:\n\n' +
    items.join('\n\n---\n\n');
}

// ════════════════════════════════════════════
//  Claude API
// ════════════════════════════════════════════
let chatHistory = [];
let isSending = false;



// ════════════════════════════════════════════
//  기술 용어 — 뉴스에서 자동 추출 (수동 실행)
// ════════════════════════════════════════════
// 용어 정규화: 공백 제거 + 소문자 변환 (2.6 GHz == 2.6ghz 중복 방지)
function normalizeTerm(s) { return (s||'').toLowerCase().replace(/\s+/g, ''); }

async function extractTermsFromNews() {
  var btn = document.getElementById('extract-terms-btn');
  if (!sb) { alert('Supabase 연결이 필요합니다.'); return; }
  var { claudeKey } = getConfig();
  if (!claudeKey) { alert('Claude API 키가 필요합니다.'); return; }
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="ti ti-loader"></i> 추출 중...'; }

  try {
    // 최근 7일 뉴스 가져오기
    var cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - 7);
    var cutoffStr = cutoff.toISOString().split('T')[0];
    var newsResp = await sb.from('news_feed').select('title,source,published_at').gte('created_at', cutoffStr).order('created_at', {ascending:false}).limit(30);
    var newsList = (newsResp.data || []).map(function(n) { return '[' + (n.published_at||'').slice(0,10) + '] ' + n.title + ' (' + (n.source||'') + ')'; }).join('\n');
    if (!newsList) { alert('최근 7일 뉴스가 없습니다. 먼저 뉴스 브리핑을 실행하세요.'); if(btn){btn.disabled=false;btn.innerHTML='<i class="ti ti-bulb"></i>뉴스에서 용어 추출';} return; }

    // 기존 용어 목록 (정규화 비교: 공백 제거 + 소문자)
    var existingResp = await sb.from('tech_terms').select('term').limit(500);
    var existingTerms = (existingResp.data || []).map(function(t) { return normalizeTerm(t.term); });

    // Claude에 용어 추출 요청
    var systemMsg = '당신은 이동통신·전파 전문가입니다. 반드시 순수 JSON 배열만 출력하세요. 마크다운 코드블록 없이.';
    var userMsg = '아래 뉴스 목록에서 이동통신·전파 분야 기술 용어(영문 약어, 표준명, 새 기술명)를 추출하세요.\n' +
      '이미 알려진 용어(' + existingTerms.slice(0,20).join(', ') + ' 등)는 제외하세요.\n\n' +
      '뉴스 목록:\n' + newsList + '\n\n' +
      '형식: [{"term":"약어","term_en":"영문 전체 이름","category":"주파수|네트워크|위성|단말|규제|기타","definition":"한 줄 정의(50자 이내)","source":"출처"}]\n' +
      '새 용어가 없으면 [] 출력.';

    var res = await fetch('https://api.anthropic.com/v1/messages', {
      method:'POST',
      headers:{'x-api-key':claudeKey,'anthropic-version':'2023-06-01','content-type':'application/json','anthropic-dangerous-direct-browser-access':'true'},
      // thinking:disabled — Sonnet 5는 thinking 미지정 시 적응형 추론이 켜져 응답 첫 블록이 빈 thinking 블록이 됨.
      //  → content[0].text가 undefined라 크래시했고, 숨은 thinking 토큰이 max_tokens(1500)를 잠식해 JSON도 잘렸음.
      body:JSON.stringify({model:'claude-sonnet-5',max_tokens:1500,thinking:{type:'disabled'},system:systemMsg,messages:[{role:'user',content:userMsg}]})
    });
    var data = await res.json();
    if (data.type === 'error' || !data.content) {
      throw new Error('Claude API 오류: ' + ((data.error && data.error.message) || JSON.stringify(data)));
    }
    // content[0]을 가정하지 말고 text 블록을 찾아서 사용 (적응형 추론 시 첫 블록이 thinking일 수 있음)
    var textBlock = data.content.find(function(b) { return b.type === 'text'; });
    var text = (textBlock ? textBlock.text : '').trim().replace(/^```[\w]*\n?/,'').replace(/\n?```$/,'').trim();
    var firstBracket = text.indexOf('[');
    var lastBracket = text.lastIndexOf(']');
    if (firstBracket === -1) { alert('용어 추출 결과가 없습니다.'); if(btn){btn.disabled=false;btn.innerHTML='<i class="ti ti-bulb"></i>뉴스에서 용어 추출';} return; }
    var terms = JSON.parse(text.slice(firstBracket, lastBracket + 1));

    if (terms.length === 0) { alert('새로운 기술 용어가 발견되지 않았습니다.'); if(btn){btn.disabled=false;btn.innerHTML='<i class="ti ti-bulb"></i>뉴스에서 용어 추출';} return; }

    // Supabase에 저장
    var saved = 0, skipped = 0;
    var newIds = [];
    for (var i = 0; i < terms.length; i++) {
      var t = terms[i];
      if (!t.term || existingTerms.includes(normalizeTerm(t.term))) { skipped++; continue; }
      var r = await sb.from('tech_terms').insert({
        term: t.term, term_en: t.term_en||'', category: t.category||'기타',
        definition: t.definition||'', source: t.source||'뉴스 자동 추출', is_reviewed: false
      }).select('id');
      if (!r.error && r.data && r.data[0]) {
        saved++;
        existingTerms.push(normalizeTerm(t.term));
        newIds.push(r.data[0].id);
      } else skipped++;
    }

    if (saved > 0) {
      alert('신규 용어 ' + saved + '건 저장됨. 설명·다이어그램을 백그라운드에서 자동 생성합니다.');
      await loadTerms(); // 목록 새로고침 후 설명 생성 시작
      // 새로 저장된 용어 설명을 백그라운드에서 자동 생성 (클릭 전 미리 채움)
      newIds.forEach(function(id) { generateTermDetail(id); });
    } else {
      alert('완료! 신규 용어 0건 저장, ' + skipped + '건 중복/스킵');
    }
  } catch(e) {
    alert('오류: ' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="ti ti-bulb"></i>뉴스에서 용어 추출'; }
  }
}

// ════════════════════════════════════════════
//  기술 용어 위키
// ════════════════════════════════════════════
let termsData = [];
let termsLoaded = false;

async function loadTerms() {
  if (!sb) { document.getElementById('terms-list').innerHTML = '<div style="padding:20px;color:var(--text-tertiary);font-size:12px">Supabase 연결 필요 (설정 탭에서 API 키 입력)</div>'; return; }
  try {
    var resp = await sb.from('tech_terms').select('id,term,term_en,category,definition,description,diagram_html,source,related_terms,is_reviewed,created_at').order('created_at', { ascending: false });
    termsData = resp.data || [];
    termsLoaded = true;
    var badge = document.getElementById('terms-count-badge');
    if (badge) badge.textContent = termsData.length + '개 용어';
    renderTerms(termsData);
  } catch(e) {
    console.warn('tech_terms 로드 실패:', e);
    document.getElementById('terms-list').innerHTML = '<div style="padding:20px;color:var(--text-tertiary);font-size:12px">tech_terms 테이블 없음 — Supabase에서 SQL 실행 필요</div>';
  }
}

function renderTerms(items) {
  var el = document.getElementById('terms-list');
  if (!el) return;
  if (!items || items.length === 0) {
    el.innerHTML = '<div style="padding:20px;color:var(--text-tertiary);font-size:12px;grid-column:1/-1">검색 결과가 없습니다.</div>';
    return;
  }
  var catColor = {주파수:'badge-purple', 네트워크:'badge-teal', 위성:'badge-blue', 단말:'badge-amber', 규제:'badge-red', 기타:'badge-amber'};
  el.innerHTML = items.map(function(t) {
    var cc = catColor[t.category] || 'badge-amber';
    var reviewed = t.is_reviewed ? '<span style="color:var(--green);font-size:10px">✓ 검토완료</span>' : '';
    // 용어 데이터는 AI가 외부 뉴스에서 추출해 DB에 저장한 값 — innerHTML 삽입 전 escHtml (#61)
    return '<div class="card" style="cursor:pointer;padding:12px 14px" onclick="openTermsModal(&quot;' + t.id + '&quot;)">' +
      '<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">' +
        '<span style="font-size:14px;font-weight:600;color:var(--text-primary)">' + escHtml(t.term) + '</span>' +
        (t.term_en ? '<span style="font-size:11px;color:var(--text-tertiary)">(' + escHtml(t.term_en) + ')</span>' : '') +
        '<span class="badge ' + cc + '" style="margin-left:auto">' + escHtml(t.category||'기타') + '</span>' +
      '</div>' +
      '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:6px">' + escHtml(t.definition || '(설명 없음)') + '</div>' +
      '<div style="display:flex;align-items:center;justify-content:space-between">' +
        '<span style="font-size:11px;color:var(--text-tertiary)">' + escHtml(t.source||'') + '</span>' +
        reviewed +
      '</div>' +
    '</div>';
  }).join('');
}

function filterTerms(query) {
  if (!termsLoaded) return;
  var cat = document.getElementById('terms-cat-filter').value;
  var q = (query||'').toLowerCase().trim();
  var filtered = termsData.filter(function(t) {
    var matchCat = !cat || t.category === cat;
    var matchQ = !q || (t.term||'').toLowerCase().includes(q) ||
      (t.term_en||'').toLowerCase().includes(q) ||
      (t.definition||'').toLowerCase().includes(q) ||
      (t.description||'').toLowerCase().includes(q);
    return matchCat && matchQ;
  });
  renderTerms(filtered);
}

// 마크다운 → HTML 변환 (bold, 단락 분리)
function mdToHtml(text) {
  if (!text) return '';
  return text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')  // escape first
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')                  // **bold**
    .replace(/\*(.*?)\*/g, '<em>$1</em>')                              // *italic*
    .split(/\n\n+/)
    .map(function(p) { return '<p style="margin:0 0 11px 0;line-height:1.75">' + p.replace(/\n/g,'<br>') + '</p>'; })
    .join('');
}

function renderTermsModalHtml(t) {
  var catColor = {주파수:'badge-purple', 네트워크:'badge-teal', 위성:'badge-blue', 단말:'badge-amber', 규제:'badge-red', 기타:'badge-amber'};
  var cc = catColor[t.category] || 'badge-amber';
  // 용어명을 onclick JS 문자열에 직접 넣지 않고 data-속성으로 전달 (속성 탈출 XSS 차단, #61)
  var related = (t.related_terms||[]).map(function(r) {
    return '<span class="badge badge-amber" style="cursor:pointer" data-term="' + escHtml(r) + '" onclick="closeTermsModal();var v=this.getAttribute(\'data-term\');document.getElementById(\'terms-search-input\').value=v;filterTerms(v)">' + escHtml(r) + '</span>';
  }).join(' ');

  var headerHtml =
    '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">' +
      '<span style="font-size:20px;font-weight:700;color:var(--text-primary)">' + escHtml(t.term) + '</span>' +
      (t.term_en ? '<span style="font-size:13px;color:var(--text-secondary)">' + escHtml(t.term_en) + '</span>' : '') +
      '<span class="badge ' + cc + '">' + escHtml(t.category||'기타') + '</span>' +
    '</div>' +
    (t.source ? '<div style="font-size:11px;color:var(--text-tertiary);margin-bottom:10px">📌 출처: ' + escHtml(t.source) + '</div>' : '<div style="margin-bottom:10px"></div>');

  // 한 줄 정의
  var defHtml = t.definition
    ? '<div style="font-size:13px;font-weight:500;margin-bottom:14px;padding:10px 14px;background:var(--bg-secondary);border-radius:var(--radius-md);border-left:3px solid var(--accent)">' + escHtml(t.definition) + '</div>'
    : '';

  var footerHtml =
    (related ? '<div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--border)"><span style="font-size:11px;color:var(--text-secondary);margin-right:6px">관련 용어</span>' + related + '</div>' : '') +
    '<div style="display:flex;gap:8px;margin-top:14px">' +
      '<button class="btn" style="font-size:11px;padding:4px 10px" onclick="generateTermDetail(&quot;' + t.id + '&quot;)" id="gen-btn-' + t.id + '">↺ 재생성</button>' +
      '<button class="btn" data-term="' + escHtml(t.term) + '" onclick="askQ(this.getAttribute(\'data-term\') + \' 기술에 대해 자세히 설명해줘\')">AI 자문에서 질문</button>' +
    '</div>';

  if (t.description) {
    // 캐시된 설명 있음 — 다이어그램 상단, 설명 하단 레이아웃
    var diagramHtml = t.diagram_html
      ? '<div style="margin-bottom:16px;padding:12px;background:var(--bg-secondary);border-radius:var(--radius-md);overflow-x:auto;text-align:center">' + t.diagram_html + '</div>'
      : '';
    return headerHtml + defHtml + diagramHtml +
      '<div style="font-size:13px;color:var(--text-primary)">' + mdToHtml(t.description) + '</div>' +
      footerHtml;
  } else {
    // 설명 없음 — 자동 생성 로딩 상태
    return headerHtml + defHtml +
      '<div id="gen-body-' + t.id + '" style="padding:28px 0;text-align:center;color:var(--text-secondary)">' +
        '<div style="display:inline-flex;align-items:center;gap:8px;font-size:13px">' +
          '<span style="display:inline-block;width:14px;height:14px;border:2px solid var(--accent);border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite"></span>' +
          'AI가 개념도와 상세 설명을 생성하는 중...' +
        '</div>' +
      '</div>';
  }
}

function openTermsModal(id) {
  var t = termsData.find(function(x) { return x.id === id; });
  if (!t) return;

  document.getElementById('terms-modal-content').innerHTML = renderTermsModalHtml(t);
  var modal = document.getElementById('terms-modal');
  modal.style.display = 'flex';

  // 설명 없으면 자동 생성 시작
  if (!t.description) {
    generateTermDetail(id);
  }
}

function closeTermsModal() {
  document.getElementById('terms-modal').style.display = 'none';
}

// ── 용어 상세 생성: 화면과 분리된 핵심부 ──────────────────────────
// 자동 생성(신규 추출 직후)과 수동 생성(모달 열기)이 같은 프롬프트를 쓰도록
// DOM을 건드리지 않는 순수 함수로 뽑았다. 반환: {description, diagram_html, related_terms}
// 실패 시 예외를 던진다 — 호출부가 화면 표시 여부를 정한다. (배경역사 #46)
async function _fetchTermDetail(t, claudeKey) {
  var termLabel = t.term + (t.term_en ? ' (' + t.term_en + ')' : '');
  var systemMsg = '당신은 이동통신·전파 정책 전문가입니다. 반드시 지정된 XML 태그 형식으로만 답변하세요.';
  var userMsg = '기술 용어 [' + termLabel + '] 에 대해 아래 형식으로 정확히 답변하세요.\n' +
    '분야: ' + (t.category||'기타') + '. 현재 정의: ' + (t.definition||'없음') + '.\n\n' +
    '<description>\n' +
    '3~5문단 상세 설명. **굵은글씨**로 핵심 개념 강조. 단락 구분은 빈 줄로.\n' +
    '내용: 개념 배경/기술 원리/국내외 현황/관련 표준 순서로 서술.\n' +
    '</description>\n\n' +
    '<diagram>\n' +
    '아래 조건을 모두 지킨 SVG를 생성하라:\n' +
    '- viewBox="0 0 680 320" xmlns="http://www.w3.org/2000/svg"\n' +
    '- 배경: rect fill="#f8fafc" 전체 채움\n' +
    '- 한국어 레이블 사용, font-family="sans-serif"\n' +
    '- 주요 구성요소를 박스/원/화살표로 시각화 (최소 4개 요소)\n' +
    '- 색상: 주요 박스 #6366f1(보라), 보조 #10b981(초록), 강조 #f59e0b(노랑), 배경박스 #e0e7ff\n' +
    '- 화살표는 marker-end 사용하여 방향 표시\n' +
    '- 개념 흐름이나 계층 구조를 한눈에 파악할 수 있게\n' +
    '</diagram>\n\n' +
    '<related>관련용어1,관련용어2,관련용어3</related>';
  var res = await fetch('https://api.anthropic.com/v1/messages', {
    method:'POST',
    headers:{'x-api-key':claudeKey,'anthropic-version':'2023-06-01','content-type':'application/json','anthropic-dangerous-direct-browser-access':'true'},
    body:JSON.stringify({model:'claude-sonnet-5',max_tokens:6000,system:systemMsg,messages:[{role:'user',content:userMsg}]})
  });
  var data = await res.json();
  if (data.type === 'error' || !data.content) {
    var errMsg = (data.error && data.error.message) ? data.error.message : JSON.stringify(data);
    throw new Error('Claude API 오류: ' + errMsg);
  }
  var textBlock = data.content.find(function(b) { return b.type === 'text'; });
  var text = textBlock ? textBlock.text : '';
  if (!text) throw new Error('Claude 응답 없음');

  // XML 태그로 파싱 (JSON 불필요 — SVG 포함 안전)
  var descMatch    = text.match(/<description>([\s\S]*?)<\/description>/);
  var diagramMatch = text.match(/<diagram>([\s\S]*?)<\/diagram>/);
  var relatedMatch = text.match(/<related>([\s\S]*?)<\/related>/);
  return {
    description:   descMatch    ? descMatch[1].trim()    : '',
    diagram_html:  diagramMatch ? diagramMatch[1].trim() : '',
    related_terms: relatedMatch
      ? relatedMatch[1].trim().split(',').map(function(s){return s.trim();}).filter(Boolean)
      : []
  };
}

async function generateTermDetail(id) {
  var t = termsData.find(function(x) { return x.id === id; });
  if (!t) return;
  var btn = document.getElementById('gen-btn-' + id);
  if (btn) { btn.disabled = true; btn.textContent = '생성 중...'; }
  var { claudeKey } = getConfig();
  if (!claudeKey) { alert('Claude API 키가 필요합니다.'); if(btn){btn.disabled=false;btn.textContent='🤖 Claude로 상세 설명·다이어그램 생성';} return; }
  try {
    var parsed = await _fetchTermDetail(t, claudeKey);

    // Supabase 업데이트
    if (sb) {
      await sb.from('tech_terms').update({
        description: parsed.description || t.description,
        diagram_html: parsed.diagram_html || t.diagram_html,
        related_terms: parsed.related_terms || t.related_terms
      }).eq('id', id);
    }
    // 로컬 데이터 갱신
    var idx = termsData.findIndex(function(x){return x.id===id;});
    if (idx >= 0) {
      termsData[idx].description = parsed.description;
      termsData[idx].diagram_html = parsed.diagram_html;
      termsData[idx].related_terms = parsed.related_terms;
    }
    // 모달 재렌더링
    openTermsModal(id);
  } catch(e) {
    // 생성 실패 시 로딩 영역에 에러 메시지 표시
    var genBody = document.getElementById('gen-body-' + id);
    if (genBody) {
      genBody.innerHTML = '<span style="font-size:12px;color:var(--text-secondary)">생성 실패: ' + e.message + ' &nbsp;<button class="btn" style="font-size:11px;padding:2px 8px" onclick="generateTermDetail(&quot;' + id + '&quot;)">재시도</button></span>';
    }
    if (btn) { btn.disabled = false; btn.textContent = '↺ 재생성'; }
  }
}

// ════════════════════════════════════════════
//  뉴스 컨텍스트 — 키워드 매칭 본문 발췌 + 제목 목록 (AI 자문 참조용)
// ════════════════════════════════════════════
async function fetchRecentNewsContext(query) {
  lastNewsSources = [];
  if (!sb) return '';
  try {
    var cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - 60); // 최근 60일
    var cutoffStr = cutoff.toISOString().split('T')[0];

    // [1] 최근 뉴스 제목 목록 (동향 파악용, 최대 30건)
    var listResp = await sb
      .from('news_feed')
      .select('title, source, published_at')
      .or('published_at.gte.' + cutoffStr + ',locked.eq.true')
      .not('title', 'ilike', '[업데이트]%')
      .order('published_at', { ascending: false })
      .limit(30);
    var allTitles = listResp.data || [];

    // [2] 질문 키워드로 관련 기사 선별 (최대 3건) — 제목 일치 가중 + 관련도 순 정렬
    //     ★ 최신순(order published_at desc, limit 2)으로 뽑으면 특정 이슈가 폭주한 날
    //       질문과 무관한 기사가 발췌 3칸을 다 차지한다. 실제로 그렇게 누락 사고가 났으므로
    //       "최신순 상위 N건" 방식으로 되돌리지 말 것. (배경역사 #35)
    var bodyResults = [];
    if (query) {
      var keywords = extractNewsKeywords(query);
      var qs = [];
      keywords.forEach(function(kw) {
        var esc = String(kw).replace(/[%_,]/g, ' ').trim();
        if (esc.length < 2) return;
        // 제목 일치(가중 3) — 질문이 특정 기사를 가리킬 때 가장 강한 신호
        qs.push(sb.from('news_feed').select('title, source, published_at, content')
          .or('published_at.gte.' + cutoffStr + ',locked.eq.true')
          .ilike('title', '%' + esc + '%')
          .order('published_at', { ascending: false }).limit(10)
          .then(function(r) { return { w: 3, rows: r.data || [] }; })
          .catch(function() { return { w: 3, rows: [] }; }));
        // 본문 일치(가중 1)
        qs.push(sb.from('news_feed').select('title, source, published_at, content')
          .or('published_at.gte.' + cutoffStr + ',locked.eq.true')
          .ilike('content', '%' + esc + '%').not('content', 'is', null)
          .order('published_at', { ascending: false }).limit(10)
          .then(function(r) { return { w: 1, rows: r.data || [] }; })
          .catch(function() { return { w: 1, rows: [] }; }));
      });
      var cand = {};
      (await Promise.all(qs)).forEach(function(p) {
        p.rows.forEach(function(n) {
          if (!n || !n.content) return;                    // 본문 없으면 발췌 불가
          if (!cand[n.title]) cand[n.title] = { row: n, score: 0 };
          cand[n.title].score += p.w;
        });
      });
      var ranked = Object.keys(cand).map(function(k) { return cand[k]; })
        .sort(function(a, b) {
          if (b.score !== a.score) return b.score - a.score;
          return String(b.row.published_at || '').localeCompare(String(a.row.published_at || ''));
        });
      // 관련도 2점 미만(키워드 1개만 스친 기사)은 "질문 관련"으로 보기 어렵다 →
      // 2점 이상이 하나도 없을 때만 상위 2건으로 완화
      var strong = ranked.filter(function(c) { return c.score >= 2; });
      bodyResults = (strong.length ? strong.slice(0, 3) : ranked.slice(0, 2))
        .map(function(c) { return c.row; });
      if (bodyResults.length) {
        console.log('[뉴스 컨텍스트] 키워드(' + keywords.join(', ') + ') → 발췌 ' +
          bodyResults.length + '건: ' + bodyResults.map(function(n) { return n.title; }).join(' / '));
      } else {
        console.log('[뉴스 컨텍스트] 키워드(' + keywords.join(', ') + ') → 관련 기사 없음');
      }
      // 본문 발췌로 실제 반영된 기사만 출처로 남긴다
      // (제목 목록 30건은 동향 참고용이라 근거가 아니므로 출처에 넣지 않는다 — 거짓 표기 방지)
      lastNewsSources = bodyResults.map(function(n) {
        return NEWS_SRC_PREFIX + n.title +
          ' (' + (n.source || '출처미상') + ', ' + String(n.published_at || '').slice(0, 10) + ')';
      });
    }

    var lines = [];

    // 관련 기사 본문 발췌 (질문과 관련된 경우 우선 표시)
    if (bodyResults.length > 0) {
      lines.push('[질문 관련 최신 기사]');
      // 발췌 길이는 순위별로 차등 — 1위(질문이 가리키는 기사)는 거의 전문, 2·3위는 요지만.
      // 일괄 600자로 자르면 기사 후반의 최신 상황(예: "SKT 시범 운영 중", 관계자 코멘트)이
      // 잘려 나가 답변이 옛 시점으로 후퇴한다. 실제 그 오류가 났으므로 줄이지 말 것. (배경역사 #35)
      bodyResults.slice(0, 3).forEach(function(n, i) {
        var lim = (i === 0) ? 1800 : 700;
        var full = (n.content || '');
        var excerpt = full.slice(0, lim).trim();
        lines.push('■ [' + String(n.published_at || '').slice(0, 10) + '] ' + n.title + ' (' + (n.source || '') + ')');
        if (excerpt) lines.push('  → ' + excerpt + (full.length > lim ? '...' : ''));
      });
    }

    // 최근 뉴스 제목 목록 (전반적인 동향 파악용)
    if (allTitles.length > 0) {
      lines.push('\n[최근 수집 뉴스 동향]');
      allTitles.forEach(function(n) {
        lines.push('  · [' + (n.published_at || '').slice(0, 10) + '] ' + n.title + ' (' + (n.source || '') + ')');
      });
    }

    if (lines.length === 0) return '';
    // 수치 인용 지시는 발췌 바로 뒤에 붙인다 — 기사 본문이 프롬프트에 들어갔는데도
    // 모델이 웹검색 쪽 수치를 골라 쓰는 일이 있었다. (배경역사 #35)
    return '\n\n' + lines.join('\n') +
      '\n(위 뉴스를 참고하여, 질문과 관련된 최신 동향이 있으면 출처와 날짜를 포함해 언급하세요.' +
      ' 특히 질문이 수치·순위 비교(속도·요금·점유율·과징금 등)를 묻는 경우, 위 [질문 관련 최신 기사]에 해당 수치가 있으면' +
      ' 웹 검색 결과나 학습 지식의 수치를 쓰지 말고 반드시 그 수치를 매체명·날짜와 함께 인용하세요.)';
  } catch(e) {
    console.warn('뉴스 컨텍스트 로드 실패:', e);
    return '';
  }
}

// ════════════════════════════════════════════
//  원문 수집 — CORS 프록시 경유 기사 본문 추출
// ════════════════════════════════════════════
var CORS_PROXIES = [
  'https://corsproxy.io/?',
  'https://api.allorigins.win/raw?url=',
];

async function _fetchArticleBody(url) {
  for (var pi = 0; pi < CORS_PROXIES.length; pi++) {
    try {
      var proxyUrl = CORS_PROXIES[pi] + encodeURIComponent(url);
      var resp = await fetch(proxyUrl, { signal: AbortSignal.timeout(10000) });
      if (!resp.ok) continue;
      var html = await resp.text();

      // DOMParser로 본문 추출
      var parser = new DOMParser();
      var doc = parser.parseFromString(html, 'text/html');

      // 불필요한 태그 제거
      ['script','style','nav','header','footer','aside','iframe','noscript'].forEach(function(tag) {
        doc.querySelectorAll(tag).forEach(function(el) { el.remove(); });
      });

      // 본문 셀렉터 순서대로 시도
      var selectors = [
        'article', '#articleBody', '#article_body', '#article-body',
        '.article_body', '.article-body', '.article_txt', '.article-txt',
        '.news_body', '.news-body', '.view_cont', '.view-content',
        '#articleWrap', '#newsContent', '.content_area', 'main'
      ];
      var bodyText = '';
      for (var si = 0; si < selectors.length; si++) {
        var el = doc.querySelector(selectors[si]);
        if (el) {
          var t = el.innerText || el.textContent || '';
          t = t.replace(/\s+/g, ' ').trim();
          if (t.length > 200) { bodyText = t; break; }
        }
      }
      // fallback: body 전체
      if (!bodyText) {
        bodyText = (doc.body.innerText || doc.body.textContent || '').replace(/\s+/g, ' ').trim();
      }

      if (bodyText.length > 100) return bodyText.slice(0, 3000);
    } catch(e) {
      console.warn('[원문 수집 실패] 프록시 ' + pi + ':', e.message);
    }
  }
  return '';
}

// ════════════════════════════════════════════
//  추가 지식 — custom_knowledge 검색 및 CRUD
// ════════════════════════════════════════════
async function searchCustomKnowledge(query) {
  if (!sb || !query) return '';
  try {
    var keywords = extractKeywords(query);
    if (keywords.length === 0) return '';
    var seen = new Set();
    var results = [];
    for (var ki = 0; ki < Math.min(keywords.length, 5); ki++) {
      var kw = keywords[ki];
      if (kw.length < 2) continue;
      try {
        var resp = await sb
          .from('custom_knowledge')
          .select('title, content, category')
          .eq('is_active', true)
          .or('title.ilike.%' + kw + '%,content.ilike.%' + kw + '%')
          .order('created_at', { ascending: false })
          .limit(3);
        (resp.data || []).forEach(function(row) {
          if (!seen.has(row.title)) {
            seen.add(row.title);
            results.push(row);
          }
        });
      } catch(e) { console.warn('추가지식(custom_knowledge) 조회 실패(건너뜀):', kw, e); }
      if (results.length >= 3) break;
    }
    if (results.length === 0) return '';
    var lines = ['\n\n[팀 내부 추가 지식 — 검증 완료]'];
    results.slice(0, 3).forEach(function(r, i) {
      var excerpt = (r.content || '').slice(0, 2500);
      lines.push('■ [' + (r.category || '일반') + '] ' + r.title);
      lines.push('  ' + excerpt + (r.content.length > 2500 ? '...' : ''));
    });
    lines.push('(위 내부 지식을 우선 참고하여 답변하세요.)');
    return lines.join('\n');
  } catch(e) {
    console.warn('추가 지식 검색 실패:', e);
    return '';
  }
}

async function saveCustomKnowledge(title, content, category, tagsStr) {
  if (!sb) throw new Error('Supabase 연결 없음');
  var tags = tagsStr ? tagsStr.split(',').map(function(t) { return t.trim(); }).filter(Boolean) : [];
  var { error } = await sb.from('custom_knowledge').insert({
    title: title, content: content, category: category || '일반', tags: tags
  });
  if (error) throw new Error(error.message);
}

async function updateCustomKnowledge(id, title, content, category, tagsStr) {
  if (!sb) throw new Error('Supabase 연결 없음');
  var tags = tagsStr ? tagsStr.split(',').map(function(t) { return t.trim(); }).filter(Boolean) : [];
  var { error } = await sb.from('custom_knowledge').update({
    title: title, content: content, category: category || '일반', tags: tags
  }).eq('id', id);
  if (error) throw new Error(error.message);
}

async function loadCustomKnowledgeList() {
  if (!sb) return [];
  var { data } = await sb
    .from('custom_knowledge')
    .select('id, title, category, tags, created_at, is_active')
    .order('created_at', { ascending: false })
    .limit(100);
  return data || [];
}

async function deleteCustomKnowledge(id) {
  if (!sb) throw new Error('Supabase 연결 없음');
  var { error } = await sb.from('custom_knowledge').delete().eq('id', id);
  if (error) throw new Error(error.message);
}

// 추가 지식 탭 "파일 업로드"분 — document_chunks(doc_category='추가지식')를
// doc_name 기준으로 묶어 목록에 함께 표시 (custom_knowledge와 별개 경로)
async function loadCustomFileList() {
  if (!sb) return [];
  try {
    var { data: rows } = await sb
      .from('document_chunks')
      .select('doc_name, created_at, file_path')
      .eq('doc_category', '추가지식')
      .order('created_at', { ascending: false })
      .limit(3000);
    if (!rows || rows.length === 0) return [];
    // 임베딩 완료된 청크 doc_name별 개수 (vector 본문은 받지 않고 not-null만 카운트)
    var { data: embRows } = await sb
      .from('document_chunks')
      .select('doc_name')
      .eq('doc_category', '추가지식')
      .not('embedding', 'is', null)
      .limit(3000);
    var embCount = {};
    (embRows || []).forEach(function(r) {
      embCount[r.doc_name] = (embCount[r.doc_name] || 0) + 1;
    });
    var map = {};
    rows.forEach(function(r) {
      var m = map[r.doc_name];
      if (!m) { m = map[r.doc_name] = { doc_name: r.doc_name, chunks: 0, created_at: r.created_at, file_path: null }; }
      m.chunks++;
      if (r.created_at < m.created_at) m.created_at = r.created_at; // 최초 업로드 시각
      if (!m.file_path && r.file_path) m.file_path = r.file_path; // 원본 파일 경로 (있으면 다운로드)
    });
    return Object.keys(map).map(function(n) {
      var m = map[n];
      m.embedded = embCount[n] || 0;
      m._type = 'file';
      return m;
    });
  } catch(e) {
    console.warn('업로드 파일 목록 로드 실패:', e);
    return [];
  }
}

async function onDownloadCustomFile(filePath, downloadName) {
  if (!sb || !filePath) return;
  try {
    var { data, error } = await sb.storage.from('uploads')
      .createSignedUrl(filePath, 60, { download: downloadName || true });
    if (error || !data || !data.signedUrl) throw new Error(error ? error.message : '다운로드 링크 생성 실패');
    window.open(data.signedUrl, '_blank');
  } catch(e) {
    alert('다운로드 실패: ' + e.message);
  }
}

async function onDeleteCustomFile(docName, btn) {
  if (!confirm('업로드 파일 "' + docName + '"의 모든 청크를 삭제하시겠습니까?')) return;
  var pwd = _ensureAdminPwd();
  if (!pwd) return;
  if (btn) btn.disabled = true;
  try {
    // 원본 파일 보관 경로 조회 → Storage 객체도 함께 삭제
    var paths = [];
    try {
      var { data: fp } = await sb.from('document_chunks')
        .select('file_path')
        .eq('doc_category', '추가지식').eq('doc_name', docName)
        .not('file_path', 'is', null).limit(1);
      (fp || []).forEach(function(r) { if (r.file_path) paths.push(r.file_path); });
    } catch(e) { console.warn('원본 file_path 조회 실패(Storage 정리 생략될 수 있음):', e); }

    // document_chunks는 RLS가 켜져 있고 DELETE 정책이 없다. 프런트에서 직접
    // delete()하면 PostgREST가 오류 없이 '0건 삭제 성공'으로 응답해 조용히 실패한다
    // (운영자가 삭제 버튼을 눌러도 아무 일도 안 일어나던 원인). 서버 검증 RPC로 처리. (#48)
    var res = await sb.rpc('admin_delete_custom_file', { p_doc_name: docName, p_pwd: pwd });
    if (res.error) { _handleAdminRpcError(res.error, '삭제'); if (btn) btn.disabled = false; return; }
    // 반환된 삭제 행수가 0이면 실패다 — 이 가드가 없으면 같은 무성 실패가 재발한다
    if (!res.data) {
      alert('삭제된 청크가 없습니다. 문서명이 바뀌었거나 이미 삭제된 항목일 수 있습니다.');
      if (btn) btn.disabled = false;
      return;
    }
    if (paths.length) { try { await sb.storage.from('uploads').remove(paths); } catch(e) { console.warn('Storage 원본 삭제 실패(파일 잔존 가능):', e); } }
    renderCustomKnowledgeList((document.getElementById('ck-list-search') || {}).value || '');
  } catch(e) {
    alert('삭제 실패: ' + e.message);
    if (btn) btn.disabled = false;
  }
}

// ── 보도자료 질의 판별·검색 (0313a8f에서 복원 — 08d29f1에서 유실) ──
function isPressQuery(query) {
  return /보도자료|보도|발표|공지|공고|과기정통부|국립전파연구원|전파연구원|방송통신위원회|방통위|중앙전파관리소|전파관리소|ETRI|KISDI/.test(query);
}
// 보도자료 검색 — pressData(제목·날짜·doc_name·agency만 보유)에서 제목 매칭으로 후보를
// 고른 뒤, 본문은 document_chunks에서 doc_name+제목 일부 ilike로 실조회해 채운다.
// (과거엔 원소에 content/id가 있다고 가정해 TypeError로 자문이 죽었음 — 데이터 소스가
//  JSON→Supabase로 바뀐 잔재. 본문 조회 실패 항목은 결과에서 제외해 원천 차단.)
async function searchPressReleases(query) {
  if (!pressData || !sb) return [];
  var keywords = extractKeywords(query);
  if (keywords.length === 0) return [];
  var scored = [];
  for (var i = 0; i < pressData.length; i++) {
    var item = pressData[i];
    var title = (item.title || '').toLowerCase();
    var score = 0;
    for (var k = 0; k < keywords.length; k++) {
      if (title.includes(keywords[k].toLowerCase())) score++;
    }
    if (score > 0) scored.push({ item: item, score: score });
  }
  scored.sort(function(a, b) { return b.score - a.score; });
  var candidates = scored.slice(0, 4);

  var settled = await Promise.all(candidates.map(async function(r) {
    var item = r.item;
    try {
      // 업로드 직후 메모리에 추가된 항목은 content를 이미 갖고 있다 — 그대로 사용
      if (typeof item.content === 'string' && item.content.trim()) {
        return { item: item, body: item.content };
      }
      if (!item.doc_name) return null;
      // ilike 패턴·PostgREST 구문을 깨는 문자(%,_,쉼표,괄호) 전까지의 제목 앞부분으로 본문 조회
      var m = (item.title || '').match(/^[^%_,()]+/);
      var frag = m ? m[0].trim().substring(0, 20).trim() : '';
      if (frag.length < 4) return null;
      var cr = await sb.from('document_chunks')
        .select('content')
        .eq('doc_name', item.doc_name)
        .ilike('content', '%' + frag + '%')
        .limit(2);
      if (cr.error || !cr.data || cr.data.length === 0) return null;
      var body = cr.data.map(function(c) { return c.content || ''; }).join('\n').trim();
      if (!body) return null;
      return { item: item, body: body };
    } catch(e) {
      console.warn('보도자료 본문 조회 실패(항목 제외):', item.title, e);
      return null;
    }
  }));

  return settled.filter(function(x) { return x; }).map(function(x) {
    var item = x.item;
    var excerpt = x.body.slice(0, 800).trim();  // 관련 본문 발췌 (최대 800자)
    return {
      id: 'press_' + (item.doc_name || '') + '_' + item.date,
      doc_name: item.title,
      doc_category: (item.agency && item.agency !== '기타' ? item.agency : '정부') + ' 보도자료',
      content: '[날짜: ' + item.date + ']\n' + excerpt
    };
  });
}

async function callClaude(userText, onDelta) {
  const { claudeKey } = getConfig();
  if (!claudeKey) throw new Error('Claude API 키가 설정되지 않았습니다. 설정 탭에서 입력해주세요.');

  // 보조 컨텍스트 검색 4종을 먼저 동시에 시작 (조문 RAG와 병렬 실행 — 프롬프트 조합 순서는 아래에서 고정)
  const customP     = searchCustomKnowledge(userText).catch(function(e) { console.warn('추가지식 검색 실패(건너뜀):', e); return ''; });
  const newsP       = fetchRecentNewsContext(userText).catch(function(e) { console.warn('뉴스 컨텍스트 실패(건너뜀):', e); return ''; });
  const lawTrackP   = fetchLawTrackContext().catch(function(e) { console.warn('법령동향 실패(건너뜀):', e); return ''; });
  const kbP         = searchKbSummaries(userText).catch(function(e) { console.warn('법령요약 검색 실패(건너뜀):', e); return []; });
  // 조문 정밀검색 (rag.ts answerAdvisory와 동일 계층) — RAG가 논문·보도자료에 밀려 놓친 근거 조문 보강
  const lawArtP     = searchLawArticles(userText, 5).catch(function(e) { console.warn('조문 정밀검색 실패(건너뜀):', e); return []; });
  // 법령 관계도: 기존 주제명 목록(주제명 분열 방지용) — 실패해도 자문은 정상 진행
  const lawTopicsP  = sb
    ? sb.from('law_graph_nodes').select('name').eq('node_type', 'topic').limit(120)
        .then(function(r) { return (r.data || []).map(function(x) { return x.name; }); })
        .catch(function(e) { console.warn('관계도 주제 목록 조회 실패(건너뜀):', e); return []; })
    : Promise.resolve([]);

  // RAG: 관련 문서 청크 검색 (보도자료는 원본 JSON, 법령은 Supabase)
  lastRagSources = [];
  var ragChunks = [];

  if (isPressQuery(userText)) {
    // 보도자료 질문: 원본 JSON에서 검색
    var pressResults = await searchPressReleases(userText);
    if (pressResults.length > 0) {
      ragChunks = pressResults;
      lastRagSources = pressResults.map(function(c) { return c.doc_name; });
      console.log('보도자료 원본 검색:', pressResults.length + '개');
    }
    // 보도자료이지만 법령도 관련 있을 경우 Supabase도 병행
    var lawChunks = await searchKeywords(userText, true);
    ragChunks = ragChunks.concat(lawChunks).slice(0, 6);
    lastRagSources = ragChunks.map(function(c) { return c.doc_name; });
  } else {
    // 일반 법령·고시 질문: Supabase 검색
    ragChunks = await searchKeywords(userText, false);
    if (ragChunks.length > 0) {
      lastRagSources = ragChunks.map(function(c) { return c.doc_name; });
      console.log('RAG 검색 결과:', ragChunks.length + '개 청크 (' + lastRagSources.join(', ') + ')');
    }
  }

  // 조문 보강 (rag.ts answerAdvisory와 동일 구조) — 정밀검색이 찾은 조문 중 위 RAG에
  // 안 들어온 것을 덧붙인다. RAG는 논문·보도자료도 섞여 정작 근거 조문을 놓치는 일이 있다.
  var lawHits = await lawArtP;
  var haveIds = new Set(ragChunks.map(function(c) { return c.id; }));
  var lawExtra = lawHits.filter(function(h) { return !haveIds.has(h.id); });
  var lawArticleContext = '';
  if (lawExtra.length) {
    lawArticleContext = '\n\n---\n\n[조문 정밀검색 결과 — 질문 의도에 직접 대응하는 조문]\n' +
      '위 RAG 결과에 없더라도 아래 조문이 질문의 핵심 근거일 가능성이 높습니다. 우선 확인하세요:\n\n' +
      lawExtra.map(function(h, i) {
        return '[조문 ' + (i + 1) + '] ' + h.doc_name + (h.article_no ? ' ' + h.article_no : '') + '\n' + h.content;
      }).join('\n\n---\n\n');
    lawExtra.forEach(function(h) {
      if (h.doc_name && lastRagSources.indexOf(h.doc_name) === -1) lastRagSources.push(h.doc_name);
    });
    console.log('조문 정밀검색 보강:', lawExtra.map(function(h) { return h.doc_name + ' ' + (h.article_no || ''); }).join(', '));
  }

  // 시스템 프롬프트에 컨텍스트 조합 (위에서 동시 시작한 검색 결과를 기존 순서 그대로 조립)
  const ragContext    = buildRagContext(ragChunks);
  const customContext = await customP;                            // 팀 내부 추가 지식
  const newsContext   = await newsP;                              // 뉴스 본문+제목
  // 본문 발췌로 실제 반영된 뉴스만 출처에 합친다 (제목 목록 30건은 근거가 아니라 동향 참고용)
  if (lastNewsSources.length) lastRagSources = lastRagSources.concat(lastNewsSources);
  const lawTrackContext = await lawTrackP;                        // 최근 법령 개정·입법예고 동향
  const kbContext     = buildKbContext(await kbP);                // 법령·규제 요약 지식베이스(regulatory-kb, 현행본)
  if (lastKbSources.length) lastRagSources = lastRagSources.concat(lastKbSources);
  const pendingContext = await buildPendingContext(ragChunks);    // 인용 조문의 시행예정 개정본(Phase 3)
  const annexContext  = await buildAnnexContext(ragChunks, userText);  // 인용 조문이 가리키는 별표 원문 (배경역사 #43)
  if (lastAnnexSources.length) lastRagSources = lastRagSources.concat(lastAnnexSources.map(function(s) { return ANNEX_SRC_PREFIX + s; }));
  // 배지용 스냅샷 — lastPendingNotice는 보고서 초안 경로와 공유하는 전역이라,
  // 자문 스트리밍(수 분) 중 보고서를 생성하면 답변 완료 시점엔 다른 값이 들어 있다.
  window._advPendingNotice = lastPendingNotice;
  const webSearchGuide = '\n\n---\n\n[웹 검색 도구 사용 지침]\n해외 규제·제도 비교, 최신 정책 동향 등 위 참조 자료(법령 RAG·추가 지식·뉴스)에 없는 사실 정보가 필요하면 web_search 도구로 확인 후 답변하세요. 특히 "한국 고유", "유일한", "주요국 중 한국만" 등 국가 간 비교 단정 표현은 검색으로 확인하기 전에는 사용하지 마세요. 국내 법령 해석은 RAG 원문을 최우선으로 하고 웹 검색은 보조로만 사용하세요.\n국내 최신 동향(속도·요금·투자·품질평가 수치, 사업 추진 단계 등)은 위 [질문 관련 최신 기사]·[최근 수집 뉴스 동향]을 최우선 근거로 삼고, 웹 검색 결과가 수집 뉴스와 상충하면(수치가 다르거나 시점이 더 과거이면) 수집 뉴스를 따르세요.';
  // 법령 관계도 자동 축적: 답변 말미에 기계용 <lawmap> 블록을 덧붙이게 함 (별도 API 호출 없음 — 출력 몇 줄 추가뿐)
  const lawTopics = await lawTopicsP;
  const lawmapGuide = '\n\n---\n\n[법령 관계도 블록 지침]\n' +
    '이번 질문이 법령·고시·규제 근거가 있는 정책/법령 질문이면, 답변 본문을 모두 마친 뒤 맨 마지막 줄에 아래 형식의 블록을 정확히 한 줄로 출력하세요 (블록 앞뒤에 설명·마크다운 금지):\n' +
    '<lawmap>{"topic":"주제명(2~12자)","description":"주제 한줄 설명","relations":[{"law":"법령·고시명","type":"law|decree|rules|notice|etc","relation":"관계 한줄","basis":"제N조","law_desc":"법령 한줄 설명"}]}</lawmap>\n' +
    '- relations에는 이번 답변에서 실제 근거로 사용한 법령·고시만 포함 (최대 8개). law는 정식 명칭(예: "전파법", "전기통신사업법 시행령").\n' +
    '- 기존 주제명 목록에 같은 의미의 주제가 있으면 새 이름을 만들지 말고 그 이름을 그대로 재사용: ' + (lawTopics.length ? lawTopics.join(', ') : '(아직 없음)') + '\n' +
    '- 보고서 작성 요청, 문서 요약, 잡담, 법령 근거가 등장하지 않는 질문이면 이 블록을 출력하지 마세요.';
  // ── 프롬프트 캐싱(Anthropic prompt caching): 텍스트는 기존 연결 순서 그대로, 캐시 표시만 추가 ──
  // 고정부(SYSTEM_PROMPT + webSearchGuide — 둘 다 정적 문자열)를 별도 블록으로 분리해
  // cache_control:{type:'ephemeral'}를 붙인다. tools→system 순으로 렌더되므로 이 브레이크포인트가
  // web_search 도구 정의 + 고정 지침을 함께 캐시한다(후속 질문 입력비용 ~90% 절감).
  // 가변부(lawmapGuide는 lawTopics 목록이 변함 + RAG·뉴스 등 질문마다 다른 컨텍스트)는
  // 캐시 블록 '뒤'에 둬야 적중한다 — 가변 요소를 고정부 앞·중간에 끼우지 말 것.
  const systemStable   = SYSTEM_PROMPT + webSearchGuide;
  const systemVariable = lawmapGuide + ragContext + lawArticleContext + annexContext + pendingContext + kbContext + customContext + newsContext + lawTrackContext;
  const systemWithRag = [
    { type: 'text', text: systemStable, cache_control: { type: 'ephemeral' } },
    { type: 'text', text: systemVariable }
  ];

  chatHistory.push({ role: 'user', content: userText });

  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'x-api-key': claudeKey,
      'anthropic-version': '2023-06-01',
      'content-type': 'application/json',
      'anthropic-dangerous-direct-browser-access': 'true'
    },
    body: JSON.stringify({
      model: 'claude-sonnet-5',
      // Sonnet 5 토크나이저(동일 텍스트 +30% 토큰)·적응형 추론 여유분 반영해 상향
      max_tokens: 24000,
      // ★ 스트리밍 필수: 웹검색+긴 답변은 응답이 2분 이상 걸려, 비스트리밍 시
      //   ~120초 idle 구간에 브라우저·사내망 프록시가 연결을 끊어 "Failed to fetch"가 났음.
      //   토큰을 실시간 수신하면 연결이 idle가 아니게 되어 끊김이 사라짐. (stream 제거 금지)
      stream: true,
      system: systemWithRag,
      tools: [{ type: 'web_search_20250305', name: 'web_search', max_uses: 3 }],
      messages: chatHistory
    })
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    chatHistory.pop();
    throw new Error(err.error?.message || 'API 오류 (HTTP ' + res.status + ')');
  }

  // ── SSE 스트림 파싱: text_delta 누적 + 웹검색 인용(citations_delta) 수집 ──
  var aiText = '';
  var cited = [];
  var seenUrl = new Set();
  var stopReason = null;
  function addCitation(c) {
    if (c && c.url && !seenUrl.has(c.url)) { seenUrl.add(c.url); cited.push({ url: c.url, title: c.title || c.url }); }
  }

  try {
    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    var buf = '';
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buf += decoder.decode(chunk.value, { stream: true });
      var events = buf.split(/\r?\n\r?\n/);
      buf = events.pop();   // 마지막 미완성 조각은 다음 청크와 합침
      for (var ei = 0; ei < events.length; ei++) {
        var lines = events[ei].split(/\r?\n/);
        for (var li = 0; li < lines.length; li++) {
          var line = lines[li];
          if (line.indexOf('data:') !== 0) continue;
          var payload = line.slice(5).trim();
          if (!payload || payload === '[DONE]') continue;
          var evt;
          try { evt = JSON.parse(payload); } catch(e) { continue; }
          if (evt.type === 'content_block_delta' && evt.delta) {
            if (evt.delta.type === 'text_delta' && evt.delta.text) {
              aiText += evt.delta.text;
              if (typeof onDelta === 'function') {
                // <lawmap> 블록은 기계용 — 스트리밍 중 화면에 노출되지 않게 잘라서 전달
                var lmCut = aiText.indexOf('<lawmap');
                onDelta(lmCut === -1 ? aiText : aiText.slice(0, lmCut));
              }
            } else if (evt.delta.type === 'citations_delta' && evt.delta.citation) {
              addCitation(evt.delta.citation);
            }
          } else if (evt.type === 'content_block_start' && evt.content_block) {
            (evt.content_block.citations || []).forEach(addCitation);
          } else if (evt.type === 'message_delta' && evt.delta && evt.delta.stop_reason) {
            stopReason = evt.delta.stop_reason;
          } else if (evt.type === 'error') {
            throw new Error((evt.error && evt.error.message) || '스트리밍 오류');
          }
        }
      }
    }
  } catch(streamErr) {
    chatHistory.pop();
    throw streamErr;
  }

  // <lawmap> 블록 추출·제거 (관계도 자동 축적 — 화면·히스토리에는 블록 없이 저장)
  lastLawmapData = null;
  var lmMatch = aiText.match(/<lawmap>\s*([\s\S]*?)\s*<\/lawmap>/);
  if (lmMatch) {
    try { lastLawmapData = JSON.parse(lmMatch[1]); } catch(e) { console.warn('lawmap 블록 파싱 실패(무시):', e); }
  }
  // 닫는 태그가 잘린 미완성 블록까지 포함해 화면 텍스트에서 제거
  aiText = aiText.replace(/<lawmap>[\s\S]*?<\/lawmap>/g, '').replace(/<lawmap>[\s\S]*$/, '').replace(/\s+$/, '');

  chatHistory.push({ role: 'assistant', content: aiText });
  // 웹 검색 출처 표시
  if (cited.length > 0) {
    aiText += '\n\n---\n\n**🌐 웹 검색 출처:**\n\n' + cited.slice(0, 5).map(function(c) {
      return '- [' + c.title.replace(/[\[\]]/g, '') + '](' + c.url + ')';
    }).join('\n');
  }
  // 길이 제한으로 잘린 경우 안내 (히스토리에는 원문만 저장 → "계속" 입력 시 이어서 생성)
  if (stopReason === 'max_tokens') {
    aiText += '\n\n---\n\n> ⚠️ 답변이 길이 제한으로 잘렸습니다. **"계속"**이라고 입력하면 이어서 답변합니다.';
  }
  return aiText;
}

// ════════════════════════════════════════════
//  Chat UI
// ════════════════════════════════════════════
function renderMd(text) {
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const inline = s => esc(s)
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`(.+?)`/g, '<code>$1</code>');
  const splitRow = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());

  const lines = text.split('\n');
  let html = '', para = [], i = 0;
  const flush = () => {
    if (para.length) { html += '<p>' + para.map(inline).join('<br>') + '</p>'; para = []; }
  };

  while (i < lines.length) {
    const t = lines[i].trim();

    // 펜스 코드블록 (``` 또는 ~~~) — 내부는 마크다운 해석 없이 원문 보존(박스 다이어그램 정렬 유지)
    const fence = t.match(/^(```|~~~)/);
    if (fence) {
      flush();
      i++;
      let code = '';
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) {
        code += esc(lines[i]) + '\n';
        i++;
      }
      i++; // 닫는 펜스 줄 건너뛰기
      html += '<pre><code>' + code.replace(/\n$/, '') + '</code></pre>';
      continue;
    }

    // 표: |헤더| 다음 줄이 |---|---| 구분선
    if (t.startsWith('|') && i + 1 < lines.length && /^\|?[\s:|-]+\|?$/.test(lines[i + 1].trim()) && lines[i + 1].includes('-')) {
      flush();
      let head = splitRow(t);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(splitRow(lines[i]));
        i++;
      }
      // 웹에서 긁어온 표는 원본의 rowspan이 풀리면서 ①어느 행에서도 안 쓰는 빈 열과
      // ②내용이 첫 칸에만 들어간 '이어지는 행'을 남긴다(중앙전파관리소 등록요건 표).
      // 빈 열을 그대로 두면 표가 가로로 짓눌리고, 이어지는 행은 내용이 엉뚱한 열
      // 머리글(예: '구분') 아래로 들어가 규정을 잘못 읽게 만든다. (배경역사 #42)
      const used = head.map(function(h, c) {
        return (h || '').trim() !== '' || rows.some(function(r) { return (r[c] || '').trim() !== ''; });
      });
      const keep = head.map(function(_, c) { return c; }).filter(function(c) { return used[c]; });
      head = keep.map(function(c) { return head[c]; });
      let body = '';
      rows.forEach(function(r) {
        const cells = keep.map(function(c) { return (r[c] || '').trim(); });
        // 첫 칸에만 내용이 있는 행 = 앞 행에서 이어지는 내용. 열을 배정하지 않고
        // 통칸으로 깔아, 없는 열 구분을 지어내지 않는다.
        if (head.length > 1 && cells[0] && cells.slice(1).every(function(x) { return !x; })) {
          body += '<tr><td colspan="' + head.length + '" class="md-cont">' + inline(cells[0]) + '</td></tr>';
          return;
        }
        body += '<tr>' + cells.map(function(x) { return '<td>' + inline(x) + '</td>'; }).join('') + '</tr>';
      });
      html += '<div class="md-table-wrap"><table><thead><tr>' +
        head.map(h => '<th>' + inline(h) + '</th>').join('') +
        '</tr></thead><tbody>' + body + '</tbody></table></div>';
      continue;
    }

    // 제목 (# ~ ####)
    const h = t.match(/^(#{1,4})\s+(.*)/);
    if (h) {
      flush();
      const lv = Math.min(h[1].length + 2, 6);
      html += `<h${lv}>${inline(h[2])}</h${lv}>`;
      i++; continue;
    }

    // 구분선
    if (/^(-{3,}|\*{3,})$/.test(t)) { flush(); html += '<hr>'; i++; continue; }

    // 글머리 목록
    if (/^[-*]\s+/.test(t)) {
      flush();
      let items = '';
      while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
        items += '<li>' + inline(lines[i].trim().replace(/^[-*]\s+/, '')) + '</li>';
        i++;
      }
      html += '<ul>' + items + '</ul>';
      continue;
    }

    // 번호 목록
    if (/^\d+[.)]\s+/.test(t)) {
      flush();
      const start = parseInt(t, 10);
      let items = '';
      while (i < lines.length && /^\d+[.)]\s+/.test(lines[i].trim())) {
        items += '<li>' + inline(lines[i].trim().replace(/^\d+[.)]\s+/, '')) + '</li>';
        i++;
      }
      html += `<ol start="${start}">` + items + '</ol>';
      continue;
    }

    if (t === '') { flush(); i++; continue; }

    para.push(lines[i]);
    i++;
  }
  flush();
  return html;
}

function appendMsg(role, text) {
  const area = document.getElementById('chat-area');
  const div = document.createElement('div');
  div.className = `msg msg-${role}`;
  if (role === 'ai') {
    div.innerHTML = `<div class="msg-name">전파정책 전문가 AI</div>${renderMd(text)}`;
  } else {
    div.textContent = text;
  }
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
  return div;
}

function appendLoading() {
  const area = document.getElementById('chat-area');
  const div = document.createElement('div');
  div.className = 'msg-loading';
  div.innerHTML = '<div class="dot-anim"></div><div class="dot-anim"></div><div class="dot-anim"></div>';
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
  return div;
}

function detectCategory(t) {
  if (/주파수|할당|경매|분배|재배치/.test(t)) return '주파수';
  if (/전자파|SAR|EMC|인체|흡수율/.test(t)) return '전자파';
  if (/적합성평가|기자재|인증|시험기관/.test(t)) return '적합성평가';
  if (/ITU|WRC|IMT|6G|5G|국제/.test(t)) return 'ITU-R';
  if (/기술기준|무선설비|무선국|안테나/.test(t)) return '기술기준';
  return '일반';
}

// ════════════════════════════════════════════
//  자문 이력 (chat_logs 열람)
// ════════════════════════════════════════════
function chEsc(s) { return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function chDate(iso) {
  var d = new Date(iso);
  var p = function(n) { return (n < 10 ? '0' : '') + n; };
  return d.getFullYear() + '-' + p(d.getMonth()+1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
}

async function openChatHistory() {
  var modal = document.getElementById('chat-history-modal');
  var body = document.getElementById('chat-history-body');
  modal.style.display = 'flex';
  body.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px">불러오는 중...</div>';
  if (!sb) { body.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px">Supabase 연결 없음</div>'; return; }
  try {
    var resp = await sb.from('chat_logs')
      .select('id, question, category, created_at')
      .order('created_at', { ascending: false })
      .limit(100);
    if (resp.error) throw resp.error;
    var data = resp.data || [];
    if (data.length === 0) {
      body.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px">저장된 자문 이력이 없습니다.</div>';
      return;
    }
    body.innerHTML = data.map(function(item) {
      return '<div class="card" style="cursor:pointer;margin-bottom:8px;padding:12px 14px;display:flex;align-items:flex-start;gap:8px" onclick="viewChatHistoryItem(\'' + item.id + '\')">' +
        '<div style="flex:1;min-width:0">' +
          '<div style="font-size:13px;font-weight:500;color:var(--text-primary);line-height:1.5">' + chEsc(item.question) + '</div>' +
          '<div style="font-size:11px;color:var(--text-tertiary);margin-top:5px;display:flex;align-items:center;gap:8px">' +
            '<span class="rag-tag">' + chEsc(item.category || '일반') + '</span>' + chDate(item.created_at) +
          '</div>' +
        '</div>' +
        '<button class="btn" title="이력 삭제" style="padding:4px 8px;flex-shrink:0;color:var(--text-tertiary)" onclick="event.stopPropagation();deleteChatHistoryItem(\'' + item.id + '\', this)"><i class="ti ti-trash"></i></button>' +
      '</div>';
    }).join('');
    body.scrollTop = 0;
  } catch(e) {
    body.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px">이력 조회 실패: ' + chEsc(e.message) + '</div>';
  }
}

// ── 자문 상세 내보내기 (MD / Word / PDF) ──
//   viewChatHistoryItem이 현재 상세를 _chatDetail에 저장 → 아래 함수들이 전체 내용으로 내보냄
//   (기존 프린트는 모달의 보이는 부분만 인쇄되던 문제 해결)
var _chatDetail = null;

function _chatExportName(ext) {
  var d = _chatDetail || {};
  var dt = d.created_at ? new Date(d.created_at) : new Date();
  var p = function(n) { return (n < 10 ? '0' : '') + n; };
  var stamp = dt.getFullYear() + p(dt.getMonth() + 1) + p(dt.getDate()) + '_' + p(dt.getHours()) + p(dt.getMinutes());
  var t = (d.question || '자문').replace(/[\\/:*?"<>|\r\n\t]+/g, ' ').trim().slice(0, 30).trim();
  return '자문_' + stamp + (t ? '_' + t : '') + '.' + ext;
}

function _chatDownload(blob, fn) {
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url; a.download = fn;
  document.body.appendChild(a); a.click();
  setTimeout(function() { document.body.removeChild(a); URL.revokeObjectURL(url); }, 100);
}

function _chatExportStyle() {
  return '<style>' +
    'body{font-family:"Malgun Gothic","맑은 고딕",sans-serif;line-height:1.65;color:#1a1a1a;font-size:13px;max-width:780px;margin:28px auto;padding:0 18px}' +
    'h1.ex-q{font-size:18px;margin:0 0 4px;line-height:1.4}h2,h3,h4{margin:18px 0 6px}' +
    '.ex-meta{font-size:12px;color:#666;margin:0 0 14px}.ex-src{margin-top:18px;font-size:12px;color:#555}' +
    'table{border-collapse:collapse;width:100%;margin:10px 0}th,td{border:1px solid #bbb;padding:6px 9px;font-size:12px;text-align:left;vertical-align:top}th{background:#f2f2f2}' +
    'hr{border:none;border-top:1px solid #ddd;margin:14px 0}code{background:#f4f4f4;padding:1px 4px;border-radius:3px;font-size:12px}' +
    'pre{background:#f4f4f4;padding:10px 12px;border-radius:6px;overflow-x:auto;margin:8px 0}pre code{display:block;background:none;padding:0;white-space:pre;font-size:12px;line-height:1.5}' +
    'ul,ol{margin:6px 0 6px 4px;padding-left:20px}li{margin:2px 0}a{color:#1a56db}' +
    '</style>';
}

function _chatContentHtml() {
  var d = _chatDetail || {};
  // 내보내기(PDF·Word)는 화면과 달리 6개 제한 없이 전부 남긴다 — 문서는 근거를 온전히 보존해야 함
  var xs = splitSources(d.sources);
  var srcHtml =
    (xs.laws.length ? '<p class="ex-src"><b>참조 법령·문서:</b> ' + xs.laws.map(chEsc).join(', ') + '</p>' : '') +
    (xs.annex.length ? '<p class="ex-src"><b>참조 별표:</b> ' + xs.annex.map(function(s) { return chEsc(stripAnnexPrefix(s)); }).join(', ') + '</p>' : '') +
    (xs.kb.length ? '<p class="ex-src"><b>참조 요약·실무:</b> ' + xs.kb.map(function(s) { return chEsc(stripKbPrefix(s)); }).join(', ') + '</p>' : '') +
    (xs.news.length ? '<p class="ex-src"><b>참조 뉴스:</b> ' + xs.news.map(function(s) { return chEsc(stripNewsPrefix(s)); }).join(', ') + '</p>' : '');
  return '<h1 class="ex-q">' + chEsc(d.question || '') + '</h1>' +
    '<p class="ex-meta">분류: ' + chEsc(d.category || '일반') + ' &nbsp;|&nbsp; ' + chDate(d.created_at) + '</p>' +
    '<hr>' + renderMd(d.answer || '') + srcHtml;
}

function exportChatMd() {
  if (!_chatDetail) return;
  var d = _chatDetail;
  var md = '# ' + (d.question || '') + '\n\n';
  md += '- 분류: ' + (d.category || '일반') + '\n';
  md += '- 일시: ' + chDate(d.created_at) + '\n\n---\n\n';
  md += (d.answer || '') + '\n';
  var ms = splitSources(d.sources);
  if (ms.laws.length) md += '\n---\n\n**참조 법령·문서:** ' + ms.laws.join(', ') + '\n';
  if (ms.annex.length) md += '\n**참조 별표:** ' + ms.annex.map(stripAnnexPrefix).join(', ') + '\n';
  if (ms.kb.length) md += '\n**참조 요약·실무:** ' + ms.kb.map(stripKbPrefix).join(', ') + '\n';
  if (ms.news.length) md += '\n**참조 뉴스:** ' + ms.news.map(stripNewsPrefix).join(', ') + '\n';
  _chatDownload(new Blob([md], { type: 'text/markdown;charset=utf-8' }), _chatExportName('md'));
}

function exportChatPdf() {
  if (!_chatDetail) return;
  var w = window.open('', '_blank');
  if (!w) { alert('팝업이 차단되어 PDF 인쇄 창을 열 수 없습니다. 팝업을 허용한 뒤 다시 시도하세요.'); return; }
  w.document.write('<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>' +
    chEsc(_chatDetail.question || '자문') + '</title>' + _chatExportStyle() + '</head><body>' +
    _chatContentHtml() + '</body></html>');
  w.document.close(); w.focus();
  setTimeout(function() { try { w.print(); } catch(e) {} }, 500);
}

async function exportChatDocx() {
  if (!_chatDetail) return;
  if (!window.JSZip) { alert('Word 변환 라이브러리(JSZip)가 로드되지 않았습니다.'); return; }
  var html = '<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">' +
    '<head><meta charset="utf-8">' + _chatExportStyle() + '</head><body>' + _chatContentHtml() + '</body></html>';
  try {
    var zip = new JSZip();
    zip.file('[Content_Types].xml',
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
      '<Default Extension="xml" ContentType="application/xml"/>' +
      '<Default Extension="html" ContentType="text/html"/>' +
      '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
      '</Types>');
    zip.folder('_rels').file('.rels',
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
      '</Relationships>');
    var wf = zip.folder('word');
    wf.file('afchunk.html', html);
    wf.folder('_rels').file('document.xml.rels',
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="htmlChunk" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/aFChunk" Target="afchunk.html"/>' +
      '</Relationships>');
    wf.file('document.xml',
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
      '<w:body><w:altChunk r:id="htmlChunk"/>' +
      '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>' +
      '</w:body></w:document>');
    var blob = await zip.generateAsync({ type: 'blob', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
    _chatDownload(blob, _chatExportName('docx'));
  } catch (e) {
    alert('Word 저장 실패: ' + e.message);
  }
}

async function viewChatHistoryItem(id) {
  var body = document.getElementById('chat-history-body');
  body.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px">불러오는 중...</div>';
  try {
    var resp = await sb.from('chat_logs')
      .select('question, answer, category, created_at, sources')
      .eq('id', id).single();
    if (resp.error) throw resp.error;
    var row = resp.data;
    var srcs = row.sources;
    if (typeof srcs === 'string') {
      try { srcs = JSON.parse(srcs); } catch(e) { srcs = srcs ? [srcs] : []; }
    }
    var sp = splitSources(Array.isArray(srcs) ? srcs : []);
    var srcHtml = '';
    if (sp.laws.length > 0) {
      srcHtml += '<div class="rag-sources" style="margin-top:12px"><i class="ti ti-book"></i> 참조 법령·문서: ' +
        sourceTagsHtml(sp.laws, 6) + '</div>';
    }
    if (sp.annex.length > 0) {
      srcHtml += '<div class="rag-sources" style="margin-top:6px"><i class="ti ti-table"></i> 참조 별표: ' +
        annexTagsHtml(sp.annex) + '</div>';
    }
    if (sp.kb.length > 0) {
      srcHtml += '<div class="rag-sources" style="margin-top:6px"><i class="ti ti-clipboard-text"></i> 참조 요약·실무: ' +
        kbTagsHtml(sp.kb) + '</div>';
    }
    if (sp.news.length > 0) {
      srcHtml += '<div class="rag-sources" style="margin-top:6px"><i class="ti ti-news"></i> 참조 뉴스: ' +
        newsTagsHtml(sp.news) + '</div>';
    }
    _chatDetail = { question: row.question || '', answer: row.answer || '', category: row.category || '일반', created_at: row.created_at, sources: sp.laws.concat(sp.annex, sp.kb, sp.news) };
    body.innerHTML =
      '<button class="btn" onclick="openChatHistory()" style="margin-bottom:12px"><i class="ti ti-arrow-left"></i>목록으로</button>' +
      '<button class="btn" onclick="deleteChatHistoryItem(\'' + id + '\', null)" style="margin-bottom:12px;margin-left:8px;color:#d04545"><i class="ti ti-trash"></i>삭제</button>' +
      '<button class="btn" onclick="exportChatMd()" title="Markdown(.md)으로 저장" style="margin-bottom:12px;margin-left:8px"><i class="ti ti-download"></i>MD</button>' +
      '<button class="btn" onclick="exportChatDocx()" title="Word(.docx)로 저장" style="margin-bottom:12px;margin-left:8px"><i class="ti ti-download"></i>Word</button>' +
      '<button class="btn" onclick="exportChatPdf()" title="PDF로 인쇄/저장 (전체 내용)" style="margin-bottom:12px;margin-left:8px"><i class="ti ti-download"></i>PDF</button>' +
      '<div style="font-size:13px;font-weight:600;color:var(--text-primary);line-height:1.5">' + chEsc(row.question) + '</div>' +
      '<div style="font-size:11px;color:var(--text-tertiary);margin:5px 0 12px"><span class="rag-tag">' + chEsc(row.category || '일반') + '</span> ' + chDate(row.created_at) + '</div>' +
      '<div class="msg msg-ai" style="max-width:100%">' + renderMd(row.answer || '') + '</div>' + srcHtml;
    body.scrollTop = 0;
  } catch(e) {
    body.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px">조회 실패: ' + chEsc(e.message) + '</div>';
  }
}

function closeChatHistory() {
  document.getElementById('chat-history-modal').style.display = 'none';
}

// 자문 이력 삭제 — 목록 카드의 휴지통 버튼(btn 전달) / 상세 보기의 삭제 버튼(btn=null)
async function deleteChatHistoryItem(id, btn) {
  if (!confirm('이 자문 이력을 삭제할까요?')) return;
  var pwd = _ensureAdminPwd();
  if (!pwd) return;
  try {
    // chat_logs도 RLS 켜짐 + DELETE 정책 없음 → 직접 delete()는 조용히 실패한다.
    // 서버 검증 RPC + 삭제 행수 확인. (#48)
    var resp = await sb.rpc('admin_delete_chat_log', { p_id: id, p_pwd: pwd });
    if (resp.error) { _handleAdminRpcError(resp.error, '삭제'); return; }
    if (!resp.data) { alert('삭제된 이력이 없습니다. 이미 삭제된 항목일 수 있습니다.'); return; }
    if (btn && btn.closest) {
      var card = btn.closest('.card');
      if (card) card.remove();
      var body = document.getElementById('chat-history-body');
      if (body && !body.querySelector('.card')) {
        body.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px">저장된 자문 이력이 없습니다.</div>';
      }
    } else {
      openChatHistory(); // 상세 보기에서 삭제 → 목록으로 복귀
    }
  } catch(e) {
    alert('이력 삭제 실패: ' + e.message);
  }
}

// 홈 대시보드 최근 자문 카드 → 이력 모달 열고 바로 상세 표시
function openChatHistoryDetail(id) {
  document.getElementById('chat-history-modal').style.display = 'flex';
  viewChatHistoryItem(id);
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const btn = document.getElementById('send-btn');
  const text = input.value.trim();
  if (!text || isSending) return;

  isSending = true;
  input.disabled = true;
  btn.disabled = true;
  input.value = '';

  appendMsg('user', text);
  const loader = appendLoading();
  const chatArea = document.getElementById('chat-area');

  try {
    // 스트리밍: 첫 토큰 도착 시 로더 제거하고 답변 말풍선을 실시간 갱신(렌더 쓰로틀)
    let streamEl = null;
    let lastRender = 0;
    const onDelta = function(partial) {
      if (!streamEl) { loader.remove(); streamEl = appendMsg('ai', ''); }
      const now = Date.now();
      if (now - lastRender < 120) return;
      lastRender = now;
      streamEl.innerHTML = '<div class="msg-name">전파정책 전문가 AI</div>' + renderMd(partial);
      chatArea.scrollTop = chatArea.scrollHeight;
    };
    const answer = await callClaude(text, onDelta);
    if (!streamEl) { loader.remove(); streamEl = appendMsg('ai', ''); }
    const msgEl = streamEl;
    msgEl.innerHTML = '<div class="msg-name">전파정책 전문가 AI</div>' + renderMd(answer);
    chatArea.scrollTop = chatArea.scrollHeight;

    // RAG 출처 표시 — 법령·문서와 뉴스는 근거 성격이 달라 한 배지에 섞지 않는다
    const _advSrc = splitSources(lastRagSources);
    if (_advSrc.laws.length > 0) {
      const srcDiv = document.createElement('div');
      srcDiv.className = 'rag-sources';
      srcDiv.innerHTML = '<i class="ti ti-database"></i>참조 문서: ' + sourceTagsHtml(_advSrc.laws, 6);
      msgEl.appendChild(srcDiv);
    }
    // 별표는 금액·요율의 정본이라 조문 배지와 따로 보여야, 표를 실제로 근거 삼았는지 바로 보인다
    if (_advSrc.annex.length > 0) {
      const anDiv = document.createElement('div');
      anDiv.className = 'rag-sources';
      anDiv.innerHTML = '<i class="ti ti-table"></i>참조 별표: ' + annexTagsHtml(_advSrc.annex);
      msgEl.appendChild(anDiv);
    }
    if (_advSrc.kb.length > 0) {
      const kbDiv = document.createElement('div');
      kbDiv.className = 'rag-sources';
      kbDiv.innerHTML = '<i class="ti ti-clipboard-text"></i>참조 요약·실무: ' + kbTagsHtml(_advSrc.kb);
      msgEl.appendChild(kbDiv);
    }
    if (_advSrc.news.length > 0) {
      const nwDiv = document.createElement('div');
      nwDiv.className = 'rag-sources';
      nwDiv.innerHTML = '<i class="ti ti-news"></i>참조 뉴스: ' + newsTagsHtml(_advSrc.news);
      msgEl.appendChild(nwDiv);
    }

    // 시행예정 개정본이 컨텍스트에 들어갔음을 가시화 — 답변이 현행 기준임을 명확히 하기 위함
    if (window._advPendingNotice && window._advPendingNotice.length) {
      const seen = {};
      const items = window._advPendingNotice.filter(function(p) {
        const k = p.law_name + '|' + p.enf_date;
        if (seen[k]) return false; seen[k] = 1; return true;
      });
      const pvDiv = document.createElement('div');
      pvDiv.className = 'rag-sources';
      pvDiv.innerHTML = '<i class="ti ti-calendar-clock"></i>시행 예정 반영: ' + items.map(function(p) {
        const d = p.enf_date || '';
        return '<span class="rag-tag">' + chEsc(p.law_name) + ' '
          + (d.length === 8 ? d.slice(2,4)+'.'+d.slice(4,6)+'.'+d.slice(6,8) : chEsc(d)) + '</span>';
      }).join(' ');
      msgEl.appendChild(pvDiv);
    }

    // 법령 관계도 자동 축적: 답변의 <lawmap> 블록 → DB 저장 + 답변 밑 미니 관계도 표시 (추가 API 호출 없음)
    if (lastLawmapData && lastLawmapData.topic && Array.isArray(lastLawmapData.relations) && lastLawmapData.relations.length > 0) {
      const lmData = lastLawmapData;
      saveLawmapData(lmData, 'ai')
        .then(function() { _lawMapLoaded = false; })  // 다음 관계도 탭 진입 시 새로 로드
        .catch(function(e) { console.warn('법령 관계도 저장 실패(답변은 정상):', e); });
      const lmDiv = document.createElement('div');
      lmDiv.className = 'lawmap-mini';
      lmDiv.innerHTML =
        '<div class="lawmap-mini-head"><i class="ti ti-topology-star-3"></i> 이 답변의 법령 관계도 <span>— 관계망에 자동 반영됨</span></div>' +
        renderMiniLawMap(lmData.topic, lmData.relations) +
        '<div class="lawmap-mini-link">관계도 탭에서 크게 보기 →</div>';
      lmDiv.addEventListener('click', function() { goLawMapTopicByName(lmData.topic); });
      msgEl.appendChild(lmDiv);
    }

    if (sb) {
      try {
        await sb.from('chat_logs').insert({
          question: text,
          answer: answer,
          category: detectCategory(text),
          sources: lastRagSources
        });
      } catch(e) { console.warn('자문 이력(chat_logs) 저장 실패(답변은 정상):', e); }
      refreshDashboard();
    }
  } catch(e) {
    loader.remove();
    appendMsg('ai', '⚠️ ' + e.message);
  } finally {
    isSending = false;
    input.disabled = false;
    btn.disabled = false;
    input.focus();
  }
}

function askQ(q) {
  go('chat', document.querySelectorAll('.nav-item')[1]);
  document.getElementById('chat-input').value = q;
  setTimeout(sendChat, 150);
}

// ════════════════════════════════════════════
//  Dashboard
// ════════════════════════════════════════════
function smartRefresh() {
  // 패널 활성화는 inline style이 아니라 .active 클래스다 — 옛 선택자는 항상 실패해
  // 어느 페이지에서든 뉴스만 갱신되던 버그(그래서 패널마다 중복 새로고침 버튼이 생겼었다). (#54)
  var active = document.querySelector('.panel.active');
  var id = active ? active.id : 'panel-news';
  var map = {
    'panel-news':     function() { loadNews(); },
    'panel-briefing': function() { loadBriefing(); },
    'panel-terms':    function() { loadTerms && loadTerms(); },
    'panel-press':    function() { loadPressJSON(); },
    'panel-law':      function() { loadKbDocs(true); },
    'panel-guide':    function() { loadGuideDocs(true); },
    'panel-lawmap':   function() { loadLawMap(true); },
    'panel-assembly': function() { loadAssemblyBills(true); },
    'panel-minutes':  function() { loadAssemblyMinutes(true); },
    'panel-overseas': function() { loadOverseasNews(true); },
    'panel-lawtrack': function() { loadLawTrack(true); },
    'panel-diff':     function() { loadLawDiffs(true); },
    'panel-opsstatus': function() { typeof loadOpsStatus === 'function' && loadOpsStatus(); },
    'panel-settings': function() { typeof loadSettingsUI === 'function' && loadSettingsUI(); },
  };
  var fn = map[id];
  if (fn) fn();
  if (typeof refreshOpsLight === 'function') refreshOpsLight();   // 상단바 상태등도 함께 갱신
}

async function refreshDashboard() {
  if (!sb) return;
  try {
    const now = new Date();
    const firstDay = new Date(now.getFullYear(), now.getMonth(), 1).toISOString();

    const { count: consultCount } = await sb.from('chat_logs')
      .select('*', { count: 'exact', head: true })
      .gte('created_at', firstDay);

    const { count: newsCount } = await sb.from('news_feed')
      .select('*', { count: 'exact', head: true })
      .eq('is_read', false);

    document.getElementById('stat-consult').textContent = consultCount ?? 0;
    document.getElementById('stat-consult-sub').textContent = '이번달 AI 자문 횟수';
    document.getElementById('stat-news').textContent = newsCount ?? 0;
    document.getElementById('stat-news-sub').textContent = '미확인 뉴스';

    const { data: logs } = await sb.from('chat_logs')
      .select('id, question, category, created_at')
      .order('created_at', { ascending: false })
      .limit(3);

    if (logs && logs.length > 0) {
      const container = document.getElementById('recent-logs');
      container.innerHTML = logs.map(l => {
        const date = new Date(l.created_at).toLocaleDateString('ko-KR', {month:'2-digit',day:'2-digit'});
        const catColor = { '주파수':'badge-purple','전자파':'badge-blue','ITU-R':'badge-blue','적합성평가':'badge-teal','기술기준':'badge-teal','일반':'badge-amber' };
        return `<div class="card" style="cursor:pointer;margin-bottom:8px" onclick="openChatHistoryDetail('${l.id}')">
          <div class="card-header"><span class="card-title" style="font-size:12px">${l.question.slice(0,40)}${l.question.length>40?'…':''}</span><span class="badge ${catColor[l.category]||'badge-amber'}">${l.category||'일반'}</span></div>
          <div class="card-meta"><i class="ti ti-calendar"></i>${date}</div>
        </div>`;
      }).join('');
    }
  } catch(e) { console.warn('Dashboard refresh error:', e); }
}

// ════════════════════════════════════════════
//  News — 팀 중요도 기반 분류 & 액션 아이템 패널
// ════════════════════════════════════════════
let currentNewsFilter = '전체';
let currentNewsSourceType = 'gov'; // 'gov' | 'media' | 'all'
let newsDataCache = [];      // 전체 로드된 뉴스 캐시
let selectedNewsId = null;   // 현재 선택된 뉴스 id
let currentNewsSearch = '';  // 뉴스 검색어 (클라이언트 필터 — 중요도와 AND 결합)
// 6개 기관 자동 수집 확장(2026-08)에 맞춰 접두 추가 — '방송통신위원회 보도자료' 등은
// 기존 '방통위' 접두와 별개 문자열이라 명시해야 정부 탭에 잡힌다.
var GOV_SOURCE_PREFIXES = ['국립전파연구원', '과기정통부', '방통위', '방송통신위원회', '중앙전파관리소', 'ETRI', 'KISDI'];
// 해외 규제기관 5종 (2026-08) — category='해외' 행과 함께 정부 보도자료·공지사항 탭에 포함.
// 칩은 '해외' 통합 1개만 노출한다(기관별 칩을 늘리면 칩 과밀).
var OVERSEAS_SOURCE_PREFIXES = ['FCC', 'Ofcom', 'BEREC', '日총무성', 'ITU'];

// gov 탭 포함 판정 — source 접두(국내 7 + 해외 5) 또는 category='해외'
function isGovFeedItem(n) {
  var s = (n && n.source) || '';
  if (n && n.category === '해외') return true;
  if (OVERSEAS_SOURCE_PREFIXES.some(function(p) { return s.startsWith(p); })) return true;
  return GOV_SOURCE_PREFIXES.some(function(p) { return s.startsWith(p); });
}

// ── 정부 보도자료 기관 필터 (모니터링 > 정부 보도자료·공지사항 상단 칩) ──
var currentGovAgency = '전체';
var GOV_AGENCY_TABS = ['전체', '과기정통부', '전파연구원', '방통위', '전파관리소', 'ETRI', 'KISDI', '해외', '기타'];

// news_feed.source 접두 → 기관 슬러그 매핑 (클라이언트 필터 전용)
function govAgencyOf(source, category) {
  var s = source || '';
  if (category === '해외' || OVERSEAS_SOURCE_PREFIXES.some(function(p) { return s.indexOf(p) === 0; })) return '해외';
  if (s.indexOf('과기정통부') === 0) return '과기정통부';
  if (s.indexOf('국립전파연구원') === 0) return '전파연구원';
  if (s.indexOf('방송통신위원회') === 0 || s.indexOf('방통위') === 0) return '방통위';
  if (s.indexOf('중앙전파관리소') === 0) return '전파관리소';
  if (s.indexOf('ETRI') === 0) return 'ETRI';
  if (s.indexOf('KISDI') === 0) return 'KISDI';
  return '기타';
}

function renderGovAgencyTabs(govData) {
  var el = document.getElementById('gov-agency-tabs');
  if (!el) return;
  el.style.display = '';  // 인라인 none 제거 → .tag-list 클래스 규칙(데스크톱 flex/모바일 숨김) 적용
  var counts = {};
  (govData || []).forEach(function(n) { var a = govAgencyOf(n.source, n.category); counts[a] = (counts[a] || 0) + 1; });
  el.innerHTML = GOV_AGENCY_TABS.map(function(a) {
    var cnt = (a === '전체') ? (govData || []).length : (counts[a] || 0);
    return '<span class="tag' + (currentGovAgency === a ? ' selected' : '') + '" ' +
      'onclick="filterGovAgency(\'' + a + '\')">' + a + (cnt ? ' ' + cnt : '') + '</span>';
  }).join('');
}

function hideGovAgencyTabs() {
  var el = document.getElementById('gov-agency-tabs');
  if (el) el.style.display = 'none';
}

function filterGovAgency(agency) {
  currentGovAgency = agency;
  renderNewsList();
}

function closeNewsDetail() {
  selectedNewsId = null;
  var panel = document.getElementById('news-detail-panel');
  if (panel) panel.style.display = 'none';
}

// ── 중요도 분류 규칙 ──────────────────────────────────────
// SKT Comm센터 기술정책팀 KPI 기준으로 키워드 매핑
var IMPORTANCE_RULES = {
  긴급: {
    color: '#ef4444', bg: 'rgba(239,68,68,0.08)', border: '2px solid #ef4444',
    label: '🔴 중요', badge_class: 'badge-red',
    desc: '즉각 임원 보고 및 대관 대응 필요',
    keywords: ['취소','회수','처분','반납','강제','의무화','시정명령','이행강제','과징금',
               '청문','위반','제재','즉시','긴급','주파수 반납','할당 취소','할당취소',
               '재할당 거부','시행 완료','고시 시행','법령 시행','효력 발생'],
    response_guide: [
      '즉시 현황 파악 — 해당 주파수·허가 영향 범위 확인',
      '법무팀 협의 — 법적 대응 근거 검토',
      '임원 보고서 작성 (1p 이내, 배경·쟁점·리스크·대응방향)',
      '정부 회신 또는 의견서 준비',
      '유관부서(네트워크·재무·법무) 긴급 공유'
    ]
  },
  보통: {
    color: '#f59e0b', bg: 'rgba(245,158,11,0.08)', border: '2px solid #f59e0b',
    label: '🟡 보통', badge_class: 'badge-amber',
    desc: '당일~금주 내 검토 및 팀 공유 필요',
    keywords: ['행정예고','입법예고','개정안','발의','공청회','계획 확정','추진 계획','논의',
               '심의','의견수렴','고시 개정','시행령 개정','정책 발표','방침','예정','추진',
               '제정안','신설','협의 중','검토 중','연구반','태스크포스','TF','로드맵'],
    response_guide: [
      '내용 검토 및 1p 요약 작성',
      '팀 내부 공유 (채널/메일)',
      '검토의견서 또는 입장문 준비',
      '유관부서 사전 협의 여부 판단',
      '향후 일정 캘린더 등록'
    ]
  },
  참고: {
    color: '#22c55e', bg: 'rgba(34,197,94,0.06)', border: '1px solid var(--border)',
    label: '🟢 참고', badge_class: 'badge-teal',
    desc: '동향 파악 — 필요시 브리핑 반영',
    keywords: [],   // 위 두 기준에 해당하지 않으면 참고
    response_guide: [
      '내용 확인 및 키워드 태그 정리',
      '필요시 모닝 브리핑 반영',
      '지식 DB 저장 (장기 트렌드 추적)'
    ]
  }
};

// ── SKT 관련 주제 키워드 (공공 와이파이 / 이동통신 품질·장비 / 전파·전자파·무선국·주파수)
var SKT_RELEVANT_TOPICS = [
  // 공공 와이파이
  '공공 와이파이', '공공와이파이', '공공wi-fi', '공공wifi', '공중 와이파이', '공중와이파이',
  '공공 인터넷', '무료 와이파이', '공용 와이파이',
  // 이동통신 품질·장비
  '이동통신 품질', '통신 품질', '5g 품질', '5g 속도', '네트워크 품질', '기지국',
  '통신 장비', '중계기', '통신망', '망 품질', '서비스 품질', '커버리지',
  '통신 불량', '전파 수신', '수신 불량', '전파 품질', '신호 약함', '음영지역',
  // 전파·전자파·무선국·주파수
  '전파', '전자파', '무선국', '주파수'
];

// ── 부정적·불만 기사 감지 키워드
var NEGATIVE_SIGNALS = [
  '민낯', '속터지는', '절레절레', '불만', '비판', '논란', '갈등', '문제점', '미흡', '부실',
  '실패', '형편없', '최악', '불편', '차별', '피해', '민원', '어이없', '황당', '역부족',
  '허점', '사각지대', '외면', '방치', '방관', '지적', '질타', '성토', '처참', '엉터리',
  '먹통', '불통', '불량', '낙제점', '끊김', '느린', '불만족', '개선 촉구', '개선 요구',
  '꼴', '망신', '비난', '성난', '분통', '뿔난', '꼬집', '꼬집어', '분노', '항의',
  'nobody\'s ready', 'fails', 'problem', 'issue', 'concern', 'complaint', 'poor',
  'slow', 'unreliable', 'disappointing', 'frustrat'
];

function classifyNewsImportance(news) {
  var hay = ((news.title || '') + ' ' + (news.summary || '')).toLowerCase();

  // [1단계] 법적 조치·행정처분 등 기존 긴급 키워드 → 긴급
  var urgentKws = IMPORTANCE_RULES['긴급'].keywords;
  for (var i = 0; i < urgentKws.length; i++) {
    if (hay.includes(urgentKws[i].toLowerCase())) return '긴급';
  }

  // [2단계] SKT 관련 주제 + 부정적 신호 → 긴급
  var isRelevant = SKT_RELEVANT_TOPICS.some(function(t) { return hay.includes(t.toLowerCase()); });
  var isNegative = NEGATIVE_SIGNALS.some(function(s) { return hay.includes(s.toLowerCase()); });
  if (isRelevant && isNegative) return '긴급';

  // [3단계] 정책 움직임 (입법예고·개정안 등) → 보통
  var normalKws = IMPORTANCE_RULES['보통'].keywords;
  for (var i = 0; i < normalKws.length; i++) {
    if (hay.includes(normalKws[i].toLowerCase())) return '보통';
  }

  // [4단계] SKT 관련 주제 + 정보성 → 보통
  if (isRelevant) return '보통';

  return '참고';
}

// ── 뉴스 로드 & 렌더링 ────────────────────────────────────
async function loadNews() {
  if (!sb) return;
  try {
    // 전량 페이지네이션 조회 — PostgREST 서버 max-rows가 1000이라 limit만 키워선 잘린다(#28).
    // 60일 보존이라 행수가 수천 건까지 자라며, 상한 없이 전부 가져온다(안전 상한 10,000행).
    // 목록 표시에 필요한 컬럼만 조회 — content(기사 본문)는 행당 수 KB로 초기 전송량의 대부분이라 제외.
    // 상세 열람 시 showNewsDetail이 해당 1건만 온디맨드 조회하며, RAG 자문은 별도 쿼리로 content를 직접 가져온다 (#61).
    var NEWS_LIST_COLS = 'id,title,source,category,url,is_read,published_at,created_at,summary,importance,urgency,locked,briefed_date,content_fetched_at';
    var all = [];
    for (var off = 0; off < 10000; off += 1000) {
      var page = await sb.from('news_feed').select(NEWS_LIST_COLS)
        .order('published_at', { ascending: false, nullsFirst: false })
        .range(off, off + 999);
      if (page.error) throw page.error;
      all = all.concat(page.data || []);
      if ((page.data || []).length < 1000) break;
    }
    // 잠금 기사 별도 조회·병합 유지(배경역사 #38) — 전량 조회가 어떤 이유로든 잘려도 잠금 기사는 항상 포함
    var lockedResp = await sb.from('news_feed').select(NEWS_LIST_COLS).eq('locked', true).limit(500);
    var seen = new Set();
    newsDataCache = [];
    all.concat(lockedResp.data || []).forEach(function(n) {
      if (seen.has(n.id)) return; seen.add(n.id); newsDataCache.push(n);
    });
    newsDataCache.sort(function(a, b) { return (b.published_at || '').localeCompare(a.published_at || ''); });
    // 중요도 분류 (캐시에 저장)
    newsDataCache.forEach(function(n) { n._importance = n.importance || n.urgency || classifyNewsImportance(n); });
    renderNewsList();
  } catch(e) {
    console.warn('News load error:', e);
    var el = document.getElementById('news-list');
    if (el) el.innerHTML = '<div style="color:var(--text-secondary);padding:20px;text-align:center;font-size:12px">뉴스 로드 실패: ' + e.message + '</div>';
  }
}

// ── 뉴스 그룹핑 유틸 ─────────────────────────────────────
var _newsGroupOpen = {};

function _extractKeywords(title) {
  var stopwords = ['관련','대한','위한','통해','대해','기반','위해','이후','이전',
    '지난','오는','올해','내년','지금','현재','새로운','이번','해당','추진',
    '강화한다','강화하는','나선다','밝혔다','위해서'];
  // 한글 단어 추출 (2글자 이상)
  var words = title.match(/[가-힣]{2,}/g) || [];
  // 숫자+한글 혼합 추출 후 조사 제거 (예: 6300개로 → 6300개)
  var mixed = (title.match(/[0-9]+[가-힣]+/g) || []).map(function(w){
    return w.replace(/(으로|에서|부터|까지|로서|로는|로도|에는|에도|이나|이며|이고|로|을|를|이|가|은|는|의|에|과|와|도|만)$/, '');
  });
  // 지명 정규화: '제주도' → '제주', '서울시' → '서울'
  var normalized = words.map(function(w){
    return w.replace(/([가-힣]{2,})(도|시|군|구|광장)$/, '$1');
  });
  var all = normalized.concat(mixed);
  return all.filter(function(w){ return !stopwords.includes(w) && w.length >= 2; });
}

function _titleSimilarity(t1, t2) {
  var k1 = _extractKeywords(t1);
  var k2 = _extractKeywords(t2);
  if (!k1.length || !k2.length) return 0;
  var shared = k1.filter(function(w){ return k2.includes(w); });
  // 공유 키워드 1개만으로는 그룹핑하지 않음 — '기지국' 같은 흔한 도메인 단어가
  // 서로 다른 주제(광화문 행사 vs 폐기지국 재활용)를 한 그룹으로 잇는 오류 방지 (2026-06-12)
  if (shared.length < 2) return 0;
  return shared.length / Math.max(k1.length, k2.length);
}

function _groupNews(items) {
  var used = {};
  var groups = [];
  for (var i = 0; i < items.length; i++) {
    if (used[i]) continue;
    var group = [items[i]];
    var d1 = (items[i].published_at || items[i].created_at || '').slice(0, 10);
    used[i] = true;
    // 그룹 크기가 늘어날 수 있으므로 반복 확인 (전이적 그룹핑)
    var changed = true;
    while (changed) {
      changed = false;
      for (var j = 0; j < items.length; j++) {
        if (used[j]) continue;
        var d2 = (items[j].published_at || items[j].created_at || '').slice(0, 10);
        if (d1 !== d2) continue;
        // 그룹 내 어느 기사와 유사하면 추가
        var matchAny = group.some(function(g) {
          return _titleSimilarity(g.title, items[j].title) >= 0.15;
        });
        if (matchAny) {
          group.push(items[j]);
          used[j] = true;
          changed = true;
        }
      }
    }
    groups.push(group);
  }
  return groups;
}

function _groupTitle(items) {
  var allKw = [];
  items.forEach(function(n){ allKw = allKw.concat(_extractKeywords(n.title)); });
  var freq = {};
  allKw.forEach(function(w){ freq[w] = (freq[w]||0) + 1; });
  var top = Object.keys(freq).filter(function(w){ return freq[w] >= 2; })
    .sort(function(a,b){ return freq[b]-freq[a]; }).slice(0,3);
  return top.length ? top.join(' ') + ' 관련' : items[0].title.slice(0,20) + '…';
}

function toggleNewsGroup(gid) {
  _newsGroupOpen[gid] = !_newsGroupOpen[gid];
  var body = document.getElementById('ng-body-' + gid);
  var icon = document.getElementById('ng-icon-' + gid);
  if (body) body.style.display = _newsGroupOpen[gid] ? 'block' : 'none';
  if (icon) icon.style.transform = _newsGroupOpen[gid] ? 'rotate(180deg)' : '';
}

function _renderSingleItem(n) {
  var rule = IMPORTANCE_RULES[n._importance] || IMPORTANCE_RULES['참고'];
  var date = new Date(n.published_at || n.created_at).toLocaleDateString('ko-KR', {year:'numeric', month:'2-digit', day:'2-digit'});
  var isSelected = String(n.id) === String(selectedNewsId);
  // 외부 API 유래 필드(title/summary/source/url)는 innerHTML 삽입 전 반드시 escHtml/safeUrl (XSS 차단, #61)
  var safeU = safeUrl(n.url);
  var urlIcon = safeU
    ? ' <a href="' + safeU + '" target="_blank" onclick="event.stopPropagation()" style="color:var(--accent);font-size:11px;vertical-align:middle"><i class="ti ti-external-link"></i></a>'
    : '';
  var lockIcon = ' <span onclick="event.stopPropagation();toggleNewsLock(\'' + n.id + '\')" ' +
    'title="' + (n.locked ? '잠금 해제 (해제 시 60일 경과 후 삭제됨)' : '잠금 (60일이 지나도 삭제되지 않음)') + '" ' +
    'style="cursor:pointer;font-size:11px;vertical-align:middle;color:' + (n.locked ? 'var(--accent)' : 'var(--text-tertiary)') + ';opacity:' + (n.locked ? '1' : '.4') + '">' +
    '<i class="ti ti-' + (n.locked ? 'lock' : 'lock-open') + '"></i></span>';
  var delIcon = ' <span onclick="event.stopPropagation();deleteNewsItem(\'' + n.id + '\')" ' +
    'title="기사 삭제" ' +
    'style="cursor:pointer;font-size:11px;vertical-align:middle;color:var(--text-tertiary);opacity:.4">' +
    '<i class="ti ti-trash"></i></span>';
  return '<div class="news-item" onclick="showNewsDetail(\'' + n.id + '\')" style="cursor:pointer;border-left:' + rule.border + ';' + (isSelected ? 'background:var(--bg-secondary);border-radius:var(--radius-md)' : '') + '">' +
    '<div class="news-dot ' + (n.is_read ? 'dot-read' : 'dot-new') + '"></div>' +
    '<div style="flex:1;min-width:0;overflow:hidden">' +
      '<div class="news-item-header" style="display:flex;align-items:center;gap:5px;margin-bottom:3px;flex-wrap:wrap">' +
        '<span style="font-size:10px;font-weight:700;color:' + rule.color + ';background:' + rule.bg + ';padding:1px 7px;border-radius:4px;flex-shrink:0">' + rule.label + '</span>' +
        '<span style="font-size:11px;color:var(--text-tertiary);flex-shrink:0">' + date + '</span>' +
        (n.source ? '<span class="news-item-source" style="font-size:10px;color:var(--text-tertiary);margin-left:auto;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:90px">' + escHtml(n.source) + '</span>' : '') +
      '</div>' +
      '<div class="news-title" style="font-size:13px;line-height:1.5;word-break:break-word;overflow-wrap:break-word">' + escHtml(n.title) + urlIcon + lockIcon + delIcon + '</div>' +
      (n.summary ? '<div class="news-meta" style="margin-top:3px;font-size:11px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;color:var(--text-tertiary)">' + escHtml(n.summary.slice(0, 80)) + (n.summary.length > 80 ? '…' : '') + '</div>' : '') +
    '</div>' +
  '</div>';
}

function renderNewsList() {
  var data = currentNewsFilter === '전체'
    ? newsDataCache
    : newsDataCache.filter(function(n) { return n._importance === currentNewsFilter; });

  // 소스 타입 필터
  if (currentNewsSourceType === 'gov') {
    data = data.filter(isGovFeedItem);
    // 기관 필터 칩 렌더(전체 정부 데이터 기준 건수) 후 선택 기관만 남긴다 — 재조회 없음
    renderGovAgencyTabs(data);
    if (currentGovAgency !== '전체') {
      data = data.filter(function(n) { return govAgencyOf(n.source, n.category) === currentGovAgency; });
    }
  } else if (currentNewsSourceType === 'media') {
    hideGovAgencyTabs();
    data = data.filter(function(n) { return !isGovFeedItem(n); });
  } else {
    hideGovAgencyTabs();
  }

  // 검색어 필터 (제목·요약·출처, 대소문자 무시) — 중요도·소스 필터와 AND 결합.
  // 기관 칩 건수(renderGovAgencyTabs)에는 영향을 주지 않도록 맨 마지막에 적용한다.
  if (currentNewsSearch) {
    var q = currentNewsSearch.toLowerCase();
    data = data.filter(function(n) {
      return ((n.title || '') + '\n' + (n.summary || '') + '\n' + (n.source || '')).toLowerCase().indexOf(q) !== -1;
    });
  }

  var sorted = data.slice().sort(function(a, b) {
    return new Date(b.published_at || b.created_at) - new Date(a.published_at || a.created_at);
  });

  var listEl = document.getElementById('news-list');
  if (!listEl) return;

  if (sorted.length === 0) {
    listEl.innerHTML = '<div style="color:var(--text-secondary);padding:24px;text-align:center;font-size:12px">' +
      (currentNewsSearch ? '검색 결과 없음 — “' + escHtml(currentNewsSearch) + '”' : '조건에 맞는 뉴스가 없습니다.') + '</div>';
    return;
  }

  // 정부 보도자료·공지사항은 그룹핑 없이 개별 표시
  var groups = currentNewsSourceType === 'gov' ? sorted.map(function(n){ return [n]; }) : _groupNews(sorted);
  var html = '';

  groups.forEach(function(group, gi) {
    if (group.length === 1) {
      html += _renderSingleItem(group[0]);
    } else {
      var gid = 'g-' + String(group[0].id);
      var isOpen = !!_newsGroupOpen[gid];
      var gtitle = _groupTitle(group);
      var date = (group[0].published_at || group[0].created_at || '').slice(0, 10);
      var hasUrgent = group.some(function(n){ return n._importance === '긴급'; });
      var badgeColor = hasUrgent ? 'color:#c53030;background:#fff5f5' : 'color:var(--text-secondary);background:var(--bg-secondary)';
      html += '<div style="border:0.5px solid var(--border-secondary);border-radius:var(--radius-md);margin:4px 0;overflow:hidden">' +
        '<div onclick="toggleNewsGroup(\'' + gid + '\')" style="display:flex;align-items:center;gap:8px;padding:9px 12px;background:var(--bg-secondary);cursor:pointer;user-select:none">' +
          '<i class="ti ti-news" style="font-size:14px;color:var(--text-tertiary);flex-shrink:0"></i>' +
          '<span style="font-size:13px;font-weight:500;color:var(--text-primary);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escHtml(gtitle) + '</span>' +
          '<span style="font-size:11px;padding:1px 7px;border-radius:8px;flex-shrink:0;' + badgeColor + '">' + group.length + '건</span>' +
          '<span style="font-size:11px;color:var(--text-tertiary);flex-shrink:0">' + date + '</span>' +
          '<i id="ng-icon-' + gid + '" class="ti ti-chevron-down" style="font-size:14px;color:var(--text-tertiary);flex-shrink:0;transition:transform .2s;' + (isOpen ? 'transform:rotate(180deg)' : '') + '"></i>' +
        '</div>' +
        '<div id="ng-body-' + gid + '" style="display:' + (isOpen ? 'block' : 'none') + ';padding:0 12px;border-top:0.5px solid var(--border-tertiary)">' +
          group.map(function(n) {
            var rule = IMPORTANCE_RULES[n._importance] || IMPORTANCE_RULES['참고'];
            var safeU = safeUrl(n.url);
            var urlIcon = safeU ? ' <a href="' + safeU + '" target="_blank" onclick="event.stopPropagation()" style="color:var(--accent);font-size:11px"><i class="ti ti-external-link"></i></a>' : '';
            return '<div onclick="showNewsDetail(\'' + n.id + '\')" style="display:flex;align-items:flex-start;gap:8px;padding:8px 0;border-bottom:0.5px solid var(--border-tertiary);cursor:pointer">' +
              '<div class="news-dot ' + (n.is_read ? 'dot-read' : 'dot-new') + '" style="flex-shrink:0;margin-top:4px"></div>' +
              '<span style="font-size:12px;font-weight:700;color:' + rule.color + ';background:' + rule.bg + ';padding:1px 6px;border-radius:4px;flex-shrink:0">' + rule.label + '</span>' +
              '<div style="flex:1;min-width:0;overflow:hidden">' +
                '<div style="font-size:13px;color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escHtml(n.title) + urlIcon + '</div>' +
                (n.summary ? '<div style="margin-top:2px;font-size:11px;color:var(--text-tertiary);overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical">' + escHtml(n.summary.slice(0, 80)) + (n.summary.length > 80 ? '…' : '') + '</div>' : '') +
              '</div>' +
              '<span style="font-size:11px;color:var(--text-tertiary);flex-shrink:0;margin-left:8px">' + escHtml(n.source||'') + '</span>' +
              '<span onclick="event.stopPropagation();deleteNewsItem(\'' + n.id + '\')" title="기사 삭제" style="cursor:pointer;font-size:11px;color:var(--text-tertiary);opacity:.5;flex-shrink:0;margin-left:6px"><i class="ti ti-trash"></i></span>' +
            '</div>';
          }).join('') +
        '</div>' +
      '</div>';
    }
  });

  var groupCount = groups.filter(function(g){ return g.length > 1; }).length;
  var totalGrouped = groups.filter(function(g){ return g.length > 1; }).reduce(function(s,g){ return s+g.length; }, 0);
  if (groupCount > 0) {
    html += '<div style="font-size:11px;color:var(--text-tertiary);text-align:center;padding:8px 0">' +
      sorted.length + '건 중 ' + totalGrouped + '건 → ' + groupCount + '개 그룹으로 묶음</div>';
  }

  listEl.innerHTML = html;
}

// 뉴스 검색 입력 핸들러 — 200ms 디바운스 후 클라이언트 필터 재렌더 (서버 왕복 없음)
var _newsSearchTimer = null;
function onNewsSearchInput(value) {
  clearTimeout(_newsSearchTimer);
  _newsSearchTimer = setTimeout(function() {
    currentNewsSearch = (value || '').trim();
    renderNewsList();
  }, 200);
}

function filterNewsByImportance(el, importance) {
  document.querySelectorAll('#news-filter-tabs .tag').forEach(function(t) { t.classList.remove('selected'); });
  el.classList.add('selected');
  currentNewsFilter = importance;
  renderNewsList();
}

// ── 뉴스 상세 패널 ─────────────────────────────────────────
// ── 뉴스 잠금 토글 (locked=true면 60일 경과해도 삭제되지 않음) ──
async function toggleNewsLock(newsId) {
  var n = newsDataCache.find(function(x) { return String(x.id) === String(newsId); });
  if (!n || !sb) return;
  var newVal = !n.locked;
  n.locked = newVal;
  renderNewsList();
  // 모달 잠금 버튼이 열려 있으면 상태 갱신
  var btn = document.getElementById('lock-btn-' + newsId);
  if (btn) {
    btn.innerHTML = newVal ? '<i class="ti ti-lock"></i> 잠금됨' : '<i class="ti ti-lock-open"></i> 잠금';
    btn.style.color = newVal ? 'var(--accent)' : '';
  }
  try {
    await sb.from('news_feed').update({ locked: newVal }).eq('id', newsId);
  } catch(e) {
    n.locked = !newVal;
    renderNewsList();
    alert('잠금 변경 실패: ' + e.message);
  }
}

// ── 뉴스 기사 삭제 (news_feed 영구 삭제 + deleted_news 등록으로 재수집 방지) ──
async function deleteNewsItem(newsId) {
  var n = newsDataCache.find(function(x) { return String(x.id) === String(newsId); });
  if (!n || !sb) return;
  var msg = '이 기사를 삭제할까요?\n\n' + (n.title || '');
  if (n.locked) msg += '\n\n⚠️ 잠금된 기사입니다. 삭제하면 AI 자문에서도 더 이상 참조되지 않습니다.';
  if (!confirm(msg)) return;
  try {
    // 재수집 방지: 크롤러가 같은 URL·제목을 다시 저장하지 않도록 블록리스트 기록
    try { await sb.from('deleted_news').insert({ url: n.url || null, title: n.title || null }); } catch(e2) { console.warn('deleted_news 기록 실패(같은 기사 재수집될 수 있음):', e2); }
    var resp = await sb.from('news_feed').delete().eq('id', newsId);
    if (resp.error) throw resp.error;
    newsDataCache = newsDataCache.filter(function(x) { return String(x.id) !== String(newsId); });
    if (String(selectedNewsId) === String(newsId)) {
      selectedNewsId = null;
      var panel = document.getElementById('news-detail-panel');
      if (panel) panel.style.display = 'none';
    }
    renderNewsList();
  } catch(e) {
    alert('기사 삭제 실패: ' + e.message);
  }
}

// ── 긴급도 수정 셀렉터 HTML (뉴스 상세 모달) ──
function _impSelHtml(newsId, current) {
  return ['긴급', '보통', '참고'].map(function(v) {
    var r = IMPORTANCE_RULES[v] || {};
    var act = (current === v);
    return '<span onclick="setNewsImportance(\'' + newsId + '\',\'' + v + '\')" ' +
      'style="cursor:pointer;font-size:10px;padding:2px 7px;border-radius:4px;white-space:nowrap;border:1px solid ' + (act ? r.color : 'var(--border-secondary)') + ';' +
      'color:' + (act ? '#fff' : 'var(--text-tertiary)') + ';background:' + (act ? r.color : 'transparent') + '">' + (v === '긴급' ? '중요' : v) + '</span>';
  }).join('');
}

// ── 긴급도 수동 수정 — importance_feedback에 기록되어 크롤러 분류가 학습됨 ──
async function setNewsImportance(newsId, newVal) {
  var n = newsDataCache.find(function(x) { return String(x.id) === String(newsId); });
  if (!n || !sb) return;
  var oldVal = n._importance || n.importance || n.urgency || '참고';
  if (oldVal === newVal) return;
  try {
    var ur = await sb.from('news_feed').update({ importance: newVal, urgency: newVal })
      .eq('id', newsId).select('id,importance');
    if (ur.error) throw new Error('news_feed 업데이트 실패: ' + ur.error.message);
    if (!ur.data || ur.data.length === 0) throw new Error('news_feed 업데이트 실패: 대상 행을 찾지 못함');
    // 피드백 기록 — ai_importance는 최초 AI 판정값 보존 (news_id당 1행)
    var fb = { title: n.title || '', summary: (n.summary || '').slice(0, 300),
               user_importance: newVal, updated_at: new Date().toISOString() };
    var ex = await sb.from('importance_feedback').select('id').eq('news_id', newsId).limit(1);
    if (ex.data && ex.data.length > 0) {
      await sb.from('importance_feedback').update(fb).eq('news_id', newsId);
    } else {
      fb.news_id = newsId;
      fb.ai_importance = oldVal;
      await sb.from('importance_feedback').insert(fb);
    }
    n.importance = newVal; n.urgency = newVal; n._importance = newVal;
    renderNewsList();
    var rule = IMPORTANCE_RULES[newVal];
    var badge = document.getElementById('importance-badge-' + newsId);
    if (badge && rule) { badge.textContent = rule.label; badge.style.color = rule.color; badge.style.background = rule.bg; }
    var sel = document.getElementById('imp-sel-' + newsId);
    if (sel) sel.innerHTML = _impSelHtml(newsId, newVal);
    // 당일 브리핑에 포함된 기사면 브리핑 원문의 🔴 표시도 동기화
    try { await syncBriefingUrgency(newsId, newVal); } catch(e2) { console.warn('[브리핑 동기화] 실패(무시):', e2); }
  } catch(e) {
    alert('긴급도 수정 실패: ' + e.message);
  }
}

// ── 긴급도 수정 → 당일 브리핑 원문 🔴 동기화 ──
// 기사가 오늘 daily_briefings에 [ID:..]로 포함돼 있으면, 긴급 지정 시 해당 줄에 🔴 추가,
// 긴급 해제 시 🔴 제거. 화면이 열려 있으면 즉시 갱신. (이미 발송된 이메일·텔레그램은 소급 불가)
async function syncBriefingUrgency(newsId, newVal) {
  if (!sb) return;
  var todayKst = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
  var resp = await sb.from('daily_briefings').select('content').eq('briefing_date', todayKst).limit(1);
  if (resp.error || !resp.data || resp.data.length === 0) return;
  var content = resp.data[0].content || '';
  var tag = '[ID:' + newsId + ']';
  if (content.indexOf(tag) === -1) return; // 오늘 브리핑에 없는 기사
  var lines = content.split('\n');
  var changed = false;
  for (var i = 0; i < lines.length; i++) {
    if (lines[i].indexOf(tag) === -1) continue;
    if (newVal === '긴급' && lines[i].indexOf('🔴') === -1) {
      lines[i] = lines[i].replace(/^(\s*•\s*)/, '$1🔴 ');
      changed = true;
    } else if (newVal !== '긴급' && lines[i].indexOf('🔴') !== -1) {
      lines[i] = lines[i].replace(/🔴\s*/, '');
      changed = true;
    }
    break;
  }
  if (!changed) return;
  var ur = await sb.from('daily_briefings').update({ content: lines.join('\n') }).eq('briefing_date', todayKst);
  if (!ur.error) {
    console.log('[브리핑 동기화] 당일 브리핑 🔴 표시 갱신:', newVal);
    var listEl = document.getElementById('briefing-list');
    if (listEl && listEl.innerHTML) loadBriefing();
  }
}

async function showNewsDetail(newsId) {
  selectedNewsId = newsId;
  var n = newsDataCache.find(function(x) { return String(x.id) === String(newsId); });
  if (!n) return;

  // 목록 선택 표시 업데이트
  renderNewsList();

  var rule   = IMPORTANCE_RULES[n._importance] || IMPORTANCE_RULES['참고'];
  var date   = (n.published_at || n.created_at || '').slice(0, 10);
  var safeU  = safeUrl(n.url);
  var urlBtn = safeU
    ? '<a href="' + safeU + '" target="_blank" class="btn" style="font-size:11px;padding:4px 10px;text-decoration:none;white-space:nowrap"><i class="ti ti-external-link"></i> 원문 보기</a>'
    : '';
  var lockBtn = '<button class="btn" id="lock-btn-' + n.id + '" onclick="toggleNewsLock(\'' + n.id + '\')" ' +
    'title="잠금 시 60일이 지나도 삭제되지 않고 AI 자문에서 계속 참조됩니다" ' +
    'style="font-size:11px;padding:4px 10px;cursor:pointer;white-space:nowrap;' + (n.locked ? 'color:var(--accent)' : '') + '">' +
    (n.locked ? '<i class="ti ti-lock"></i> 잠금됨' : '<i class="ti ti-lock-open"></i> 잠금') + '</button>';
  var delBtn = '<button class="btn" onclick="deleteNewsItem(\'' + n.id + '\')" ' +
    'title="이 기사를 목록에서 영구 삭제합니다 (재수집되지 않음)" ' +
    'style="font-size:11px;padding:4px 10px;cursor:pointer;color:#d04545;white-space:nowrap">' +
    '<i class="ti ti-trash"></i> 삭제</button>';

  var impSel = '<div style="display:flex;align-items:center;gap:5px;margin-bottom:8px;flex-wrap:wrap">' +
    '<span style="font-size:10px;color:var(--text-tertiary);white-space:nowrap">중요도 수정</span>' +
    '<span id="imp-sel-' + n.id + '" title="수정 내역은 AI 분류 학습에 반영됩니다" style="display:inline-flex;gap:4px">' + _impSelHtml(n.id, n._importance) + '</span></div>';

  var html =
    // 헤더: 중요도 + 제목
    '<div style="border-left:3px solid ' + rule.color + ';padding-left:10px;margin-bottom:14px">' +
      '<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;flex-wrap:wrap;row-gap:6px">' +
        '<span id="importance-badge-' + n.id + '" style="font-size:11px;font-weight:700;color:' + rule.color + ';background:' + rule.bg + ';padding:2px 8px;border-radius:4px;white-space:nowrap">' + rule.label + '</span>' +
        '<span style="font-size:11px;color:var(--text-tertiary);white-space:nowrap">' + date + '</span>' +
        '<div style="margin-left:auto;display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">' + lockBtn + delBtn + urlBtn + '</div>' +
      '</div>' +
      impSel +
      '<div style="font-size:13px;font-weight:600;color:var(--text-primary);line-height:1.55;margin-bottom:4px">' + escHtml(n.title) + '</div>' +
      '<div style="font-size:11px;color:var(--text-secondary)">' + escHtml(n.source || '') + '</div>' +
    '</div>' +

    // 주요 내용 요약 — AI 자동 생성 (스피너로 시작)
    '<div style="margin-bottom:14px">' +
      '<div style="font-size:10px;font-weight:700;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.6px;margin-bottom:7px">● 주요 내용 요약</div>' +
      '<div style="font-size:12px;color:var(--text-primary);padding:9px 12px;background:var(--bg-secondary);border-radius:var(--radius-md);line-height:1.7" id="summary-box-' + n.id + '">' +
        '<div style="display:flex;align-items:center;gap:8px;color:var(--text-secondary)">' +
          '<span style="display:inline-block;width:14px;height:14px;border:2px solid var(--accent);border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite"></span>' +
          '요약 생성 중...' +
        '</div>' +
      '</div>' +
    '</div>' +

    // SKT 영향도 — 자동 분석 (로딩 스피너로 시작)
    '<div style="margin-bottom:14px">' +
      '<div style="font-size:10px;font-weight:700;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.6px;margin-bottom:7px">● SKT 영향도 분석</div>' +
      '<div style="font-size:12px;color:var(--text-primary);padding:10px 12px;background:' + rule.bg + ';border-radius:var(--radius-md);line-height:1.7" id="impact-box-' + n.id + '">' +
        '<div style="display:flex;align-items:center;gap:8px;color:var(--text-secondary)">' +
          '<span style="display:inline-block;width:14px;height:14px;border:2px solid var(--accent);border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite"></span>' +
          'AI 분석 중...' +
        '</div>' +
      '</div>' +
    '</div>' +

    // AI 자문 연동 — 제목을 onclick JS 문자열에 직접 넣지 않고 data-속성으로 전달 (속성 탈출 XSS 차단, #61)
    '<div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--border)">' +
      '<button data-nt="' + escHtml(n.title.slice(0, 50)) + '" onclick="askQ(this.getAttribute(\'data-nt\') + \' SKT 영향 분석해줘\')" class="btn btn-primary" style="width:100%;font-size:12px;justify-content:center">' +
        '<i class="ti ti-message-2"></i> AI 자문에서 상세 분석' +
      '</button>' +
    '</div>';

  var panel   = document.getElementById('news-detail-panel');
  var content = document.getElementById('news-detail-content');
  if (panel)   { panel.style.display = 'block'; }
  if (content) { content.innerHTML = html; }

  // 읽음 처리
  if (sb) { sb.from('news_feed').update({ is_read: true }).eq('id', n.id).then(function() {}); }
  n.is_read = true;

  // content는 목록 조회(select)에서 제외했으므로(초기 전송량 절감, #61) 상세 열람 시 해당 1건만 온디맨드 조회.
  // RAG 자문은 별도 쿼리(select에 content 포함)로 본문을 직접 가져오므로 캐시 슬림화와 무관.
  if (sb && n.content === undefined) {
    try {
      var cResp = await sb.from('news_feed').select('content').eq('id', n.id).maybeSingle();
      n.content = (cResp && cResp.data && cResp.data.content) || '';
    } catch(e) { n.content = ''; }
  }

  // 요약 + 영향도 분석 자동 실행
  summarizeNews(n.id);
  analyzeNewsImpact(n.id);
}

// ── 주요 내용 요약 렌더링 헬퍼 ──────────────────────────────────
function renderSummaryHtml(text) {
  // 줄바꿈 기준으로 단락 분리, 각 항목을 불릿으로 표시
  var lines = text.split(/\n+/).map(function(l) { return l.trim(); }).filter(function(l) { return l.length > 0; });
  if (lines.length <= 1) {
    // 문장 단위로 분리 (마침표 기준)
    lines = text.replace(/([.!?])\s+/g, '$1\n').split('\n').map(function(l) { return l.trim(); }).filter(function(l) { return l.length > 4; });
  }
  if (lines.length <= 1) {
    return '<p style="margin:0;font-size:12px;line-height:1.8;color:var(--text-primary)">' + text.trim() + '</p>';
  }
  return lines.map(function(line) {
    return '<div style="display:flex;gap:7px;margin-bottom:7px;font-size:12px;line-height:1.75;color:var(--text-primary)">' +
      '<span style="flex-shrink:0;margin-top:5px;width:5px;height:5px;border-radius:50%;background:var(--accent);display:inline-block"></span>' +
      '<span>' + line + '</span>' +
    '</div>';
  }).join('');
}

// ── 주요 내용 요약 (Claude Haiku + Supabase 캐싱) ──────────────
async function summarizeNews(newsId) {
  var n = newsDataCache.find(function(x) { return String(x.id) === String(newsId); });
  if (!n) return;

  var box = document.getElementById('summary-box-' + newsId);
  if (!box) return;

  // ① DB에 저장된 요약 있으면 즉시 표시 (API 호출 없음)
  if (n.summary && n.summary.trim().length > 20) {
    box.innerHTML = renderSummaryHtml(n.summary.trim());
    return;
  }

  // ② 본문 준비 — 없으면 CORS 프록시로 원문 직접 수집
  var bodySnippet = (n.content || '').replace(/\s+/g, ' ').trim().slice(0, 3000);

  if (!bodySnippet && n.url) {
    box.innerHTML =
      '<div style="display:flex;align-items:center;gap:8px;color:var(--text-secondary)">' +
        '<span style="display:inline-block;width:14px;height:14px;border:2px solid var(--accent);border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite"></span>' +
        '원문 수집 중...' +
      '</div>';
    bodySnippet = await _fetchArticleBody(n.url);
    if (bodySnippet && sb) {
      // 수집 성공 시 DB에 저장해 다음번엔 바로 사용
      sb.from('news_feed').update({ content: bodySnippet }).eq('id', n.id).then(function() {});
      n.content = bodySnippet;
    }
  }

  if (!bodySnippet) {
    box.innerHTML = '<span style="color:var(--text-tertiary);font-size:11px">원문을 가져오지 못했습니다. 원문 보기를 통해 직접 확인해 주세요.</span>';
    return;
  }

  // 다시 로딩 스피너로 교체
  box.innerHTML =
    '<div style="display:flex;align-items:center;gap:8px;color:var(--text-secondary)">' +
      '<span style="display:inline-block;width:14px;height:14px;border:2px solid var(--accent);border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite"></span>' +
      '요약 생성 중...' +
    '</div>';

  var { claudeKey } = getConfig();
  if (!claudeKey) {
    box.innerHTML = '<span style="color:var(--text-tertiary);font-size:11px">Claude API 키 필요 — 설정에서 입력해 주세요.</span>';
    return;
  }

  try {
    var userMsg =
      '다음 뉴스를 핵심 포인트 3~5개로 요약하세요.\n' +
      '- 각 포인트를 줄바꿈으로 구분하세요.\n' +
      '- 각 포인트는 1~2문장, 육하원칙(누가/무엇을/왜/어떻게) 포함.\n' +
      '- 불릿 기호(•, -, * 등)는 붙이지 마세요. 순수 텍스트만.\n\n' +
      '제목: ' + n.title + '\n출처: ' + (n.source || '') + '\n날짜: ' + (n.published_at || '').slice(0, 10) +
      '\n\n본문:\n' + bodySnippet;

    var res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'x-api-key': claudeKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json', 'anthropic-dangerous-direct-browser-access': 'true' },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 500,
        system: '당신은 전파·통신 정책 뉴스를 간결하게 요약하는 전문가입니다. 사실만 기반으로 핵심 포인트를 줄바꿈으로 구분하여 작성하세요. 불릿 기호 없이 텍스트만 출력하세요.',
        messages: [{ role: 'user', content: userMsg }]
      })
    });
    var data = await res.json();
    var summaryText = (data.content && data.content[0] && data.content[0].text || '').trim();

    if (summaryText) {
      box.innerHTML = renderSummaryHtml(summaryText);
      // ② Supabase에 저장 + 로컬 캐시 갱신
      n.summary = summaryText;
      if (sb) { sb.from('news_feed').update({ summary: summaryText }).eq('id', n.id).then(function() {}); }
    } else {
      box.innerHTML = '<span style="color:var(--text-tertiary);font-size:11px">요약 생성 실패 — 원문을 직접 확인해 주세요.</span>';
    }
  } catch(e) {
    console.warn('요약 오류:', e);
    if (box) { box.innerHTML = '<span style="color:var(--text-tertiary);font-size:11px">요약 생성 실패 — 원문을 직접 확인해 주세요.</span>'; }
  }
}

// ── AI 영향도 분석 (Claude Haiku — 빠른 분석) ───────────────
async function analyzeNewsImpact(newsId) {
  var n = newsDataCache.find(function(x) { return String(x.id) === String(newsId); });
  if (!n) return;
  var { claudeKey } = getConfig();
  if (!claudeKey) { alert('Claude API 키가 필요합니다.'); return; }

  var box = document.getElementById('impact-box-' + newsId);

  try {
    var sysMsg = SKT_IMPACT_SYSTEM_PROMPT;
    // 본문이 있으면 최대 2000자까지 포함 — 제목만 줄 때보다 훨씬 정확한 분석 가능
    var bodySnippet = (n.body || n.content || '').replace(/\s+/g, ' ').trim().slice(0, 2000);

    // 본문 없으면 분석 불가 안내
    if (!bodySnippet) {
      if (box) box.innerHTML = '<span style="color:var(--text-tertiary);font-size:11px">원문 본문이 없어 영향도를 분석할 수 없습니다. 원문 보기를 통해 직접 확인해 주세요.</span>';
      return;
    }

    var userMsg = '제목: ' + n.title +
      '\n출처: ' + (n.source || '') +
      '\n날짜: ' + (n.published_at || '').slice(0, 10) +
      (n.summary ? '\n요약: ' + n.summary : '') +
      (bodySnippet ? '\n\n본문:\n' + bodySnippet : '');

    var res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'x-api-key': claudeKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json', 'anthropic-dangerous-direct-browser-access': 'true' },
      body: JSON.stringify({ model: 'claude-haiku-4-5-20251001', max_tokens: 800, system: sysMsg, messages: [{ role: 'user', content: userMsg }] })
    });
    var data = await res.json();

    // API 오류 응답 명시 처리
    if (data.error) {
      throw new Error(data.error.message || 'API 오류');
    }

    var text = (data.content && data.content[0] && data.content[0].text) || '';

    var impactM   = text.match(/<impact>([\s\S]*?)<\/impact>/);
    var priorityM = text.match(/<priority>([\s\S]*?)<\/priority>/);

    var impactText   = impactM   ? impactM[1].trim()   : '';
    var priorityText = priorityM ? priorityM[1].trim() : '';

    var rule = IMPORTANCE_RULES[n._importance] || IMPORTANCE_RULES['참고'];

    if (box) {
      if (impactText) {
        box.innerHTML =
          renderSummaryHtml(impactText) +
          (priorityText ? '<div style="font-size:11px;color:' + rule.color + ';font-weight:600;margin-top:6px">⚡ ' + priorityText + '</div>' : '');
      } else {
        box.innerHTML = text
          ? renderSummaryHtml(text.trim())
          : '<span style="color:var(--text-tertiary);font-size:11px">분석 결과를 받지 못했습니다 — AI 자문에서 직접 질문해 주세요.</span>';
      }
    }

    // ※ 과거에는 분석의 priority로 긴급도 배지·DB를 자동 덮어썼으나 제거됨 (2026-06-12).
    //    긴급도의 단일 기준은 크롤러 분류 + 담당자 수동 수정(importance_feedback)이며,
    //    영향도 분석은 표시 전용. (자동 덮어쓰기가 담당자 수정을 되돌리는 버그의 원인이었음)
  } catch(e) {
    console.warn('영향도 분석 오류:', e);
    if (box) { box.innerHTML = '<span style="color:var(--text-tertiary);font-size:11px">분석 실패 (' + e.message + ') — AI 자문에서 직접 질문해 주세요.</span>'; }
  }
}

async function markRead(id) {
  if (sb) { try { await sb.from('news_feed').update({ is_read: true }).eq('id', id); } catch(e) { console.warn('읽음 표시 저장 실패:', e); } }
}

// 구 filterNews 호환용 (혹시 다른 곳에서 호출 시)
function filterNews(el, cat) { filterNewsByImportance(el, cat); }

// ════════════════════════════════════════════
//  법령 DIFF 분석
// ════════════════════════════════════════════
// ── 지식 베이스 문서 목록 (document_chunks 실시간 · 수동정리 목록과 동일 스타일) ──
var _kbDocsLoaded = false;
var _kbDocsRows = [];    // list_kb_documents 원본 캐시 — 검색 재렌더가 DB를 다시 치지 않도록
// 지식베이스 목록의 구버전·시행예정본 표시 토글(기본: 현행본만)
var _kbShowOlder = false, _kbOlderCount = 0, _kbPendingCount = 0;

// ── 지식 목록 이름 검색 (국내 법령·고시 / 실무 안내 공용) ────────────────
// 공백으로 나눈 단어를 모두 포함해야 통과(AND). 매칭 0건인 그룹은 렌더 단계에서 통째로 빠진다.
function kbSearchTerms(inputId) {
  var el = document.getElementById(inputId);
  var v = (el && el.value || '').trim().toLowerCase();
  return v ? v.split(/\s+/).filter(function(t) { return t; }) : [];
}
function kbNameMatches(name, terms) {
  if (!terms.length) return true;
  var s = String(name || '').toLowerCase();
  return terms.every(function(t) { return s.indexOf(t) !== -1; });
}
function kbHighlight(name, terms) {
  var html = escHtml(name);
  if (!terms.length) return html;
  // 긴 단어부터 치환해야 짧은 단어가 <mark> 태그 안쪽을 깨뜨리지 않는다
  terms.slice().sort(function(a, b) { return b.length - a.length; }).forEach(function(t) {
    var re = new RegExp('(' + t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
    html = html.replace(re, '\u0001$1\u0002');
  });
  return html.replace(/\u0001/g, '<mark class="kb-hit">').replace(/\u0002/g, '</mark>');
}
function kbSearchStatus(countId, clearId, inputId, n) {
  var c = document.getElementById(countId), x = document.getElementById(clearId);
  var has = kbSearchTerms(inputId).length > 0;
  if (c) c.textContent = has ? n + '건' : '';
  if (x) x.style.display = has ? 'block' : 'none';
}
function clearKbSearch() {
  var el = document.getElementById('kb-search');
  if (el) { el.value = ''; el.focus(); }
  loadKbDocs();
}
function clearGuideSearch() {
  var el = document.getElementById('guide-search');
  if (el) { el.value = ''; el.focus(); }
  loadGuideDocs();
}

var _KB_GROUPS = [
  ['전파법 기본 법령', /^전파법/],
  ['주파수 행정규칙', /주파수|할당|공동사용/],
  ['전자파 행정규칙', /전자파/],
  ['적합성평가 행정규칙', /적합성평가|시험기관|상호인정/],
  ['전기통신사업법 계열', /전기통신사업|이동통신단말장치/],
  ['정보통신망법 계열', /정보통신망/],
  ['방송통신발전기본법 계열', /방송통신발전|방송통신설비|방송통신규제|기반시설|멀티미디어|재난/],
  ['지방세법 계열', /지방세/],
  ['무선설비·무선국·기술기준', /기술기준|무선설비|무선국|단말장치|간이무선|항공|해상|우주|선박|아마추어|검사업무/]
];

function _kbParseName(raw) {
  var name = String(raw || '').replace(/\.(pdf|md|pptx|txt)$/i, '').replace(/\s*\(\d\)\s*$/, '');
  var dup = /^_중복_/.test(name);
  name = name.replace(/^_중복_/, '');
  var kind = (name.match(/\(([가-힣]*(?:법률|대통령령|총리령|부령|고시|훈령|공고|예규|위원회규칙|연구원규칙))\)/) || [])[1] || '';
  var no = (name.match(/\(제([0-9\-]+)호\)/) || [])[1] || '';
  var date = (name.match(/\((20\d{6})\)/) || [])[1] || '';
  var clean = name
    .replace(/\(([가-힣]*(?:법률|대통령령|총리령|부령|고시|훈령|공고|예규|위원회규칙|연구원규칙))\)/g, '')
    .replace(/\(제[0-9\-]+호\)/g, '')
    .replace(/\(20\d{6}\)/g, '')
    .trim();
  var info = [];
  if (kind || no) info.push((kind ? kind + ' ' : '') + (no ? '제' + no + '호' : ''));
  if (date) info.push(date.slice(0, 4) + '.' + date.slice(4, 6) + '.' + date.slice(6, 8) + ' 시행');
  return { clean: clean || name, info: info.join(' · '), dup: dup };
}

async function loadKbDocs(force) {
  var el = document.getElementById('kb-doc-groups');
  if (!el || !sb) return;
  try {
    // 검색어 입력마다 이 함수가 다시 불리므로 DB는 최초 1회(또는 force)만 조회하고
    // 이후에는 캐시로 다시 그린다. 매 타자마다 RPC를 때리면 목록이 깜빡이고 요금도 낭비된다.
    if (!_kbDocsLoaded || force) {
      var resp = await sb.rpc('list_kb_documents');
      if (resp.error) throw resp.error;
      _kbDocsRows = resp.data || [];
    }
    // 구버전(superseded)·시행예정본(pending)은 기본적으로 감춘다. 이것들까지 나열하면
    // 같은 법령이 2~3개씩 보여 "중복 등재"로 오해된다(실제로는 버전 관리가 정상 동작한 것).
    // 토글로 펼쳐 볼 수 있게 하고, 상단에 건수만 알린다.
    // 이 목록은 '법령·고시'만 보여야 한다. 제외 조건이 ITU-R과 날짜 파일명 둘뿐이라
    // 논문·메모(추가지식)와 보도자료가 섞여 들어왔다 — 제목에 '전자파'가 든 논문이
    // '전자파 행정규칙' 그룹에 끼어 보이는 식이었다. 카테고리로 걸러야 정확하다. (#50)
    // ※ 화면에서만 빼는 것이고 자문 RAG에서는 계속 검색된다(논문·메모는 유용한 근거).
    var all = _kbDocsRows.filter(function(r) {
      if (r.doc_category === 'ITU-R') return false;    // ITU-R 문서 탭
      if (r.doc_category === '추가지식') return false;  // 추가 지식 입력 탭
      if (r.doc_category === '보도자료') return false;  // 정부 보도자료 탭
      if (r.doc_category === '회의록') return false;    // 국회 법안 탭 (과방위 회의록)
      if (r.doc_category === '해외동향') return false;  // 해외 주요 정책 KB 승격분 (자문 참조용, #54)
      // 날짜 파일명(240717…)도 보도자료. '과기정통부_보도자료_2024.md'처럼
      // 접두가 다른 것은 위 카테고리 조건이 잡는다.
      if (/^\d{6}/.test(r.doc_name)) return false;
      return true;
    });
    var older = all.filter(function(r) { return r.status && r.status !== 'current'; });
    var rows = _kbShowOlder ? all : all.filter(function(r) { return !r.status || r.status === 'current'; });
    _kbOlderCount = older.length;
    _kbPendingCount = older.filter(function(r) { return r.status === 'pending'; }).length;
    // 이름 검색 — 표시용 정리 이름(_kbParseName.clean)으로 매칭한다.
    // 원본 doc_name은 '_중복_' 접두·'.pdf' 확장자가 붙어 있어 그걸로 매칭하면 결과가 어긋난다. (배경역사 #41)
    var kbTerms = kbSearchTerms('kb-search');
    var groups = _KB_GROUPS.map(function(g) { return { title: g[0], re: g[1], items: [] }; });
    var etc = { title: '기타 법령·고시', items: [] };
    var matched = 0;
    rows.forEach(function(r) {
      var p = _kbParseName(r.doc_name);
      if (!kbNameMatches(p.clean, kbTerms)) return;
      matched++;
      var item = { p: p, docName: r.doc_name, chunks: r.chunks, embedded: r.embedded > 0, approved: r.approved !== false, status: r.status };
      for (var i = 0; i < groups.length; i++) {
        if (groups[i].re.test(p.clean)) { groups[i].items.push(item); return; }
      }
      etc.items.push(item);
    });
    groups.push(etc);
    var total = 0;
    var html = groups.filter(function(g) { return g.items.length > 0; }).map(function(g, gi) {
      g.items.sort(function(a, b) { return a.p.clean.localeCompare(b.p.clean, 'ko'); });
      total += g.items.length;
      var fileRows = g.items.map(function(it) {
        var badge = it.embedded
          ? ''
          : '<span class="badge" style="background:rgba(245,158,11,.12);color:#b45309" title="backfill_embeddings.py 실행 전 — 키워드 검색만 가능">임베딩 대기</span>';
        if (!it.approved) {
          badge += '<span class="badge" style="background:rgba(220,38,38,.12);color:#b91c1c" title="설정에서 승인 전 — AI 자문 미반영">승인 대기</span>';
        }
        var nameHtml = kbHighlight(it.p.clean, kbTerms);
        var dupTag = it.p.dup ? ' <span style="font-size:10px;color:var(--text-tertiary)">(중복본)</span>' : '';
        if (it.status === 'superseded') {
          dupTag += ' <span class="badge" style="background:rgba(107,114,128,.15);color:#4b5563" title="개정 전 구버전 — 자문 검색에서 제외됨">구버전</span>';
        } else if (it.status === 'pending') {
          dupTag += ' <span class="badge" style="background:rgba(59,130,246,.12);color:#1d4ed8" title="공포됐으나 시행 전 — 시행일 도래 시 자동 승격">시행예정</span>';
        }
        // 클릭 → 원문(조문 전체) 모달. doc_name은 목록 표시명이 아닌 DB 원본값을 넘겨야 조회됨.
        return '<div class="file-item" style="cursor:pointer" title="클릭하면 원문(조문)을 볼 수 있습니다" ' +
          'onclick="openKbDoc(&quot;' + escHtml(it.docName) + '&quot;)">' +
          '<div class="file-icon fi-purple"><i class="ti ti-file-text"></i></div>' +
          '<div style="flex:1;min-width:0"><div class="file-name">' + nameHtml + dupTag + '</div>' +
          '<div class="file-size">' + (it.p.info ? it.p.info + ' · ' : '') + it.chunks + '청크</div></div>' + badge +
          '<i class="ti ti-chevron-right" style="color:var(--text-tertiary);font-size:15px;flex-shrink:0"></i></div>';
      }).join('');
      return '<div class="section-title"' + (gi > 0 ? ' style="margin-top:20px"' : '') + '>' + g.title + ' (' + g.items.length + '종)</div>' +
        '<div class="card" style="cursor:default;margin-bottom:14px">' + fileRows + '</div>';
    }).join('');
    var tot = document.getElementById('kb-total');
    // 총계는 토글과 무관하게 '현행본 수'로 고정 — 토글에 따라 숫자가 출렁이면
    // 문서가 늘거나 준 것으로 오해된다. 감춤 건수는 괄호로 병기.
    if (tot) {
      var curCount = all.filter(function(r) { return !r.status || r.status === 'current'; }).length;
      tot.textContent = curCount + (_kbOlderCount ? ' (+비현행 ' + _kbOlderCount + ')' : '');
    }
    // 감춘 구버전·시행예정본을 알리고 펼칠 수 있게 한다(감췄다는 사실 자체를 숨기지 않는다)
    var note = '';
    if (_kbOlderCount) {
      var sup = _kbOlderCount - _kbPendingCount;
      note = '<div style="font-size:11.5px;color:var(--text-secondary);margin:0 0 12px;padding:8px 10px;'
        + 'background:var(--bg-secondary);border-radius:8px">'
        + (_kbShowOlder ? '구버전·시행예정본을 함께 표시하고 있습니다' :
            '현행본만 표시 중 — 구버전 ' + sup + '건, 시행예정 ' + _kbPendingCount + '건은 감춰져 있습니다')
        + ' <a href="#" onclick="_kbShowOlder=!_kbShowOlder;loadKbDocs(true);return false" '
        + 'style="color:var(--accent);font-weight:600;margin-left:6px">'
        + (_kbShowOlder ? '현행본만 보기' : '모두 보기') + '</a></div>';
    }
    kbSearchStatus('kb-search-count', 'kb-search-clear', 'kb-search', matched);
    var empty = kbTerms.length
      ? '<div style="color:var(--text-secondary);font-size:12px;padding:16px 0">‘' + escHtml(kbTerms.join(' ')) + '’와 일치하는 문서가 없습니다.</div>'
      : '<div style="color:var(--text-secondary);font-size:12px;padding:16px 0">등록된 문서가 없습니다.</div>';
    el.innerHTML = note + (html || empty);
    _kbDocsLoaded = true;
  } catch(e) {
    el.innerHTML = '<div style="color:var(--text-secondary);font-size:12px;padding:16px 0">목록 조회 실패: ' + e.message + '</div>';
  }
}

// ── 실무 안내 탭 (regulatory-kb / kb_documents) ─────────────────────────
// '국내 법령·고시'는 조문 원문(document_chunks), 이 탭은 요약·실무(kb_chunks) 레이어다.
// 자문 답변 하단 '참조 요약·실무' 배지에 뜨는 문서들이 여기에 있다. (배경역사 #41)
// 폴더명이 영문이라 한글 이름표로 옮겨 보여준다 — 운영자가 영문 계열명을 알 이유가 없다.
var _GUIDE_FAMILY_KO = {
  'radio-act': '전파법',
  'telecom-business-act': '전기통신사업법',
  'telecom-facility-standards': '방송통신설비 기술기준',
  'device-technical-standards': '단말장치 기술기준',
  'broadcasting-telecom-development-act': '방송통신발전 기본법',
  'kmcc-act': '방송미디어통신위원회법',
  'network-act': '정보통신망법',
  'privacy-act': '개인정보 보호법',
  'location-info-act': '위치정보법',
  'secret-protection-act': '통신비밀보호법',
  'information-infrastructure': '정보통신기반 보호',
  'disaster-safety': '재난 및 안전관리 기본법',
  'ict-industry-promotion-act': '정보통신산업 진흥법',
  'local-tax-act': '지방세법',
  'charge-management-act': '부담금관리 기본법',
  'national-finance-act': '국가재정법',
  'national-accounting-act': '국가회계법',
  'government-organization-act': '정부조직법'
};
var _GUIDE_SUB_KO = {
  'notices': '하위 고시·지침',
  'wireless-notices': '무선설비·무선국 고시',
  'spectrum-notices': '주파수 고시·공고',
  'conformity-assessment': '적합성평가 고시',
  'emf-notices': '전자파 고시',
  'radio-admin-notices': '전파행정 고시'
};

var _guideLoaded = false;
var _guideRows = [];          // list_kb_guide_docs 캐시 — 검색·접기 재렌더가 DB를 다시 치지 않도록
var _guideScope = 'all';      // 필터 칩: all | crms | laws
var _guideOpen = {};          // 펼친 노드 키 집합
var _guideAllOpen = false;
var _guideInit = false;       // 첫 렌더 여부 — 구획별 맨 위 묶음 자동 펼침용

// path → 계층. CRMS는 2단(분야 > 문서), 법령 요약은 3단(계열 > 하위 묶음 > 문서).
function _guideNodeOf(path) {
  var segs = String(path || '').split('/');
  if (segs[0] === 'procedures' && segs[1] === 'crms') {
    return { sec: 'crms', l1: (segs[2] || '').replace(/_/g, ' '), l1dir: '', l2: '', l2dir: '' };
  }
  if (segs[0] === 'laws') {
    var famDir = segs[1] || '';
    // laws/{계열}/{하위}/{파일}.md — 4조각이면 하위 묶음이 있고, 3조각이면 계열 본문이다
    var subDir = segs.length >= 4 ? (segs[2] || '') : '';
    return {
      sec: 'laws',
      l1: (_GUIDE_FAMILY_KO[famDir] || famDir) + ' 계열', l1dir: famDir,
      l2: subDir ? (_GUIDE_SUB_KO[subDir] || subDir) : '', l2dir: subDir
    };
  }
  return { sec: 'etc', l1: '기타', l1dir: segs[0] || '', l2: '', l2dir: '' };
}

// 목록 표시명 — CRMS 제목의 '중앙전파관리소 업무안내 — {분야} > ' 접두를 뗀다.
// 그룹 머리글이 이미 같은 말을 하므로, 붙여두면 한 줄이 전부 같은 글자로 보인다.
function _guideDisplayName(title) {
  var t = String(title || '').replace(/^중앙전파관리소 업무안내\s*[—-]\s*/, '');
  var gt = t.indexOf(' > ');
  return gt >= 0 ? t.slice(gt + 3) : t;
}

function toggleGuideNode(key) {
  if (_guideOpen[key]) delete _guideOpen[key]; else _guideOpen[key] = 1;
  renderGuideTree();
}
function setGuideScope(scope, el) {
  _guideScope = scope;
  document.querySelectorAll('.guide-chip').forEach(function(c) { c.classList.remove('active'); });
  if (el) el.classList.add('active');
  renderGuideTree();
}
function toggleGuideAll() {
  _guideAllOpen = !_guideAllOpen;
  _guideOpen = {};
  if (_guideAllOpen) {
    _guideRows.forEach(function(r) {
      var n = _guideNodeOf(r.path);
      _guideOpen[n.sec + '|' + n.l1] = 1;
      if (n.l2) _guideOpen[n.sec + '|' + n.l1 + '|' + n.l2] = 1;
    });
  }
  var ic = document.getElementById('guide-expand-icon'), lb = document.getElementById('guide-expand-label');
  if (ic) ic.className = 'ti ' + (_guideAllOpen ? 'ti-chevrons-up' : 'ti-chevrons-down');
  if (lb) lb.textContent = _guideAllOpen ? '모두 접기' : '모두 펼치기';
  renderGuideTree();
}

async function loadGuideDocs(force) {
  var el = document.getElementById('guide-groups');
  if (!el || !sb) return;
  try {
    if (!_guideLoaded || force) {
      // body_md는 203건 합계 681kB라 내려받지 않는다. RPC가 표 포함 여부·청크 수만 계산해 준다.
      var r = await sb.rpc('list_kb_guide_docs');
      if (r.error) throw r.error;
      _guideRows = r.data || [];
      _guideLoaded = true;
      _guideInit = true;   // 첫 렌더에서 각 구획 맨 위 묶음만 펼친다(renderGuideTree가 처리)
    }
    renderGuideTree();
  } catch(e) {
    el.innerHTML = '<div style="color:var(--text-secondary);font-size:12px;padding:16px 0">목록 조회 실패: '
      + escHtml(e && e.message ? e.message : String(e)) + '</div>';
  }
}

function renderGuideTree() {
  var el = document.getElementById('guide-groups');
  if (!el) return;
  var terms = kbSearchTerms('guide-search');

  // 1) 필터(칩 + 검색어) 통과한 문서만 계층 트리로 접는다
  var secs = { crms: { key: 'crms', l1s: [], map: {} }, laws: { key: 'laws', l1s: [], map: {} }, etc: { key: 'etc', l1s: [], map: {} } };
  var nCrms = 0, nLaws = 0, matched = 0;
  _guideRows.forEach(function(row) {
    var n = _guideNodeOf(row.path);
    if (n.sec === 'crms') nCrms++; else if (n.sec === 'laws') nLaws++;
    if (_guideScope !== 'all' && n.sec !== _guideScope) return;
    var name = _guideDisplayName(row.title);
    if (!kbNameMatches(name, terms)) return;
    matched++;
    var S = secs[n.sec];
    if (!S.map[n.l1]) { S.map[n.l1] = { name: n.l1, dir: n.l1dir, docs: [], l2s: [], l2map: {} }; S.l1s.push(S.map[n.l1]); }
    var G = S.map[n.l1];
    var item = { row: row, name: name };
    if (!n.l2) { G.docs.push(item); return; }
    if (!G.l2map[n.l2]) { G.l2map[n.l2] = { name: n.l2, dir: n.l2dir, docs: [] }; G.l2s.push(G.l2map[n.l2]); }
    G.l2map[n.l2].docs.push(item);
  });

  var nc = document.getElementById('guide-n-crms'), nl = document.getElementById('guide-n-laws');
  if (nc) nc.textContent = nCrms;
  if (nl) nl.textContent = nLaws;
  var tot = document.getElementById('guide-total');
  if (tot) tot.textContent = _guideRows.length;
  kbSearchStatus('guide-search-count', 'guide-search-clear', 'guide-search', matched);

  // 2) 그리기 — 검색 중에는 일치한 묶음을 자동으로 펼친다(접힌 채면 결과가 안 보인다)
  var auto = terms.length > 0;
  var html = ['crms', 'laws', 'etc'].map(function(sk) {
    var S = secs[sk];
    if (!S.l1s.length) return '';
    var head = sk === 'crms' ? '중앙전파관리소 업무안내 <em>· 2단</em>'
             : sk === 'laws' ? '법령 요약 <em>· 3단 (회색은 폴더 실제 이름)</em>'
             : '기타';
    S.l1s.sort(function(a, b) {
      var ca = _guideCount(a), cb = _guideCount(b);
      return cb !== ca ? cb - ca : a.name.localeCompare(b.name, 'ko');
    });
    // 첫 화면은 접힌 상태가 기본 — 203건이 쏟아지면 계층이 안 보인다. 다만 구획마다
    // 맨 위 묶음 하나는 펼쳐 둬야 "눌러서 펼치는 목록"임이 바로 드러난다.
    // 정렬 뒤에 정해야 화면 맨 위 묶음과 펼쳐진 묶음이 일치한다.
    if (_guideInit && S.l1s.length) _guideOpen[sk + '|' + S.l1s[0].name] = 1;
    var groups = S.l1s.map(function(g) {
      var k1 = sk + '|' + g.name;
      var open = auto || _guideOpen[k1];
      var rows = '<div class="guide-row l1" onclick="toggleGuideNode(\'' + escHtml(k1) + '\')">' +
        '<i class="ti ti-chevron-' + (open ? 'down' : 'right') + '"></i>' +
        '<span class="guide-label">' + escHtml(g.name) +
        (g.dir ? '<span class="guide-folder">' + escHtml(g.dir) + '</span>' : '') + '</span>' +
        '<span class="guide-count">' + _guideCount(g) + '</span></div>';
      if (open) {
        rows += g.docs.sort(_guideByName).map(function(it) { return _guideDocRow(it, terms, false); }).join('');
        rows += g.l2s.sort(function(a, b) { return b.docs.length - a.docs.length; }).map(function(s2) {
          var k2 = k1 + '|' + s2.name;
          var open2 = auto || _guideOpen[k2];
          var r2 = '<div class="guide-row l2" onclick="toggleGuideNode(\'' + escHtml(k2) + '\')">' +
            '<i class="ti ti-chevron-' + (open2 ? 'down' : 'right') + '"></i>' +
            '<span class="guide-label">' + escHtml(s2.name) +
            (s2.dir ? '<span class="guide-folder">' + escHtml(s2.dir) + '</span>' : '') + '</span>' +
            '<span class="guide-count">' + s2.docs.length + '</span></div>';
          if (open2) r2 += s2.docs.sort(_guideByName).map(function(it) { return _guideDocRow(it, terms, true); }).join('');
          return r2;
        }).join('');
      }
      return rows;
    }).join('');
    return '<div class="guide-sec">' + head + '</div>' +
           '<div class="card" style="cursor:default;padding:0;overflow:hidden">' + groups + '</div>';
  }).join('');

  el.innerHTML = html || '<div style="color:var(--text-secondary);font-size:12px;padding:16px 0">'
    + (terms.length ? '‘' + escHtml(terms.join(' ')) + '’와 일치하는 문서가 없습니다.' : '등록된 문서가 없습니다.') + '</div>';
  _guideInit = false;
}

function _guideByName(a, b) { return a.name.localeCompare(b.name, 'ko'); }

function _guideCount(g) {
  return g.docs.length + g.l2s.reduce(function(a, s) { return a + s.docs.length; }, 0);
}

function _guideDocRow(it, terms, deep) {
  // 청크 0 = 등재만 되고 자문 검색에는 안 잡히는 상태. 반드시 눈에 보여야 한다(무음 실패 방지).
  var badge = it.row.chunks === 0
    ? '<span class="guide-tbl" style="background:rgba(220,38,38,.12);color:#b91c1c" title="본문 청크가 없어 자문 검색에 잡히지 않습니다">청크 없음</span>'
    : (it.row.has_table ? '<span class="guide-tbl" title="수수료표·산정식 등 표가 들어 있습니다">표 포함</span>' : '');
  return '<div class="guide-row l3' + (deep ? ' deep' : '') + '" onclick="openGuideDoc(' + it.row.id + ')"' +
    ' title="' + escHtml(it.row.description || it.row.title) + '">' +
    '<span class="guide-label">' + kbHighlight(it.name, terms) + '</span>' + badge +
    '<i class="ti ti-chevron-right"></i></div>';
}

// 실무 안내 본문 열람 — 조문 모달을 함께 쓰되 조문 검색줄은 감춘다(요약본은 조문 단위가 아니다).
async function openGuideDoc(docId) {
  var modal = document.getElementById('kb-doc-modal');
  var bodyEl = document.getElementById('kb-doc-body');
  var row = document.getElementById('kb-doc-searchrow');
  if (!modal || !sb) return;
  modal.style.display = 'flex';
  if (row) row.style.display = 'none';
  _kbDocArticles = [];
  var meta = _guideRows.filter(function(r) { return r.id === docId; })[0] || {};
  document.getElementById('kb-doc-title').innerHTML = '<i class="ti ti-clipboard-text"></i> ' + escHtml(meta.title || '실무 안내');
  document.getElementById('kb-doc-meta').textContent =
    [meta.concept_type, meta.competent_authority, meta.description].filter(Boolean).join(' · ');
  bodyEl.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px;padding:20px 0;text-align:center">본문을 불러오는 중...</div>';
  try {
    var r = await sb.from('kb_documents').select('body_md').eq('id', docId).limit(1);
    if (r.error) throw r.error;
    var md = (r.data && r.data[0] && r.data[0].body_md) || '';
    bodyEl.innerHTML = md
      ? renderMd(md)
      : '<div style="color:var(--text-tertiary);font-size:12px;padding:20px 0;text-align:center">본문이 비어 있습니다.</div>';
    bodyEl.scrollTop = 0;
  } catch(e) {
    bodyEl.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px;padding:20px 0">본문 조회 실패: '
      + escHtml(e && e.message ? e.message : String(e)) + '</div>';
  }
}

// ── 지식베이스 법령 원문 열람 (목록 클릭 → 전체 조문 모달) ──
// 관계도의 openLawMapDoc은 '앞 6청크 미리보기'라 별도. 여기는 전체 조문 + 조문 검색.
var _kbDocArticles = [];   // [{ art, text }] — 현재 열린 문서의 조문 단위 목록

async function openKbDoc(docName) {
  var modal = document.getElementById('kb-doc-modal');
  var titleEl = document.getElementById('kb-doc-title');
  var metaEl = document.getElementById('kb-doc-meta');
  var bodyEl = document.getElementById('kb-doc-body');
  var searchEl = document.getElementById('kb-doc-search');
  if (!modal || !sb) return;
  modal.style.display = 'flex';
  if (searchEl) searchEl.value = '';
  // 실무 안내(openGuideDoc)가 감춰 놓았을 수 있으므로 조문 검색줄을 되살린다
  var searchRow = document.getElementById('kb-doc-searchrow');
  if (searchRow) searchRow.style.display = 'flex';
  var p = _kbParseName(docName);
  titleEl.innerHTML = '<i class="ti ti-file-text"></i> ' + escHtml(p.clean);
  metaEl.textContent = p.info || '';
  bodyEl.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px;padding:20px 0;text-align:center">원문을 불러오는 중...</div>';
  _kbDocArticles = [];
  try {
    // 전체 청크 — PostgREST max-rows 1000 절단 대비 range 페이지네이션 (지침 가드레일)
    var rows = [], start = 0, PAGE = 1000;
    while (true) {
      var r = await sb.from('document_chunks')
        .select('content,article_no,chunk_index')
        .eq('doc_name', docName)
        .order('chunk_index', { ascending: true })
        .range(start, start + PAGE - 1);
      if (r.error) throw r.error;
      var batch = r.data || [];
      rows = rows.concat(batch);
      if (batch.length < PAGE) break;
      start += PAGE;
    }
    if (!rows.length) {
      bodyEl.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px;padding:20px 0;text-align:center">원문 청크를 찾지 못했습니다.</div>';
      return;
    }
    // 같은 조문이 여러 청크로 쪼개진 경우 하나로 합침 (긴 조문 대응)
    var lawTitle = docName.split('(')[0].replace(/\.(pdf|md|txt)$/i, '').trim();
    rows.forEach(function(c) {
      var art = (c.article_no || '').trim();
      var text = lawmapCleanText(c.content, lawTitle);
      if (!text) return;
      var last = _kbDocArticles[_kbDocArticles.length - 1];
      if (last && art && last.art === art) { last.text += '\n' + text; return; }
      if (last && !art && !last.art) { last.text += '\n' + text; return; }
      _kbDocArticles.push({ art: art, text: text });
    });
    renderKbDocArticles(_kbDocArticles);
  } catch(e) {
    bodyEl.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px;padding:20px 0">원문 조회 실패: ' + escHtml(e && e.message ? e.message : String(e)) + '</div>';
  }
}

function renderKbDocArticles(list) {
  var bodyEl = document.getElementById('kb-doc-body');
  var countEl = document.getElementById('kb-doc-count');
  if (countEl) countEl.textContent = list.length + ' / ' + _kbDocArticles.length + '개 조문';
  if (!list.length) {
    bodyEl.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px;padding:20px 0;text-align:center">검색 결과가 없습니다.</div>';
    return;
  }
  bodyEl.innerHTML = list.map(function(a) {
    // article_no는 문서에 따라 '제38조(...)'/'38조(...)' 두 형태로 저장됨(배경역사 #28) → 표시는 '제'로 통일
    var art = a.art ? a.art.replace(/^(?!제)(?=\d)/, '제') : '';
    // 본문 첫머리가 조문 표기와 겹치면(대부분 그렇다) 헤더와 중복이므로 본문 쪽을 제거
    var text = a.text;
    if (art && text.indexOf(art) === 0) text = text.slice(art.length).replace(/^[\s:·-]+/, '');
    return '<div style="margin-bottom:16px;padding-bottom:14px;border-bottom:0.5px solid var(--border-light)">' +
      (art ? '<div style="font-size:12.5px;font-weight:600;color:var(--text-primary);margin-bottom:5px">' + escHtml(art) + '</div>' : '') +
      '<div style="white-space:pre-wrap">' + escHtml(text) + '</div></div>';
  }).join('');
  bodyEl.scrollTop = 0;
}

function filterKbDocArticles() {
  var q = (document.getElementById('kb-doc-search').value || '').trim();
  if (!q) { renderKbDocArticles(_kbDocArticles); return; }
  // '37조'로 쳐도 '제37조'가 잡히도록 조문번호 질의는 접두 '제'를 보정
  var artQ = q.replace(/^제/, '');
  var lower = q.toLowerCase();
  renderKbDocArticles(_kbDocArticles.filter(function(a) {
    var art = (a.art || '').replace(/^제/, '');
    return art.indexOf(artQ) === 0 || (a.art || '').indexOf(q) >= 0 || a.text.toLowerCase().indexOf(lower) >= 0;
  }));
}

function closeKbDoc() {
  var m = document.getElementById('kb-doc-modal');
  if (m) m.style.display = 'none';
  _kbDocArticles = [];
}

var diffState = { before: null, after: null };  // { text, name }

// ── DIFF 드롭존 UX 보강 (2026-06-12) ──
// 드롭존을 빗나가게 떨어뜨려도 브라우저가 파일을 열며 페이지를 이탈하지 않도록 전역 차단
document.addEventListener('dragover', function(e) { e.preventDefault(); });
document.addEventListener('drop', function(e) { e.preventDefault(); });
// 드롭존 진입 시 하이라이트 + 커서를 '복사'로 고정
['before', 'after'].forEach(function(t) {
  var dz = document.getElementById('drop-' + t);
  if (!dz) return;
  function clear() { dz.style.borderColor = ''; dz.style.background = ''; }
  dz.addEventListener('dragenter', function(e) {
    e.preventDefault();
    dz.style.borderColor = 'var(--accent)';
    dz.style.background = 'rgba(83,74,183,0.07)';
  });
  dz.addEventListener('dragover', function(e) {
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
  });
  dz.addEventListener('dragleave', clear);
  dz.addEventListener('drop', clear);
});

function handleDiffDrop(type, event) {
  event.preventDefault();
  var file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
  if (!file) return;
  _loadDiffFile(type, file);
}

function handleDiffFile(type, input) {
  var file = input.files && input.files[0];
  if (!file) return;
  _loadDiffFile(type, file);
}

async function _loadDiffFile(type, file) {
  var dropEl = document.getElementById('drop-' + type);
  var origHtml = dropEl ? dropEl.innerHTML : '';
  try {
    if (dropEl) {
      dropEl.innerHTML = '<span style="display:inline-block;width:16px;height:16px;border:2px solid var(--accent);border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite"></span><div style="font-size:11px">읽는 중...</div>';
    }
    var text = await _readFileAsText(file);
    diffState[type] = { text: text, name: file.name };

    if (dropEl) {
      dropEl.classList.add('loaded');
      dropEl.innerHTML =
        '<i class="ti ti-check" style="font-size:18px;color:var(--green)"></i>' +
        '<div style="font-size:11px;font-weight:600;color:var(--green);word-break:break-all;max-width:140px">' + file.name + '</div>' +
        '<div style="font-size:10px;color:var(--text-tertiary)">' + Math.ceil(text.length / 1000) + 'KB · ' + text.split('\n').length + '줄</div>';
    }

    // 두 파일 모두 준비되면 버튼 활성화
    var btn = document.getElementById('diff-analyze-btn');
    if (btn && diffState.before && diffState.after) {
      btn.disabled = false;
      btn.style.opacity = '1';
      btn.innerHTML = '<i class="ti ti-search"></i> 변경사항 분석 시작';
    }
  } catch(e) {
    alert('파일 읽기 실패: ' + e.message);
    if (dropEl) { dropEl.classList.remove('loaded'); dropEl.innerHTML = origHtml; }
  }
}

async function _readFileAsText(file) {
  if (file.name.toLowerCase().endsWith('.pdf')) {
    if (typeof pdfjsLib === 'undefined') throw new Error('PDF 파서가 로드되지 않았습니다. 잠시 후 다시 시도하거나 .txt 파일로 변환해 업로드하세요.');
    var buf = await file.arrayBuffer();
    var pdf = await pdfjsLib.getDocument({ data: buf }).promise;
    var pages = [];
    for (var i = 1; i <= pdf.numPages; i++) {
      var page = await pdf.getPage(i);
      var content = await page.getTextContent();
      // hasEOL로 원본 줄바꿈 보존 — 페이지 전체가 한 줄로 뭉치면 조문 단위 DIFF가 불가능 (2026-06-12 수정)
      pages.push(content.items.map(function(item) {
        return item.str + (item.hasEOL ? '\n' : ' ');
      }).join(''));
    }
    var full = pages.join('\n');
    // 조문 헤더 앞 줄바꿈 보강 — hasEOL 정보가 없는 PDF 대비
    full = full.replace(/[ \t]+(?=제\d+조(?:의\d+)?\()/g, '\n');
    return full;
  }
  return new Promise(function(resolve, reject) {
    var reader = new FileReader();
    reader.onload  = function(e) { resolve(e.target.result); };
    reader.onerror = function()  { reject(new Error('FileReader 오류')); };
    reader.readAsText(file, 'UTF-8');
  });
}

// ── 조문 단위 DIFF 알고리즘 ──────────────────────────────
function _computeDiff(beforeText, afterText) {
  // 한국 법령 조문 단위로 분리: 제X조, 항 번호, 번호 목록
  function toChunks(text) {
    return text
      .split(/\n(?=제\d+조|제\s*\d+\s*조|[\①-⑳]|[①②③④⑤⑥⑦⑧⑨⑩]|\d+\.\s|[가-힣]\.\s)/)
      .map(function(s) { return s.trim(); })
      .filter(function(s) { return s.length > 5; });
  }
  var bChunks = toChunks(beforeText);
  var aChunks = toChunks(afterText);

  function key(s) { return s.replace(/\s+/g,' ').slice(0,60); }
  var bKeys = new Set(bChunks.map(key));
  var aKeys = new Set(aChunks.map(key));

  var removed  = bChunks.filter(function(c) { return !aKeys.has(key(c)); });
  var added    = aChunks.filter(function(c) { return !bKeys.has(key(c)); });

  // 같은 조문 번호(제n조/제n조의m)끼리 짝지어 '변경'으로 분류
  function artKey(s) {
    var m = s.match(/^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?/);
    return m ? m[1] + (m[2] ? '의' + m[2] : '') : null;
  }
  var changed = [];
  var addedByArt = {};
  added.forEach(function(c) {
    var k = artKey(c);
    if (k && !addedByArt[k]) addedByArt[k] = c;
  });
  var stillRemoved = [];
  removed.forEach(function(c) {
    var k = artKey(c);
    if (k && addedByArt[k]) {
      changed.push({ art: k, before: c, after: addedByArt[k] });
      delete addedByArt[k];
    } else {
      stillRemoved.push(c);
    }
  });
  var changedAfters = new Set(changed.map(function(p){ return p.after; }));
  var stillAdded = added.filter(function(c) { return !changedAfters.has(c); });

  return { changed: changed, removed: stillRemoved, added: stillAdded };
}

// 단어 단위 LCS diff → 변경 부분 하이라이트 HTML 쌍 반환 (너무 길면 null)
function _tokenDiff(a, b) {
  function esc(t) { return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  var at = a.split(/(\s+)/), bt = b.split(/(\s+)/);
  var n = at.length, m = bt.length;
  if (n * m > 250000) return null;
  var dp = new Array(n + 1);
  for (var i = n; i >= 0; i--) dp[i] = new Array(m + 1).fill(0);
  for (var i = n - 1; i >= 0; i--)
    for (var j = m - 1; j >= 0; j--)
      dp[i][j] = at[i] === bt[j] ? dp[i+1][j+1] + 1 : Math.max(dp[i+1][j], dp[i][j+1]);
  var DEL = '<mark style="background:rgba(239,68,68,.22);color:#991b1b;text-decoration:line-through;border-radius:2px">';
  var ADD = '<mark style="background:rgba(34,197,94,.22);color:#14532d;border-radius:2px">';
  var outB = '', outA = '', i = 0, j = 0;
  while (i < n && j < m) {
    if (at[i] === bt[j]) { outB += esc(at[i]); outA += esc(bt[j]); i++; j++; }
    else if (dp[i+1][j] >= dp[i][j+1]) { outB += at[i].trim() ? DEL + esc(at[i]) + '</mark>' : esc(at[i]); i++; }
    else { outA += bt[j].trim() ? ADD + esc(bt[j]) + '</mark>' : esc(bt[j]); j++; }
  }
  while (i < n) { outB += at[i].trim() ? DEL + esc(at[i]) + '</mark>' : esc(at[i]); i++; }
  while (j < m) { outA += bt[j].trim() ? ADD + esc(bt[j]) + '</mark>' : esc(bt[j]); j++; }
  return { beforeHtml: outB, afterHtml: outA };
}

function _renderDiffView(diffResult) {
  var el = document.getElementById('diff-view');
  if (!el) return;
  var changed = diffResult.changed || [];
  var removed = diffResult.removed;
  var added   = diffResult.added;

  if (changed.length === 0 && removed.length === 0 && added.length === 0) {
    el.innerHTML = '<div style="color:var(--text-secondary);font-size:12px;padding:8px">변경된 조문이 자동 감지되지 않았습니다.<br>조문 형식이 다른 경우 아래 AI 분석 결과를 참고하세요.</div>';
    return;
  }

  function esc(t) { return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  var html = '';

  // 변경된 조문: 같은 조문 번호 짝 → 단어 단위 하이라이트
  changed.forEach(function(p) {
    var td = _tokenDiff(p.before.slice(0, 1500), p.after.slice(0, 1500));
    var bHtml = td ? td.beforeHtml : esc(p.before.slice(0, 400)) + (p.before.length > 400 ? '…' : '');
    var aHtml = td ? td.afterHtml  : esc(p.after.slice(0, 400))  + (p.after.length > 400 ? '…' : '');
    html += '<div style="background:rgba(245,158,11,.06);border-left:3px solid #f59e0b;padding:6px 10px;margin-bottom:4px;border-radius:0 4px 4px 0">' +
      '<div style="font-size:10px;font-weight:700;color:#d97706;margin-bottom:4px">✎ 변경 — 제' + esc(p.art) + '조</div>' +
      '<div style="font-size:11px;color:var(--text-secondary);white-space:pre-wrap;line-height:1.6;margin-bottom:6px"><span style="font-size:10px;font-weight:700;color:#ef4444">변경 전</span><br>' + bHtml + '</div>' +
      '<div style="font-size:11px;color:var(--text-primary);white-space:pre-wrap;line-height:1.6"><span style="font-size:10px;font-weight:700;color:#16a34a">변경 후</span><br>' + aHtml + '</div>' +
    '</div>';
  });

  removed.forEach(function(c) {
    html += '<div style="background:rgba(239,68,68,.07);border-left:3px solid #ef4444;padding:6px 10px;margin-bottom:4px;border-radius:0 4px 4px 0">' +
      '<div style="font-size:10px;font-weight:700;color:#ef4444;margin-bottom:2px">− 삭제 / 변경 전</div>' +
      '<div style="font-size:11px;color:#7f1d1d;white-space:pre-wrap;line-height:1.6">' + esc(c.slice(0,400)) + (c.length>400?'…':'') + '</div>' +
    '</div>';
  });

  added.forEach(function(c) {
    html += '<div style="background:rgba(34,197,94,.07);border-left:3px solid #22c55e;padding:6px 10px;margin-bottom:4px;border-radius:0 4px 4px 0">' +
      '<div style="font-size:10px;font-weight:700;color:#16a34a;margin-bottom:2px">+ 추가 / 변경 후</div>' +
      '<div style="font-size:11px;color:#14532d;white-space:pre-wrap;line-height:1.6">' + esc(c.slice(0,400)) + (c.length>400?'…':'') + '</div>' +
    '</div>';
  });

  el.innerHTML = html;
}

// ── 메인 분석 함수 ────────────────────────────────────────
async function runDiffAnalysis() {
  if (!diffState.before || !diffState.after) return;
  var { claudeKey } = getConfig();
  if (!claudeKey) { alert('Claude API 키가 설정에 없습니다.'); return; }

  var btn       = document.getElementById('diff-analyze-btn');
  var resultEl  = document.getElementById('diff-result');
  var aiResultEl = document.getElementById('diff-ai-result');

  if (btn) { btn.disabled = true; btn.style.opacity = '.6'; btn.innerHTML = '<span style="display:inline-block;width:14px;height:14px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite;vertical-align:middle;margin-right:6px"></span>분석 중...'; }
  if (resultEl)   resultEl.style.display = 'block';
  if (aiResultEl) aiResultEl.innerHTML = '<div style="display:flex;align-items:center;gap:8px;color:var(--text-secondary);padding:12px"><span style="display:inline-block;width:14px;height:14px;border:2px solid var(--accent);border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite"></span>AI 분석 중 (Claude Sonnet)…</div>';

  try {
    // DIFF 시각화
    var diffResult = _computeDiff(diffState.before.text, diffState.after.text);
    _renderDiffView(diffResult);

    // Claude 호출 — 자동 추출된 변경 조문 전체를 전달 (문서 전체 커버, 4000자 절단 문제 해결)
    var diffParts = [];
    (diffResult.changed || []).forEach(function(p) {
      diffParts.push('[변경 — 제' + p.art + '조]\n(변경 전)\n' + p.before + '\n(변경 후)\n' + p.after);
    });
    diffResult.removed.forEach(function(c) { diffParts.push('[삭제된 조문]\n' + c); });
    diffResult.added.forEach(function(c) { diffParts.push('[신설된 조문]\n' + c); });
    var diffText = diffParts.join('\n\n').slice(0, 24000);

    var sysMsg =
      'SK텔레콤 Comm센터 기술정책팀 전파정책 전문가 수석 위원. ' +
      '개정 전·후 법령 원문을 비교하여 SKT 사업에 미치는 영향을 구조적으로 분석한다. ' +
      '반드시 아래 XML 형식으로만 답변:\n' +
      '<summary>주요 변경사항 요약 (3~5줄, 조문 번호 포함)</summary>\n' +
      '<risks>SKT에 불리한 독소조항 (조문 번호·내용·이유 명시. 없으면 "없음")</risks>\n' +
      '<favorable>SKT에 유리한 조항 (조문 번호·내용·이유 명시. 없으면 "없음")</favorable>\n' +
      '<actions>팀 대응 액션 아이템 (각 항목을 || 로 구분)</actions>\n' +
      '<urgency>즉시대응/금주검토/중장기검토 중 하나</urgency>';

    var userMsg;
    if (diffText) {
      userMsg =
        '[파일명: ' + diffState.before.name + ' → ' + diffState.after.name + ']\n\n' +
        '아래는 두 문서 전체를 조문 단위로 비교해 자동 추출한 변경 사항이다:\n\n' + diffText;
    } else {
      // 자동 diff 미감지 시 원문 발췌 비교로 폴백
      userMsg =
        '[파일명: ' + diffState.before.name + ' → ' + diffState.after.name + ']\n\n' +
        '(조문 단위 자동 비교가 감지되지 않아 원문 발췌를 비교한다)\n\n' +
        '[개정 전]\n' + diffState.before.text.slice(0, 8000) + '\n\n' +
        '[개정 후]\n' + diffState.after.text.slice(0, 8000);
    }

    var res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'x-api-key': claudeKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json', 'anthropic-dangerous-direct-browser-access': 'true' },
      // thinking:disabled — Sonnet 5 적응형 추론이 응답 첫 블록을 빈 thinking 블록으로 만들어 content[0].text가 비어 파싱 실패했음(무음 오류).
      body: JSON.stringify({ model: 'claude-sonnet-5', max_tokens: 4000, thinking: { type: 'disabled' }, system: sysMsg, messages: [{ role: 'user', content: userMsg }] })
    });
    if (!res.ok) {
      var errBody = await res.json().catch(function() { return {}; });
      throw new Error((errBody.error && errBody.error.message) || ('Claude API 오류 (HTTP ' + res.status + ')'));
    }
    var data = await res.json();
    // content[0]을 가정하지 말고 text 블록을 찾아서 사용
    var txtBlock = data.content && data.content.find(function(b) { return b.type === 'text'; });
    var txt = (txtBlock && txtBlock.text) || '';

    var summaryM   = txt.match(/<summary>([\s\S]*?)<\/summary>/);
    var risksM     = txt.match(/<risks>([\s\S]*?)<\/risks>/);
    var favorableM = txt.match(/<favorable>([\s\S]*?)<\/favorable>/);
    var actionsM   = txt.match(/<actions>([\s\S]*?)<\/actions>/);
    var urgencyM   = txt.match(/<urgency>([\s\S]*?)<\/urgency>/);

    var summary   = summaryM   ? summaryM[1].trim()   : '분석 결과를 파싱하지 못했습니다.';
    var risks     = risksM     ? risksM[1].trim()     : '없음';
    var favorable = favorableM ? favorableM[1].trim() : '없음';
    var actions   = actionsM   ? actionsM[1].trim().split('||').map(function(a){return a.trim();}).filter(Boolean) : [];
    var urgency   = urgencyM   ? urgencyM[1].trim()   : '';

    var urgencyColor = urgency === '즉시대응' ? '#ef4444' : urgency === '금주검토' ? '#f59e0b' : '#22c55e';

    var actionsHtml = actions.map(function(a, i) {
      return '<div style="display:flex;align-items:flex-start;gap:8px;padding:7px 0;border-bottom:0.5px solid var(--border-light)">' +
        '<span style="background:var(--accent);color:#fff;border-radius:50%;width:18px;height:18px;min-width:18px;display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;margin-top:1px">' + (i+1) + '</span>' +
        '<span style="font-size:12px;line-height:1.6">' + a + '</span>' +
      '</div>';
    }).join('');

    if (aiResultEl) {
      aiResultEl.innerHTML =
        // 헤더: 파일명 + 대응 긴급도
        '<div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid var(--border)">' +
          '<span style="font-size:11px;background:rgba(239,68,68,.1);color:#ef4444;padding:2px 8px;border-radius:4px;white-space:nowrap">' + diffState.before.name + '</span>' +
          '<i class="ti ti-arrow-right" style="color:var(--text-tertiary);font-size:13px;flex-shrink:0"></i>' +
          '<span style="font-size:11px;background:rgba(34,197,94,.1);color:#16a34a;padding:2px 8px;border-radius:4px;white-space:nowrap">' + diffState.after.name + '</span>' +
          (urgency ? '<span style="margin-left:auto;font-size:11px;font-weight:700;color:' + urgencyColor + ';background:rgba(0,0,0,.04);padding:2px 8px;border-radius:4px;white-space:nowrap">⚡ ' + urgency + '</span>' : '') +
        '</div>' +

        // 주요 변경사항
        '<div style="margin-bottom:14px">' +
          '<div style="font-size:10px;font-weight:700;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.6px;margin-bottom:7px">● 주요 변경사항</div>' +
          '<div style="font-size:12px;line-height:1.8;color:var(--text-primary)">' + summary.replace(/\n/g,'<br>') + '</div>' +
        '</div>' +

        // 독소조항 (불리)
        (risks !== '없음' && risks ?
          '<div style="margin-bottom:14px;padding:10px 14px;background:rgba(239,68,68,.06);border-radius:var(--radius-md);border-left:3px solid #ef4444">' +
            '<div style="font-size:10px;font-weight:700;color:#ef4444;margin-bottom:6px">⚠ SKT 불리 조항 · 독소조항</div>' +
            '<div style="font-size:12px;line-height:1.8;color:var(--text-primary)">' + risks.replace(/\n/g,'<br>') + '</div>' +
          '</div>' : '') +

        // 유리 조항
        (favorable !== '없음' && favorable ?
          '<div style="margin-bottom:14px;padding:10px 14px;background:rgba(34,197,94,.06);border-radius:var(--radius-md);border-left:3px solid #22c55e">' +
            '<div style="font-size:10px;font-weight:700;color:#16a34a;margin-bottom:6px">✓ SKT 유리 조항</div>' +
            '<div style="font-size:12px;line-height:1.8;color:var(--text-primary)">' + favorable.replace(/\n/g,'<br>') + '</div>' +
          '</div>' : '') +

        // 팀 액션
        (actionsHtml ?
          '<div>' +
            '<div style="font-size:10px;font-weight:700;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.6px;margin-bottom:7px">● 팀 액션 아이템</div>' +
            actionsHtml +
          '</div>' : '') +

        // AI 자문 연동
        '<div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--border)">' +
          '<button onclick="askQ(\'개정된 법령의 SKT 영향을 상세히 분석해줘. 법령명: ' + diffState.after.name.replace(/'/g,"\\'") + '\')" class="btn btn-primary" style="width:100%;font-size:12px;justify-content:center">' +
            '<i class="ti ti-message-2"></i> AI 자문에서 추가 질의' +
          '</button>' +
        '</div>';
    }

  } catch(e) {
    console.warn('DIFF 분석 오류:', e);
    if (aiResultEl) aiResultEl.innerHTML = '<div style="color:#ef4444;font-size:12px;padding:12px">분석 실패: ' + e.message + '</div>';
  } finally {
    if (btn) { btn.disabled = false; btn.style.opacity = '1'; btn.innerHTML = '<i class="ti ti-refresh"></i> 다시 분석'; }
  }
}

// ════════════════════════════════════════════
//  법령 DIFF — 자동 감지 개정 목록 (law_diffs, 2026-08-02)
//  수동 업로드 플로우(_computeDiff/_renderDiffView/runDiffAnalysis)와 별개 —
//  law_diffs 테이블에 쌓인 분석 결과를 읽기만 한다.
// ════════════════════════════════════════════
var _lawDiffsCache = null;
var _lawDiffsLoadPromise = null;   // go('diff')가 잡아두는 로드 Promise — 국회 법안 화면에서 DIFF 딥링크 시 await 용

// enf_date 'YYYYMMDD' → 'YYYY-MM-DD'
function _fmtEnfDate(d) {
  var s = String(d || '');
  return /^\d{8}$/.test(s) ? s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8) : s;
}

// 오늘 날짜(KST) 'YYYY-MM-DD'
function _todayKstStr() {
  return new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10);
}

// 국회 입법예고(origin='assembly' proposed)의 의견마감(enf_date) 경과 여부
function _lawDiffCommentExpired(r) {
  if (!r || r.diff_kind !== 'proposed' || r.origin !== 'assembly') return false;
  var d = _fmtEnfDate(r.enf_date);
  return /^\d{4}-\d{2}-\d{2}$/.test(d) && d < _todayKstStr();
}

// 목록 행에 붙는 한 줄 요약 — 총괄 요약(summary)의 앞 문장을 잘라 쓴다(국회 법안 목록의 요약 줄과 같은 취지).
function _lawDiffBriefLine(r) {
  var s = (r.summary || '').replace(/\s+/g, ' ').trim();
  if (!s) return '';
  s = s.replace(/^(이|이번|본)\s*(개정안|전부개정안|개정)은\s*/, '');   // 매 항목 반복되는 상투어 제거
  if (s.length > 120) {
    var cut = s.slice(0, 120);
    var p = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('며 '), cut.lastIndexOf(', '));
    s = (p > 60 ? cut.slice(0, p + 1) : cut) + '…';
  }
  return '<div style="margin-top:6px;font-size:11px;line-height:1.5;color:var(--text-secondary)">' +
         '<span style="background:#ede9fe;color:#5b21b6;padding:1px 5px;border-radius:4px;font-size:10px;font-weight:600;margin-right:5px">요약</span>' +
         escHtml(s) + '</div>';
}

function _lawDiffKindBadge(kind, origin) {
  if (kind === 'proposed') {
    if (origin === 'assembly')
      return '<span style="font-size:10px;background:rgba(239,68,68,.12);color:#dc2626;padding:1px 7px;border-radius:4px;white-space:nowrap;font-weight:700">의견제출 가능 · 국회</span>';
    return '<span style="font-size:10px;background:rgba(239,68,68,.12);color:#dc2626;padding:1px 7px;border-radius:4px;white-space:nowrap;font-weight:700">입법예고 · 의견제출 가능</span>';
  }
  return kind === 'promoted'
    ? '<span style="font-size:10px;background:rgba(34,197,94,.12);color:#16a34a;padding:1px 7px;border-radius:4px;white-space:nowrap">개정 시행</span>'
    : '<span style="font-size:10px;background:rgba(59,130,246,.12);color:#2563eb;padding:1px 7px;border-radius:4px;white-space:nowrap">시행예정 개정</span>';
}

// proposed는 enf_date에 의견마감일이 들어온다 — 라벨 구분
function _lawDiffDateLabel(kind) { return kind === 'proposed' ? '의견마감' : '시행일'; }

async function loadLawDiffs(force) {
  var listEl = document.getElementById('diff-auto-list');
  if (!listEl || !sb) return;
  var detailEl = document.getElementById('diff-auto-detail');
  if (detailEl) detailEl.style.display = 'none';
  listEl.style.display = '';

  if (!_lawDiffsCache || force) {
    listEl.innerHTML = '<div style="color:var(--text-secondary);padding:20px;text-align:center;font-size:12px">로딩 중...</div>';
    try {
      var resp = await sb.from('law_diffs')
        .select('law_name, law_no, enf_date, diff_kind, origin, new_doc, summary, impact, urgency, articles, stats, analyzed_at')
        .order('analyzed_at', { ascending: false })
        .limit(50);
      if (resp.error) throw resp.error;
      _lawDiffsCache = resp.data || [];
    } catch (e) {
      listEl.innerHTML = '<div style="color:#f66;padding:20px;text-align:center;font-size:12px">불러오기 실패: ' + escHtml((e && e.message) || String(e)) + '</div>';
      return;
    }
  }

  var rows = _lawDiffsCache;
  if (rows.length === 0) {
    listEl.innerHTML = '<div style="color:var(--text-secondary);padding:20px;text-align:center;font-size:12px">아직 감지된 개정이 없습니다</div>';
    return;
  }

  // 관련도 우선 정렬 (운영자 지시 2026-08-02): ①직접(전파법·전기통신사업법·방발법 계열 —
  // 법령명 포함 매칭이라 시행령·시행규칙·고시도 같은 단계) ②통신 관련 ③기타. 단계 내 최신순.
  var DIFF_TIER1 = ['전파법', '전기통신사업법', '방송통신발전'];
  var DIFF_TIER2 = ['정보통신망', '방송법', '위치정보', '단말기', '정보통신 진흥', '지능정보'];
  function _lawDiffTier(name) {
    name = name || '';
    for (var a = 0; a < DIFF_TIER1.length; a++) if (name.indexOf(DIFF_TIER1[a]) !== -1) return 1;
    for (var b = 0; b < DIFF_TIER2.length; b++) if (name.indexOf(DIFF_TIER2[b]) !== -1) return 2;
    return 3;
  }
  // 단계 우선 정렬 (운영자 지시): 입법예고(의견제출로 개입 가능 — 유일한 대응 구간) →
  // 시행예정(공포됨·준비) → 시행 완료(확정·후속만). 그 안에서 관련도 → 최신순.
  var KIND_ORDER = { proposed: 0, pending: 1, promoted: 2 };
  rows = rows.slice().sort(function(x, y) {
    var k = (KIND_ORDER[x.diff_kind] !== undefined ? KIND_ORDER[x.diff_kind] : 9)
          - (KIND_ORDER[y.diff_kind] !== undefined ? KIND_ORDER[y.diff_kind] : 9);
    if (k !== 0) return k;
    // proposed 그룹 내: 국회(origin='assembly') 행 중 의견마감 경과분은 하위로
    var e = (_lawDiffCommentExpired(x) ? 1 : 0) - (_lawDiffCommentExpired(y) ? 1 : 0);
    if (e !== 0) return e;
    var t = _lawDiffTier(x.law_name) - _lawDiffTier(y.law_name);
    if (t !== 0) return t;
    return (y.analyzed_at || '').localeCompare(x.analyzed_at || '');
  });
  _lawDiffsCache = rows;   // openLawDiff(idx)가 정렬된 순서 기준으로 조회하도록 캐시 갱신

  var URG_COLOR = { high: '#ef4444', medium: '#f59e0b', low: '#9ca3af' };
  listEl.innerHTML = rows.map(function(r, i) {
    var st = r.stats || {};
    var urgDot = '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:'
      + (URG_COLOR[r.urgency] || URG_COLOR.low) + ';flex-shrink:0" title="긴급도: ' + escHtml(r.urgency || 'low') + '"></span>';
    return '<div class="card" style="cursor:pointer;padding:12px 14px;margin-bottom:8px" onclick="openLawDiff(' + i + ')">' +
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">' +
        urgDot +
        '<span style="flex:1;font-size:12px;font-weight:600;color:var(--text-primary);line-height:1.4">' + escHtml(r.law_name || '') + '</span>' +
        _lawDiffKindBadge(r.diff_kind, r.origin) +
      '</div>' +
      '<div style="display:flex;gap:10px;flex-wrap:wrap;font-size:10px;color:var(--text-muted)">' +
        '<span>변경 ' + (st.modified || 0) + ' · 신설 ' + (st.added || 0) + ' · 삭제 ' + (st.deleted || 0) + '</span>' +
        (r.enf_date ? '<span>' + _lawDiffDateLabel(r.diff_kind) + ' ' + escHtml(_fmtEnfDate(r.enf_date)) + '</span>' : '') +
      '</div>' +
      _lawDiffBriefLine(r) +
    '</div>';
  }).join('');
}

function closeLawDiff() {
  var detailEl = document.getElementById('diff-auto-detail');
  var listEl = document.getElementById('diff-auto-list');
  if (detailEl) detailEl.style.display = 'none';
  if (listEl) listEl.style.display = '';
}

// 조문 변경유형 색 — 기존 _renderDiffView 색 규약(modified 주황/added 초록/deleted 빨강)
var _DIFF_CHANGE_META = {
  modified: { label: '변경', color: '#d97706', bg: 'rgba(245,158,11,.1)' },
  added:    { label: '신설', color: '#16a34a', bg: 'rgba(34,197,94,.1)' },
  deleted:  { label: '삭제', color: '#ef4444', bg: 'rgba(239,68,68,.1)' }
};

function openLawDiff(idx) {
  var row = _lawDiffsCache && _lawDiffsCache[idx];
  var detailEl = document.getElementById('diff-auto-detail');
  var listEl = document.getElementById('diff-auto-list');
  if (!row || !detailEl) return;
  if (listEl) listEl.style.display = 'none';

  var html =
    '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap">' +
      '<button class="btn" style="font-size:11px;padding:3px 10px" onclick="closeLawDiff()"><i class="ti ti-arrow-left"></i> 목록으로</button>' +
      '<span style="font-size:13px;font-weight:600;color:var(--text-primary)">' + escHtml(row.law_name || '') + '</span>' +
      (row.law_no ? '<span style="font-size:11px;color:var(--text-muted)">' + escHtml(row.law_no) + '</span>' : '') +
    '</div>';

  // ① 총괄 카드 — 기존 diff-ai-result 카드 스타일 재사용
  html += '<div class="card" style="cursor:default;padding:16px;margin-bottom:12px">' +
    '<div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid var(--border)">' +
      _lawDiffKindBadge(row.diff_kind, row.origin) +
      (row.enf_date ? '<span style="font-size:11px;color:var(--text-secondary)">' + _lawDiffDateLabel(row.diff_kind) + ' ' + escHtml(_fmtEnfDate(row.enf_date)) + '</span>' : '') +
      (row.analyzed_at ? '<span style="margin-left:auto;font-size:10px;color:var(--text-muted)">분석 ' + escHtml(String(row.analyzed_at).slice(0, 10)) + '</span>' : '') +
    '</div>' +
    (row.diff_kind === 'proposed'
      ? '<div style="font-size:11px;color:#dc2626;background:rgba(239,68,68,.07);border-radius:6px;padding:8px 10px;margin-bottom:12px">확정 전 개정<b>안</b> 기준입니다 — 의견제출로 대응 가능한 단계이며, 공포되면 확정본 DIFF로 자동 대체됩니다.</div>'
      : '') +
    '<div style="margin-bottom:14px">' +
      '<div style="font-size:10px;font-weight:700;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.6px;margin-bottom:7px">● 총괄 요약</div>' +
      '<div style="font-size:12px;line-height:1.8;color:var(--text-primary)">' + escHtml(row.summary || '—').replace(/\n/g, '<br>') + '</div>' +
    '</div>' +
    '<div>' +
      '<div style="font-size:10px;font-weight:700;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.6px;margin-bottom:7px">● SKT 영향</div>' +
      '<div style="font-size:12px;line-height:1.8;color:var(--text-primary)">' + escHtml(row.impact || '—').replace(/\n/g, '<br>') + '</div>' +
    '</div>' +
  '</div>';

  // ② 조문 표
  var arts = Array.isArray(row.articles) ? row.articles : [];
  if (arts.length === 0) {
    html += '<div style="color:var(--text-secondary);font-size:12px;padding:14px;background:var(--bg-secondary);border-radius:var(--radius-md)">전부개정 — 조문 표 생략</div>';
  } else {
    var cellStyle = 'font-size:11px;line-height:1.6;vertical-align:top;padding:8px;border-bottom:0.5px solid var(--border-light)';
    var bodyRows = arts.map(function(a) {
      var meta = _DIFF_CHANGE_META[a.change] || { label: a.change || '—', color: 'var(--text-muted)', bg: 'transparent' };
      var bHtml, aHtml;
      // modified는 기존 _tokenDiff 재사용 — <mark> 하이라이트 (null이면 plain, _tokenDiff는 내부 esc)
      if (a.change === 'modified' && a.before && a.after) {
        var td = _tokenDiff(String(a.before).slice(0, 1500), String(a.after).slice(0, 1500));
        if (td) { bHtml = td.beforeHtml; aHtml = td.afterHtml; }
      }
      if (bHtml === undefined) bHtml = escHtml(a.before || '');
      if (aHtml === undefined) aHtml = escHtml(a.after || '');
      return '<tr>' +
        '<td style="' + cellStyle + ';white-space:nowrap;font-weight:600">' + escHtml(a.article_no || '') + '</td>' +
        '<td style="' + cellStyle + ';white-space:nowrap"><span style="font-size:10px;font-weight:700;color:' + meta.color + ';background:' + meta.bg + ';padding:1px 7px;border-radius:4px">' + escHtml(meta.label) + '</span></td>' +
        '<td style="' + cellStyle + ';min-width:220px"><div style="max-height:180px;overflow-y:auto;white-space:pre-wrap">' + bHtml + '</div></td>' +
        '<td style="' + cellStyle + ';min-width:220px"><div style="max-height:180px;overflow-y:auto;white-space:pre-wrap">' + aHtml + '</div></td>' +
        '<td style="' + cellStyle + ';min-width:160px">' + escHtml(a.impact || '') + '</td>' +
      '</tr>';
    }).join('');
    var headCells = ['조문', '변경', '개정 전', '개정 후', '영향'].map(function(h) {
      return '<th style="font-size:10px;font-weight:700;color:var(--text-secondary);text-align:left;padding:8px;border-bottom:1px solid var(--border);white-space:nowrap">' + h + '</th>';
    }).join('');
    html += '<div style="font-size:11px;font-weight:700;color:var(--text-secondary);margin-bottom:8px">● 조문별 변경사항</div>' +
      '<div style="overflow-x:auto;background:var(--bg-secondary);border-radius:var(--radius-md)">' +
        '<table style="width:100%;border-collapse:collapse;min-width:760px">' +
          '<thead><tr>' + headCells + '</tr></thead>' +
          '<tbody>' + bodyRows + '</tbody>' +
        '</table>' +
      '</div>';
  }

  detailEl.innerHTML = html;
  detailEl.style.display = '';
}

// ════════════════════════════════════════════
//  Daily Briefing — Supabase daily_briefings 표시
// ════════════════════════════════════════════

// 브리핑 텍스트용 중요도 분류 (구조화된 news 객체 없이 raw 텍스트로 판별)
function classifyBriefingItemImportance(text) {
  var hay = text.toLowerCase();
  var urgentKws = IMPORTANCE_RULES['긴급'].keywords;
  for (var i = 0; i < urgentKws.length; i++) {
    if (hay.includes(urgentKws[i].toLowerCase())) return '긴급';
  }
  var isRelevant = SKT_RELEVANT_TOPICS.some(function(t) { return hay.includes(t.toLowerCase()); });
  var isNegative = NEGATIVE_SIGNALS.some(function(s) { return hay.includes(s.toLowerCase()); });
  if (isRelevant && isNegative) return '긴급';
  var normalKws = IMPORTANCE_RULES['보통'].keywords;
  for (var i = 0; i < normalKws.length; i++) {
    if (hay.includes(normalKws[i].toLowerCase())) return '보통';
  }
  if (isRelevant) return '보통';
  return '참고';
}

// 비뉴스 섹션(주목 포인트·기술 용어 등) bullet 항목 렌더링
// 마크다운 굵게(**...**) → <strong> (esc 이후 적용 — 우리가 넣는 안전한 태그)
function mdBold(s) { return (s || '').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>'); }

function renderPlainBulletItem(block) {
  var lines = block.split('\n');
  var out = '';
  for (var i = 0; i < lines.length; i++) {
    var l = lines[i];
    if (/^• /.test(l)) {
      out += '<div style="font-size:13px;line-height:1.8;padding-left:2px">• ' + mdBold(l.replace(/^• /, '')) + '</div>';
    } else if (/^  → /.test(l)) {
      out += '<div style="font-size:12px;color:var(--text-secondary);padding-left:16px;line-height:1.6">→ ' + mdBold(l.replace(/^  → /, '')) + '</div>';
    } else if (/^  🔗 /.test(l)) {
      var url = l.replace(/^  🔗 /, '').trim();
      out += '<div style="padding-left:16px;font-size:12px;margin-top:2px"><a href="' + url + '" target="_blank" style="color:var(--accent);text-decoration:none">🔗 원문 보기</a></div>';
    } else if (l.trim()) {
      out += '<div style="font-size:13px;line-height:1.8">' + mdBold(l) + '</div>';
    }
  }
  return '<div style="margin-bottom:6px">' + out + '</div>';
}

// 브리핑 콘텐츠 파싱 — 섹션 순서 보존, 뉴스 섹션만 긴급도 분류
// ※ 분류는 원본(raw) 텍스트로, HTML 출력은 이스케이프 적용
function parseBriefingContent(rawContent, briefingIdx) {
  function esc(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  var rawLines = (rawContent || '').split('\n');
  var output = [];
  var rawItemLines = [];   // 원본 텍스트 줄 (분류용)
  var itemIdx = 0;
  var urgentCount = 0;
  var urgentItems = [];    // [{elemId, title}] — 분석 트리거에 사용
  var currentSection = 'news';

  function flushItem() {
    if (rawItemLines.length === 0) return;
    var rawBlock = rawItemLines.join('\n');
    if (currentSection === 'news') {
      // 긴급 여부는 브리핑 원문의 🔴(크롤러 긴급도 기반)로만 판정 — 이메일과 항상 일치
      var importance = rawBlock.indexOf('🔴') !== -1 ? '긴급' : '참고';
      var hasStoredAnalysis = rawBlock.indexOf('SKT 영향 분석') !== -1;
      // 렌더링은 이스케이프된 텍스트 기준
      var escBlock = rawItemLines.map(function(l){ return esc(l); }).join('\n');
      output.push(renderBriefingNewsItem(escBlock, importance, briefingIdx, itemIdx));
      if (importance === '긴급') {
        urgentCount++;
        // 저장된 분석이 있으면 즉석 생성 불필요 (구버전 브리핑만 폴백)
        if (!hasStoredAnalysis) {
          var titleRaw = '';
          for (var i = 0; i < rawItemLines.length; i++) {
            if (/^• /.test(rawItemLines[i])) { titleRaw = rawItemLines[i].replace(/^• /, ''); break; }
          }
          urgentItems.push({ elemId: 'bi-' + briefingIdx + '-' + itemIdx, title: titleRaw });
        }
      }
    } else {
      var escBlock = rawItemLines.map(function(l){ return esc(l); }).join('\n');
      output.push(renderPlainBulletItem(escBlock));
    }
    itemIdx++;
    rawItemLines = [];
  }

  for (var li = 0; li < rawLines.length; li++) {
    var line = rawLines[li].replace(/^\s*#{1,6}\s+/, '');  // 마크다운 헤더 기호(#, ##) 제거
    var trimmed = line.trim();

    // 섹션 헤더 [주요 뉴스], [주목 포인트], [기술 용어] 등
    if (/^\[.+\]$/.test(trimmed)) {
      flushItem();
      currentSection = /뉴스|news/i.test(trimmed) ? 'news' : 'other';
      output.push('<div style="font-weight:600;font-size:12px;color:var(--text-secondary);margin:14px 0 8px;letter-spacing:0.04em">' + mdBold(esc(trimmed)) + '</div>');
      continue;
    }
    // 제목 헤더 (📡)
    if (/^📡/.test(line)) {
      flushItem();
      output.push('<div style="font-size:15px;font-weight:700;color:var(--accent);margin:22px 0 12px;padding-top:14px;border-top:1px solid var(--border, #e5e7eb)">' + esc(line) + '</div>');
      continue;
    }
    // bullet 항목 시작
    if (/^• /.test(line)) {
      flushItem();
      rawItemLines.push(line);
      continue;
    }
    // 들여쓰기 줄 — 현재 항목에 추가
    if (/^  /.test(line) && rawItemLines.length > 0) {
      rawItemLines.push(line);
      continue;
    }
    // 빈 줄 — 항목 종료
    if (trimmed === '' && rawItemLines.length > 0) {
      flushItem();
      output.push('<div style="height:4px"></div>');
      continue;
    }
    // 일반 텍스트 / 느슨한 줄 (입법예고 📢·🔴·→·🔗 블록 포함)
    if (rawItemLines.length > 0) {
      rawItemLines.push(line);
    } else if (!trimmed) {
      output.push('<div style="height:4px"></div>');
    } else if (/^🔗\s*\S/.test(trimmed)) {
      var looseUrl = trimmed.replace(/^🔗\s*/, '').trim();
      output.push('<div style="padding-left:18px;font-size:12px;margin-top:2px"><a href="' + esc(looseUrl) + '" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none">🔗 원문 보기</a></div>');
    } else if (/^→\s/.test(trimmed)) {
      output.push('<div style="font-size:12px;color:var(--text-secondary);padding-left:18px;line-height:1.6;margin-top:2px">' + mdBold(esc(trimmed)) + '</div>');
    } else if (/^📢/.test(trimmed)) {
      output.push('<div style="font-weight:700;font-size:13px;color:var(--accent);margin:14px 0 6px">' + mdBold(esc(trimmed)) + '</div>');
    } else if (/^🔴/.test(trimmed)) {
      output.push('<div style="font-weight:600;font-size:13px;line-height:1.6;margin-top:2px">' + mdBold(esc(trimmed)) + '</div>');
    } else {
      output.push('<div style="font-size:13px;line-height:1.8">' + mdBold(esc(line)) + '</div>');
    }
  }
  flushItem();

  return { html: output.join(''), urgentCount: urgentCount, urgentItems: urgentItems };
}

// 뉴스 항목 1건 HTML 렌더링
function renderBriefingNewsItem(block, importance, briefingIdx, itemIdx) {
  var lines = block.split('\n');
  var titleLine = '';
  var summaryLines = [];
  var linkUrl = '';
  var storedAnalysis = '';

  for (var i = 0; i < lines.length; i++) {
    var l = lines[i];
    if (/^• /.test(l)) {
      titleLine = l.replace(/^• /, '').replace(/\s*\[ID:[^\]]+\]/g, '').replace(/🔴\s*/g, '');
    } else if (/^  🔗 /.test(l)) {
      linkUrl = l.replace(/^  🔗 /, '').trim();
    } else if (/^  → /.test(l)) {
      summaryLines.push(l.replace(/^  → /, '').trim());
    } else if (l.indexOf('SKT 영향 분석') !== -1) {
      storedAnalysis = l.replace(/^\s*⚠️\s*SKT 영향 분석[::]\s*/, '').trim();
    }
  }

  var titleHtml = '<span data-news-title="1" style="font-weight:500;font-size:13px;line-height:1.6">' + mdBold(titleLine) + '</span>';
  var summaryHtml = summaryLines.map(function(s) {
    return '<div style="font-size:12px;color:var(--text-secondary);padding-left:4px;margin-top:3px;line-height:1.6">→ ' + mdBold(s) + '</div>';
  }).join('');
  var linkHtml = linkUrl
    ? '<div style="margin-top:6px"><a href="' + linkUrl + '" target="_blank" style="font-size:12px;color:var(--accent);text-decoration:none">🔗 원문 보기</a></div>'
    : '';

  var analysisId = 'bi-' + briefingIdx + '-' + itemIdx;

  if (importance === '긴급') {
    var rule = IMPORTANCE_RULES['긴급'];
    return '<div style="border:2px solid ' + rule.color + ';border-radius:10px;padding:12px 14px;margin-bottom:10px;background:' + rule.bg + '">'
      + '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">'
      +   '<span style="background:' + rule.color + ';color:#fff;font-size:10px;font-weight:700;padding:2px 9px;border-radius:5px;flex-shrink:0">중요</span>'
      + '</div>'
      + '<div style="margin-bottom:6px">' + titleHtml + '</div>'
      + summaryHtml
      + linkHtml
      + '<div id="' + analysisId + '" data-briefing-analysis="1" style="margin-top:10px;padding:10px 12px;background:rgba(239,68,68,0.06);border-radius:8px;border:1px solid rgba(239,68,68,0.2)">'
      +   (storedAnalysis
          ? '<div style="font-size:12px;color:var(--text-primary);line-height:1.7"><span style="font-weight:700">⚠️ SKT 영향 분석</span> ' + mdBold(storedAnalysis) + '</div>'
          : '<div style="display:flex;align-items:center;gap:7px;font-size:12px;color:var(--text-secondary)">'
            + '<span style="display:inline-block;width:12px;height:12px;border:2px solid var(--accent);border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite"></span>'
            + 'AI 영향도 분석 중...'
            + '</div>')
      + '</div>'
      + '</div>';
  }

  // 보통·참고 — 별도 표시 없이 일반 텍스트
  return '<div style="padding:6px 0;margin-bottom:6px">'
    + '<div style="margin-bottom:4px">' + titleHtml + '</div>'
    + summaryHtml
    + linkHtml
    + '</div>';
}

// 긴급 항목 AI 영향도 분석 — DOM 요소를 직접 참조로 받음 (ID 탐색 없음)
async function analyzeBriefingItemEl(el, titleText) {
  if (!el) return;
  var { claudeKey } = getConfig();
  if (!claudeKey) {
    el.innerHTML = '<span style="font-size:11px;color:var(--text-secondary)">Claude API 키가 설정되지 않아 분석을 건너뜁니다.</span>';
    return;
  }
  try {
    var sysMsg = SKT_IMPACT_SYSTEM_PROMPT;

    // 뉴스 캐시에서 제목 일치 기사를 찾아 본문 보강
    var cached = (typeof newsDataCache !== 'undefined') && newsDataCache.find(function(x) {
      return x.title && titleText && x.title.replace(/\s+/g,'').includes(titleText.replace(/\s+/g,'').slice(0,20));
    });
    // 캐시는 content 없이 로드되므로(#61) 필요 시 해당 1건만 온디맨드 조회
    if (cached && cached.content === undefined && sb) {
      try {
        var cr0 = await sb.from('news_feed').select('content').eq('id', cached.id).maybeSingle();
        cached.content = (cr0 && cr0.data && cr0.data.content) || '';
      } catch(e0) { cached.content = ''; }
    }
    var bodySnippet = cached ? (cached.body || cached.content || '').replace(/\s+/g,' ').trim().slice(0, 2000) : '';
    var userContent = '제목: ' + titleText +
      (cached ? '\n출처: ' + (cached.source||'') + '\n날짜: ' + (cached.published_at||'').slice(0,10) : '') +
      (bodySnippet ? '\n\n본문:\n' + bodySnippet : '');

    var res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'x-api-key': claudeKey, 'anthropic-version': '2023-06-01',
                 'content-type': 'application/json', 'anthropic-dangerous-direct-browser-access': 'true' },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001', max_tokens: 800,
        system: sysMsg,
        messages: [{ role: 'user', content: userContent }]
      })
    });
    if (!res.ok) throw new Error('API ' + res.status);
    var json = await res.json();
    var txt = json.content && json.content[0] ? json.content[0].text : '';
    var impactMatch = txt.match(/<impact>([\s\S]*?)<\/impact>/);
    var priorityMatch = txt.match(/<priority>([\s\S]*?)<\/priority>/);
    var impactText = impactMatch ? impactMatch[1].trim() : '';
    var priorityText = priorityMatch ? priorityMatch[1].trim() : '';
    var priorityColor = { '즉시대응': '#ef4444', '금주검토': '#f59e0b', '동향파악': '#22c55e' };
    var pColor = priorityColor[priorityText] || '#64748b';
    el.innerHTML = ''
      + (priorityText ? '<span style="font-size:10px;font-weight:700;color:#fff;background:' + pColor + ';padding:2px 8px;border-radius:4px;margin-bottom:7px;display:inline-block">' + priorityText + '</span>' : '')
      + (impactText ? '<div style="font-size:12px;color:var(--text-primary);line-height:1.7;margin-top:4px">' + impactText + '</div>' : '<div style="font-size:12px;color:var(--text-secondary)">분석 결과 없음</div>');
  } catch(e) {
    el.innerHTML = '<span style="font-size:11px;color:var(--text-secondary)">분석 실패: ' + e.message + '</span>';
  }
}

// 하위 호환용 (ID 기반) — 기존 호출부에서 사용
async function analyzeBriefingItem(elemId, titleText) {
  var el = document.getElementById(elemId);
  if (!el) { console.warn('[analyzeBriefingItem] elem not found:', elemId); return; }
  return analyzeBriefingItemEl(el, titleText);
}

async function loadBriefing() {
  const listEl = document.getElementById('briefing-list');
  if (!listEl) return;
  if (!sb) {
    listEl.innerHTML = '<div style="color:var(--text-secondary);padding:20px;text-align:center">Supabase 연결이 필요합니다.</div>';
    return;
  }
  listEl.innerHTML = '<div style="color:var(--text-secondary);padding:20px;text-align:center">불러오는 중...</div>';
  try {
    // 브리핑은 DB에서 삭제하지 않고 전량 보관 — 목록도 제한 없이 표시 (하루 1건이라 서버 상한 1000행 = 약 2.7년치)
    const { data, error } = await sb
      .from('daily_briefings')
      .select('*')
      .order('briefing_date', { ascending: false });
    if (error) throw error;
    if (!data || data.length === 0) {
      listEl.innerHTML = '<div style="color:var(--text-secondary);padding:40px;text-align:center">아직 브리핑이 없습니다.<br>매일 오전 8시에 자동으로 생성됩니다.</div>';
      return;
    }
    // 먼저 전체 파싱 결과를 수집 (elemId 보장)
    var allParsed = data.map(function(b, idx) {
      return parseBriefingContent(b.content, idx);
    });

    listEl.innerHTML = data.map(function(b, idx) {
      const d = new Date(b.briefing_date).toLocaleDateString('ko-KR', {year:'numeric', month:'2-digit', day:'2-digit'});
      const isToday = b.briefing_date === new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0,10);
      const parsed = allParsed[idx];
      const contentHtml = parsed.html;
      const urgentCount = parsed.urgentCount;
      const badgeHtml = isToday ? '<span style="background:var(--accent);color:#fff;font-size:10px;padding:2px 7px;border-radius:10px;margin-left:8px">오늘</span>' : '';
      const urgentBadge = urgentCount > 0
        ? '<span style="background:#ef4444;color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:10px;margin-left:6px">중요 ' + urgentCount + '건</span>'
        : '';
      const metaHtml = (b.news_count || b.terms_count)
        ? '<span style="color:var(--text-secondary);font-size:11px">뉴스 ' + (b.news_count||0) + '건 · 용어 ' + (b.terms_count||0) + '건</span>'
        : '';
      return '<div class="card" style="margin-bottom:12px;cursor:default">'
        + '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;cursor:pointer" onclick="toggleBriefing(\'bf-' + idx + '\')">'
        +   '<div style="display:flex;align-items:center;gap:4px;flex-wrap:wrap">'
        +     '<i class="ti ti-coffee" style="color:var(--accent)"></i>'
        +     '<span style="font-weight:600">' + d + '</span>' + badgeHtml + urgentBadge
        +   '</div>'
        +   '<div style="display:flex;align-items:center;gap:10px">'
        +     metaHtml
        +     '<i class="ti ti-chevron-' + (idx===0?'up':'down') + '" id="chevron-bf-' + idx + '" style="color:var(--text-secondary)"></i>'
        +   '</div>'
        + '</div>'
        + '<div id="bf-' + idx + '" style="display:' + (idx===0?'block':'none') + ';border-top:1px solid var(--border);padding-top:12px">'
        +   contentHtml
        + '</div>'
        + '</div>';
    }).join('');

    // 최신 브리핑(idx=0)의 긴급 항목 AI 분석 — innerHTML 직후 요소 직접 참조
    // (innerHTML 설정은 동기 완료이므로 바로 querySelectorAll 가능)
    var analysisTargets = [];
    // data-briefing-analysis 속성으로 분석 컨테이너를 정확히 식별
    var firstBriefingEl = listEl.querySelector('#bf-0');
    if (firstBriefingEl) {
      var urgentDivs = firstBriefingEl.querySelectorAll('[data-briefing-analysis]');
      console.log('[briefing] 긴급 분석 대상 (data attr):', urgentDivs.length, '개');
      urgentDivs.forEach(function(div) {
        var container = div.parentElement;
        var titleEl = container ? container.querySelector('[data-news-title]') : null;
        var titleText = titleEl ? titleEl.textContent.trim() : '';
        analysisTargets.push({ el: div, title: titleText });
      });
    }
    // data attr 방식 fallback: 모든 [id^="bi-"] 탐색
    if (analysisTargets.length === 0) {
      var allBiDivs = listEl.querySelectorAll('[id^="bi-"]');
      console.log('[briefing] fallback bi-* 탐색 결과:', allBiDivs.length, '개');
      allBiDivs.forEach(function(div) {
        var container = div.parentElement;
        var titleEl = container ? container.querySelector('[data-news-title]') : null;
        var titleText = titleEl ? titleEl.textContent.trim() : '';
        analysisTargets.push({ el: div, title: titleText });
      });
    }
    console.log('[briefing] 최종 분석 대상:', analysisTargets.length, '개');
    analysisTargets.forEach(function(item) {
      console.log('[briefing] 분석 시작:', item.el.id || '(no id)', '|', item.title.slice(0, 40));
      analyzeBriefingItemEl(item.el, item.title);
    });

  } catch(e) {
    listEl.innerHTML = '<div style="color:var(--text-secondary);padding:20px;text-align:center">브리핑 로드 실패: ' + e.message + '</div>';
    console.warn('Briefing load error:', e);
  }
}

function toggleBriefing(id) {
  var el = document.getElementById(id);
  var idx = id.replace('bf-','');
  var chevron = document.getElementById('chevron-' + id);
  if (!el) return;
  var isOpen = el.style.display !== 'none';
  el.style.display = isOpen ? 'none' : 'block';
  if (chevron) chevron.className = 'ti ti-chevron-' + (isOpen ? 'down' : 'up');
}

// ════════════════════════════════════════════
//  관리자 인증 (AI 페르소나 보호)
// ════════════════════════════════════════════
// 관리자 비밀번호는 평문 대신 SHA-256 해시로만 보관 (공개 소스에서 비번 노출 방지).
// 비밀번호 변경 시: 브라우저 콘솔에서 아래 한 줄을 실행해 새 해시를 만들고 이 값을 교체하세요.
//   crypto.subtle.digest('SHA-256', new TextEncoder().encode('새비밀번호')).then(b=>console.log([...new Uint8Array(b)].map(x=>x.toString(16).padStart(2,'0')).join('')))
const ADMIN_PWD_HASH = '164eab12762d42b09780eba6401d395a945355e42fc95a60b42ac509891cfa7e';
const ADMIN_MAX_ATTEMPTS = 5;          // 연속 실패 허용 횟수
const ADMIN_LOCKOUT_MS = 60 * 1000;    // 초과 시 입력 잠금 시간(60초)
var _adminPwd = '';                    // 잠금 해제 시 메모리에만 보관(소스/저장소에는 없음) — 승인·삭제 RPC 서버검증용

async function _sha256Hex(str) {
  var buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(str));
  return Array.from(new Uint8Array(buf)).map(function(b){ return b.toString(16).padStart(2, '0'); }).join('');
}

async function checkAdminPwd() {
  var inputEl = document.getElementById('admin-pwd-input');
  var errEl = document.getElementById('admin-pwd-error');
  var input = inputEl.value;
  var now = Date.now();

  // 잠금 상태면 차단하고 남은 시간 안내
  var lockUntil = parseInt(sessionStorage.getItem('admin_lock_until') || '0', 10);
  if (lockUntil > now) {
    var sec = Math.ceil((lockUntil - now) / 1000);
    if (errEl) { errEl.textContent = '시도 횟수를 초과했습니다. ' + sec + '초 후 다시 시도하세요.'; errEl.style.display = 'block'; }
    inputEl.value = '';
    return;
  }

  var hash = await _sha256Hex(input);
  if (hash === ADMIN_PWD_HASH) {
    sessionStorage.setItem('admin_auth', '1');
    _adminPwd = input;   // 승인·삭제 RPC 서버검증용 (메모리에만)
    sessionStorage.removeItem('admin_fail_count');
    sessionStorage.removeItem('admin_lock_until');
    document.getElementById('settings-locked').style.display = 'none';
    document.getElementById('settings-unlocked').style.display = 'block';
    document.getElementById('system-prompt-display').value = SYSTEM_PROMPT;
    loadSettingsFields();
    if (errEl) errEl.style.display = 'none';
    inputEl.value = '';
  } else {
    var fails = parseInt(sessionStorage.getItem('admin_fail_count') || '0', 10) + 1;
    inputEl.value = '';
    if (fails >= ADMIN_MAX_ATTEMPTS) {
      sessionStorage.setItem('admin_lock_until', String(now + ADMIN_LOCKOUT_MS));
      sessionStorage.setItem('admin_fail_count', '0');
      if (errEl) { errEl.textContent = ADMIN_MAX_ATTEMPTS + '회 연속 실패 — ' + (ADMIN_LOCKOUT_MS / 1000) + '초간 입력이 잠깁니다.'; errEl.style.display = 'block'; }
    } else {
      sessionStorage.setItem('admin_fail_count', String(fails));
      if (errEl) { errEl.textContent = '비밀번호가 올바르지 않습니다. (남은 시도 ' + (ADMIN_MAX_ATTEMPTS - fails) + '회)'; errEl.style.display = 'block'; }
    }
  }
}

function lockAdmin() {
  sessionStorage.removeItem('admin_auth');
  _adminPwd = '';
  document.getElementById('settings-locked').style.display = 'flex';
  document.getElementById('settings-unlocked').style.display = 'none';
  document.getElementById('admin-pwd-input').value = '';
}

// ════════════════════════════════════════════
//  Settings
// ════════════════════════════════════════════
function loadSettingsFields() {
  const cfg = getConfig();
  if (cfg.sbUrl) document.getElementById('inp-sb-url').value = cfg.sbUrl;
  if (cfg.sbKey) document.getElementById('inp-sb-key').value = cfg.sbKey;
  if (cfg.claudeKey) document.getElementById('inp-claude-key').value = cfg.claudeKey;
  loadPendingApprovals();
  loadLawWatch();
}

// ── 지식베이스 승인 대기 (업로드 파일 게이트) ──
var _pendingDocs = [];

async function loadPendingApprovals() {
  var listEl = document.getElementById('pending-approval-list');
  var badgeEl = document.getElementById('pending-count-badge');
  if (!listEl) return;
  if (!sb) {
    listEl.innerHTML = '<div style="padding:14px;text-align:center;color:var(--text-secondary);font-size:12px">Supabase 연결 후 표시됩니다.</div>';
    if (badgeEl) badgeEl.textContent = '';
    return;
  }
  listEl.innerHTML = '<div style="padding:14px;text-align:center;color:var(--text-secondary);font-size:12px">불러오는 중...</div>';
  try {
    var resp = await sb.rpc('list_kb_documents');
    if (resp.error) throw resp.error;
    _pendingDocs = (resp.data || []).filter(function(r){ return r.approved === false; });
    if (badgeEl) badgeEl.textContent = _pendingDocs.length ? _pendingDocs.length + '건' : '';
    if (_pendingDocs.length === 0) {
      listEl.innerHTML = '<div style="padding:14px;text-align:center;color:var(--text-secondary);font-size:12px">승인 대기 중인 문서가 없습니다.</div>';
      return;
    }
    listEl.innerHTML = _pendingDocs.map(function(r, i){
      return '<div class="file-item" style="margin-bottom:6px">'
        + '<div class="file-icon" style="background:rgba(245,158,11,.15);color:#b45309"><i class="ti ti-file-alert"></i></div>'
        + '<div style="flex:1;min-width:0"><div class="file-name">' + escHtml(r.doc_name) + '</div>'
        + '<div class="file-size">' + escHtml(r.doc_category || '') + ' · ' + r.chunks + '청크</div></div>'
        + '<button class="btn btn-primary" style="font-size:11px;padding:3px 10px" onclick="approveDoc(' + i + ')"><i class="ti ti-check"></i>승인</button>'
        + '<button class="btn" style="font-size:11px;padding:3px 10px;color:#791F1F;margin-left:6px" onclick="rejectDoc(' + i + ')"><i class="ti ti-trash"></i>삭제</button>'
        + '</div>';
    }).join('');
  } catch(e) {
    listEl.innerHTML = '<div style="padding:14px;color:var(--text-secondary);font-size:12px">목록 조회 실패: ' + escHtml(e.message || String(e)) + '</div>';
  }
}

// ── 법령 현행화 상태 (law_watch) ──
// 감시(law_watch.py)는 GitHub Actions가 매일 돌리고, 여기서는 결과만 읽어 보여준다.
// 실제 현행화는 PC에서 law_sync.py 실행(조문 취득·임베딩이 무거워 브라우저에서 수행하지 않음).
async function loadLawWatch() {
  var listEl = document.getElementById('lawwatch-list');
  var badgeEl = document.getElementById('lawwatch-count-badge');
  if (!listEl) return;
  if (!sb) {
    listEl.innerHTML = '<div style="padding:14px;text-align:center;color:var(--text-secondary);font-size:12px">Supabase 연결 후 표시됩니다.</div>';
    return;
  }
  listEl.innerHTML = '<div style="padding:14px;text-align:center;color:var(--text-secondary);font-size:12px">불러오는 중...</div>';
  try {
    // law_watch = 현행 등재본 감시. 시행예정은 법령당 여러 건일 수 있어 law_pending(1:N)이 정본.
    var res = await Promise.all([
      sb.from('law_watch')
        .select('doc_name,law_name,registered_law_no,registered_enf,latest_law_no,latest_enf,sync_status,watch_status,last_checked_at')
        .neq('watch_status', 'excluded').order('law_name'),
      sb.from('law_pending')
        .select('law_name,law_no,enf_date,sync_state')
        .in('sync_state', ['detected', 'loaded']).order('enf_date')
    ]);
    var r = res[0];
    if (r.error) throw r.error;
    var rows = r.data || [];
    var pend = (res[1] && !res[1].error) ? (res[1].data || []) : [];
    var outdated = rows.filter(function(x){ return x.sync_status === 'outdated'; });
    var unmatched = rows.filter(function(x){ return x.watch_status === 'unmatched'; });
    // 법령별로 묶어 다단 시행을 한 줄에 보여준다
    var byLaw = {};
    pend.forEach(function(p){ (byLaw[p.law_name] = byLaw[p.law_name] || []).push(p); });
    var upcoming = Object.keys(byLaw).sort(function(a, b){
      return byLaw[a][0].enf_date.localeCompare(byLaw[b][0].enf_date);
    }).map(function(k){ return { law_name: k, steps: byLaw[k] }; });
    if (badgeEl) badgeEl.textContent = outdated.length ? outdated.length + '건 개정' : '';

    var last = rows.reduce(function(m, x){ return (x.last_checked_at || '') > m ? x.last_checked_at : m; }, '');
    var html = '<div style="font-size:11px;color:var(--text-tertiary);margin-bottom:8px">'
      + '감시 ' + rows.length + '건 · 최신 ' + (rows.length - outdated.length - unmatched.length) + '건'
      + (last ? ' · 최근 점검 ' + new Date(last).toLocaleString('ko-KR', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '')
      + '</div>';

    function fmtNo(v) { v = v || ''; return /^제/.test(v) ? v : (v ? '제' + v + '호' : '-'); }
    function fmtDate(v) { return v && v.length === 8 ? v.slice(2,4)+'.'+v.slice(4,6)+'.'+v.slice(6,8) : (v || ''); }

    if (outdated.length) {
      html += '<div style="font-size:11.5px;font-weight:600;color:#b45309;margin:8px 0 6px">🔄 개정 감지 — 현행화 필요</div>';
      html += outdated.map(function(x){
        return '<div class="file-item" style="margin-bottom:6px">'
          + '<div class="file-icon" style="background:rgba(245,158,11,.15);color:#b45309"><i class="ti ti-alert-triangle"></i></div>'
          + '<div style="flex:1;min-width:0"><div class="file-name">' + escHtml(x.law_name || x.doc_name) + '</div>'
          + '<div class="file-size">등재 ' + escHtml(fmtNo(x.registered_law_no)) + '(' + fmtDate(x.registered_enf) + ')'
          + ' → <strong style="color:#b45309">' + escHtml(fmtNo(x.latest_law_no)) + '</strong>(' + fmtDate(x.latest_enf) + ' 시행)</div></div>'
          + '</div>';
      }).join('');
    }
    if (upcoming.length) {
      html += '<div style="font-size:11.5px;font-weight:600;color:var(--text-secondary);margin:12px 0 6px">📅 시행 예정 ('
        + pend.length + '건 / 법령 ' + upcoming.length + '건)</div>';
      html += upcoming.map(function(x){
        var steps = x.steps.map(function(s){
          var loaded = s.sync_state === 'loaded';
          return '<span title="' + (loaded ? '조문 등재 완료(pending)' : '미적재 — law_sync.py --pending 필요') + '" style="'
            + (loaded ? '' : 'opacity:.6;') + '"><strong>' + fmtDate(s.enf_date) + '</strong> '
            + escHtml(fmtNo(s.law_no)) + (loaded ? '' : ' <i class="ti ti-download-off"></i>') + '</span>';
        }).join(' <span style="color:var(--text-tertiary)">›</span> ');
        return '<div style="font-size:11.5px;color:var(--text-secondary);padding:3px 0 3px 4px">· '
          + escHtml(x.law_name) + (x.steps.length > 1 ? ' <span style="color:#b45309">' + x.steps.length + '단계</span>' : '')
          + '<div style="padding-left:10px;font-size:11px;color:var(--text-tertiary)">' + steps + '</div></div>';
      }).join('');
    }
    if (unmatched.length) {
      html += '<div style="font-size:11.5px;font-weight:600;color:var(--text-secondary);margin:12px 0 6px">❓ 미매칭 — 수동 확인 (' + unmatched.length + '건)</div>';
      html += unmatched.map(function(x){
        return '<div style="font-size:11px;color:var(--text-tertiary);padding:2px 0 2px 4px">· ' + escHtml((x.law_name || x.doc_name).slice(0, 60)) + '</div>';
      }).join('');
    }
    if (!outdated.length && !upcoming.length && !unmatched.length) {
      html += '<div style="padding:12px;text-align:center;color:var(--text-secondary);font-size:12px">✅ 모든 법령이 현행 상태입니다.</div>';
    }
    listEl.innerHTML = html;
  } catch(e) {
    listEl.innerHTML = '<div style="padding:14px;color:var(--text-secondary);font-size:12px">조회 실패: ' + escHtml(e.message || String(e)) + '</div>';
  }
}

// 잠금 해제 후 새로고침 등으로 메모리 비번이 비면 다시 입력받음
function _ensureAdminPwd() {
  if (_adminPwd) return _adminPwd;
  var p = prompt('보안 확인을 위해 관리자 비밀번호를 다시 입력하세요:');
  if (p) _adminPwd = p;
  return _adminPwd;
}

function _handleAdminRpcError(err, action) {
  if (err && /AUTH_FAILED/.test(err.message || '')) {
    _adminPwd = '';
    alert('비밀번호 인증에 실패했습니다. 다시 시도해주세요.');
  } else {
    alert(action + ' 실패: ' + (err && err.message ? err.message : err));
  }
}

async function approveDoc(idx) {
  var doc = _pendingDocs[idx];
  if (!doc || !sb) return;
  var pwd = _ensureAdminPwd();
  if (!pwd) return;
  // RLS로 직접 UPDATE가 막히므로 서버 검증 RPC로 처리
  var res = await sb.rpc('admin_set_kb_approval', { p_doc_name: doc.doc_name, p_approved: true, p_pwd: pwd });
  if (res.error) { _handleAdminRpcError(res.error, '승인'); return; }
  _kbDocsLoaded = false;   // KB 목록 재조회 유도
  await loadPendingApprovals();
  var msgs = [];
  // 승인 직후 임베딩 자동 생성 — 실패해도 승인은 유지되고 '임베딩 대기'로 남음(PC 백필 가능)
  try {
    var n = await embedDocChunks(doc.doc_name, pwd);
    if (n > 0) msgs.push('의미검색 임베딩 ' + n + '건 자동 생성');
  } catch(e) {
    console.warn('자동 임베딩 실패(임베딩 대기 유지 — PC에서 backfill_embeddings.py로 보완):', e);
    msgs.push('⚠️ 임베딩 자동 생성 실패 — "임베딩 대기"로 남음 (PC 백필로 보완 가능)');
  }
  // 법령·고시는 OKF 요약(kb_documents)까지 자동 생성 — 실패해도 승인·임베딩은 유지 (add_law.py로 보완 가능)
  if (doc.doc_category === '법령' || doc.doc_category === '고시') {
    try {
      var okf = await generateOkfForDoc(doc.doc_name, doc.doc_category, pwd);
      msgs.push('OKF 요약 자동 생성: ' + okf.chunks + '청크 (' + okf.path + ')');
      msgs.push('※ Haiku 초안 — 번들 파일은 PC에서 sync_kb_to_bundle.py 실행 시 저장됨');
    } catch(e) {
      console.warn('OKF 자동 생성 실패(자문은 조문 기반으로 정상 동작 — PC add_law.py로 보완 가능):', e);
      msgs.push('⚠️ OKF 요약 생성 실패(' + (e && e.message ? e.message : e) + ') — PC add_law.py로 보완 가능');
    }
  }
  alert('승인 완료' + (msgs.length ? '\n- ' + msgs.join('\n- ') : ''));
  _kbDocsLoaded = false;
}

// ── OKF 요약 자동 생성 (승인 훅) — add_law.py ②단계의 브라우저판 ──
// Haiku가 요약 초안 작성 → 마크다운 청킹 → voyage-law-2 임베딩(Edge Function) → admin RPC로 kb_* 적재.
// 번들(regulatory-kb) 파일은 브라우저가 못 쓰므로 DB에만 존재 — PC의 sync_kb_to_bundle.py가 역동기화.

function _okfNormTitle(t) { return (t || '').replace(/\s*\((구버전|현행)\)\s*/g, '').trim(); }

function _okfSlug(title) {
  var base = _okfNormTitle(title).replace(/[^0-9a-zA-Z가-힣]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase();
  return (base.slice(0, 60) || 'law');
}

// 파일명 관례 "제목(법률)(제21065호)(20260102)" 에서 메타 추출 (없으면 빈 값 → Haiku frontmatter로 보완)
function _okfMetaFromDocName(docName) {
  var name = (docName || '').replace(/\.(pdf|docx|md|pptx)$/i, '');
  var m = name.match(/^(.*?)\(([^()]*(?:법률|대통령령|총리령|부령|고시|훈령|예규|공고|규칙|규정)[^()]*)\)\s*\((제[^()]*호)\)\s*\((\d{8})\)/);
  if (!m) return { title: name.replace(/\([^()]*\)/g, '').trim() || name, law_type: '', law_number: '', enf: '' };
  return { title: m[1].trim(), law_type: m[2].trim(), law_number: m[3].trim(),
           enf: m[4].slice(0, 4) + '-' + m[4].slice(4, 6) + '-' + m[4].slice(6, 8) };
}

// --- ... --- frontmatter 분리 (import_regulatory_kb.split_frontmatter의 JS판 — 키:값 스칼라만)
function _okfSplitFrontmatter(text) {
  var fm = {}, body = text;
  if (text.slice(0, 3) === '---') {
    var end = text.indexOf('\n---', 3);
    if (end !== -1) {
      var block = text.slice(3, end);
      body = text.slice(end + 4).replace(/^\n+/, '');
      block.split('\n').forEach(function(line) {
        if (line.indexOf(':') !== -1 && !/^\s*-/.test(line)) {
          var idx = line.indexOf(':');
          fm[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
        }
      });
    }
  }
  return { fm: fm, body: body };
}

// 마크다운 헤더 경계 우선 청킹 (import_regulatory_kb.chunk_body와 동일 규칙: 1000자/오버랩100/최소30/제목 접두)
function _okfChunkBody(body, title) {
  var SIZE = 1000, OVERLAP = 100;
  var parts = body.split(/(?=^#{1,3}\s)/m);
  var raw = [];
  parts.forEach(function(p) {
    p = p.trim();
    if (!p) return;
    if (p.length <= SIZE) { raw.push(p); return; }
    var start = 0;
    while (start < p.length) {
      raw.push(p.slice(start, start + SIZE));
      start += SIZE - OVERLAP;
    }
  });
  return raw.filter(function(c) { return c.trim().length >= 30; })
            .map(function(c) { return '[' + title + '] ' + c; });
}

async function generateOkfForDoc(docName, category, pwd) {
  var cfg = getConfig();
  if (!cfg.claudeKey) throw new Error('Claude API 키 미설정');
  // 1) 조문 청크에서 원문 발췌 (add_law.py와 동일하게 앞부분 최대 18000자)
  var resp = await sb.from('document_chunks')
    .select('chunk_index, content').eq('doc_name', docName)
    .order('chunk_index').limit(60);
  if (resp.error) throw new Error(resp.error.message);
  var lawText = (resp.data || []).map(function(r) { return r.content; }).join('\n').slice(0, 18000);
  if (lawText.length < 200) throw new Error('원문 텍스트 부족');

  var meta = _okfMetaFromDocName(docName);
  var conceptType = (category === '법령') ? 'Law' : 'Notice';
  // 2) Haiku 요약 초안 (add_law.py anthropic_summarize와 동일 프롬프트)
  var sysPrompt = '너는 대한민국 전파·통신 규제 전문가다. 주어진 법령/고시 원문을 바탕으로 ' +
    'OKF 지식베이스용 마크다운 문서를 작성한다. 반드시 아래 형식만 출력(설명 문장 금지):\n' +
    '--- 로 감싼 YAML frontmatter: type, title, description(한 문장), tags(목록), ' +
    'law_type, law_number, enforcement_date, competent_authority, status: current\n' +
    "그 다음 본문 섹션: '# 요약' '# 적용 범위' '# 주요 내용(구조화)' '# 실무 체크리스트' '# Citations'.\n" +
    '요약은 실무자가 이해하기 쉽게, 조문 번호는 본문에 인용하되 과장 없이 사실만.';
  var userMsg = '[메타] title=' + meta.title + ' / law_type=' + meta.law_type +
    ' / law_number=' + meta.law_number + ' / enforcement_date=' + meta.enf +
    ' / concept_type=' + conceptType + ' / competent_authority=\n\n[원문 발췌]\n' + lawText;
  var res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: { 'x-api-key': cfg.claudeKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json', 'anthropic-dangerous-direct-browser-access': 'true' },
    body: JSON.stringify({ model: 'claude-haiku-4-5-20251001', max_tokens: 4096, system: sysPrompt,
      messages: [{ role: 'user', content: userMsg }] })
  });
  var data = await res.json();
  if (!res.ok) throw new Error('Claude API 오류: ' + ((data.error && data.error.message) || res.status));
  var md = (data.content || []).filter(function(b) { return b.type === 'text'; })
    .map(function(b) { return b.text; }).join('').trim();
  md = md.replace(/^```(?:markdown|md)?\s*\n/, '').replace(/\n```\s*$/, '');
  if (md.length < 200) throw new Error('요약 결과가 비정상적으로 짧음');

  var sf = _okfSplitFrontmatter(md);
  var title = meta.title || sf.fm.title || docName;
  var lawType = meta.law_type || sf.fm.law_type || '';
  var lawNumber = meta.law_number || sf.fm.law_number || '';
  var enfDate = meta.enf || sf.fm.enforcement_date || '';
  // 3) 요약 본문 청킹 + voyage-law-2 임베딩 (kb_chunks 저장 모델과 동일 — Edge Function 경유)
  var chunks = _okfChunkBody(sf.body, title);
  if (!chunks.length) throw new Error('요약 청킹 결과 없음');
  var embeddings = [];
  for (var i = 0; i < chunks.length; i += 5) {
    var batch = chunks.slice(i, i + 5);
    var embs = await Promise.all(batch.map(function(c) {
      return sb.functions.invoke('voyage-embed', {
        body: { query: c, model: 'voyage-law-2', input_type: 'document' }
      }).then(function(r2) {
        if (r2.error || !r2.data || !r2.data.embedding) throw new Error('voyage-embed 실패');
        return r2.data.embedding;
      });
    }));
    embs.forEach(function(e) { embeddings.push(e); });
  }
  // 4) admin RPC로 kb_documents/kb_chunks 적재 (동일 path 덮어쓰기 + 구버전 supersede는 RPC가 처리)
  var path = 'laws/web-upload/' + _okfSlug(title) + '.md';
  var r1 = await sb.rpc('admin_upsert_kb_document', {
    p_pwd: pwd, p_dedup_key: _okfNormTitle(title) + '|' + lawType, p_title: title,
    p_concept_type: conceptType, p_family: 'web-upload', p_law_type: lawType,
    p_law_number: lawNumber, p_enforcement_date: enfDate,
    p_competent_authority: sf.fm.competent_authority || '', p_path: path,
    p_description: sf.fm.description || '', p_body_md: sf.body
  });
  if (r1.error) { if (/AUTH_FAILED/.test(r1.error.message || '')) _adminPwd = ''; throw new Error(r1.error.message); }
  var vecs = embeddings.map(function(e) { return '[' + e.join(',') + ']'; });
  var r2b = await sb.rpc('admin_insert_kb_chunks', { p_pwd: pwd, p_doc_id: r1.data, p_contents: chunks, p_embeddings: vecs });
  if (r2b.error) throw new Error(r2b.error.message);
  return { title: title, chunks: chunks.length, path: path };
}

// 승인된 문서의 embedding NULL 청크를 Edge Function(voyage-embed)으로 채움 (배경역사 #23)
async function embedDocChunks(docName, pwd) {
  var resp = await sb.from('document_chunks')
    .select('id, content')
    .eq('doc_name', docName)
    .is('embedding', null)
    .order('id');
  var rows = resp.data || [];
  if (!rows.length) return 0;
  var embeddings = [];
  // Edge Function은 텍스트 1건씩 처리 — 동시 5건으로 순차 배치 (문서 저장용 input_type=document)
  for (var i = 0; i < rows.length; i += 5) {
    var batch = rows.slice(i, i + 5);
    var embs = await Promise.all(batch.map(function(r) {
      return sb.functions.invoke('voyage-embed', {
        body: { query: r.content, model: 'voyage-4-lite', input_type: 'document' }
      }).then(function(res2) {
        if (res2.error || !res2.data || !res2.data.embedding) throw new Error('voyage-embed 실패');
        return res2.data.embedding;
      });
    }));
    embs.forEach(function(e) { embeddings.push(e); });
  }
  // 50건씩 서버 검증 RPC로 저장 (anon 직접 UPDATE는 RLS로 차단되어 있음)
  for (var j = 0; j < rows.length; j += 50) {
    var ids  = rows.slice(j, j + 50).map(function(r) { return r.id; });
    var vecs = embeddings.slice(j, j + 50).map(function(e) { return '[' + e.join(',') + ']'; });
    var r2 = await sb.rpc('admin_update_chunk_embeddings', { p_ids: ids, p_embeddings: vecs, p_pwd: pwd });
    if (r2.error) throw new Error(r2.error.message);
  }
  return rows.length;
}

async function rejectDoc(idx) {
  var doc = _pendingDocs[idx];
  if (!doc || !sb) return;
  if (!confirm('"' + doc.doc_name + '" 문서를 삭제할까요?\n청크가 모두 제거되며 되돌릴 수 없습니다.')) return;
  var pwd = _ensureAdminPwd();
  if (!pwd) return;
  // 원본 파일(Storage uploads) 정리 (best-effort)
  try {
    var fp = await sb.from('document_chunks').select('file_path').eq('doc_name', doc.doc_name).not('file_path', 'is', null).limit(1);
    if (fp.data && fp.data[0] && fp.data[0].file_path) {
      await sb.storage.from('uploads').remove([fp.data[0].file_path]);
    }
  } catch(se) { console.warn('원본 파일 삭제 실패:', se); }
  // RLS로 직접 DELETE가 막히므로 서버 검증 RPC로 처리
  var res = await sb.rpc('admin_delete_kb_document', { p_doc_name: doc.doc_name, p_pwd: pwd });
  if (res.error) { _handleAdminRpcError(res.error, '삭제'); return; }
  _kbDocsLoaded = false;
  await loadPendingApprovals();
}

function loadSettingsUI() {
  // 이미 인증된 경우 잠금 해제 상태 유지, 아니면 잠금 화면 표시
  var isAuth = sessionStorage.getItem('admin_auth') === '1';
  document.getElementById('settings-locked').style.display   = isAuth ? 'none'  : 'flex';
  document.getElementById('settings-unlocked').style.display = isAuth ? 'block' : 'none';
  if (isAuth) loadSettingsFields();
}

async function saveApiKeys() {
  const sbUrl = document.getElementById('inp-sb-url').value.trim();
  const sbKey = document.getElementById('inp-sb-key').value.trim();
  const claudeKey = document.getElementById('inp-claude-key').value.trim();
  if (!sbUrl || !sbKey || !claudeKey) {
    showApiAlert('warn', 'Supabase URL, Supabase Key, Claude API Key는 필수입니다.');
    return;
  }
  saveConfig({ sbUrl: sbUrl, sbKey: sbKey, claudeKey: claudeKey });
  _remoteClaudeKey = claudeKey;
  sb = null;
  initSupabase();
  updateStatusDots();
  // Supabase app_config에도 Claude 키 저장 (다른 사용자도 자동 사용)
  try {
    await sb.from('app_config').upsert({ key: 'claude_key', value: claudeKey });
    showApiAlert('ok', '저장 완료 — 모든 사용자에게 AI 자문이 활성화됩니다.');
  } catch(e) {
    showApiAlert('ok', '로컬 저장 완료 (Supabase 동기화는 실패했습니다).');
  }
}

async function testConnection() {
  const cfg = getConfig();
  const results = [];
  if (sb) {
    try {
      const { error } = await sb.from('chat_logs').select('id').limit(1);
      results.push(error ? 'Supabase X (' + error.message + ')' : 'Supabase 연결 성공');
    } catch(e) { results.push('Supabase X (' + e.message + ')'); }
  } else {
    results.push('Supabase URL/Key 미설정');
  }
  if (cfg.claudeKey) {
    try {
      const res = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: {
          'x-api-key': cfg.claudeKey,
          'anthropic-version': '2023-06-01',
          'content-type': 'application/json',
          'anthropic-dangerous-direct-browser-access': 'true'
        },
        body: JSON.stringify({ model: 'claude-sonnet-5', max_tokens: 10, messages: [{ role: 'user', content: 'ping' }] })
      });
      results.push(res.ok ? 'Claude API 연결 성공' : 'Claude API X (HTTP ' + res.status + ')');
    } catch(e) { results.push('Claude API X (' + e.message + ')'); }
  } else {
    results.push('Claude API Key 미설정');
  }

  const ok = results.every(function(r) { return r.includes('성공') || r.includes('미설정'); });
  showApiAlert(ok ? 'ok' : 'warn', results.join(' · '));
  updateStatusDots();
}

function clearApiKeys() {
  if (!confirm('저장된 API 키를 모두 삭제할까요?')) return;
  localStorage.removeItem(CFG_KEY);
  document.getElementById('inp-sb-url').value = '';
  document.getElementById('inp-sb-key').value = '';
  document.getElementById('inp-claude-key').value = '';
  sb = null;
  updateStatusDots();
  showApiAlert('ok', 'API 키가 삭제되었습니다.');
}

function showApiAlert(type, msg) {
  const el = document.getElementById('api-alert');
  if (!el) return;
  el.innerHTML = '<div style="padding:8px 12px;border-radius:6px;font-size:12px;margin-bottom:10px;background:' +
    (type === 'ok' ? '#d1fae5;color:#065f46' : '#fef3c7;color:#92400e') + '">' + msg + '</div>';
}

function updateStatusDots() {
  const cfg = getConfig();
  const sbOk = !!sb;
  const aiOk = !!cfg.claudeKey;
  const ragOk = sbOk;

  const sbDot = document.getElementById('sb-dot');
  const aiDot = document.getElementById('ai-dot');
  const ragDot = document.getElementById('rag-dot');
  const sbStatus = document.getElementById('sb-status');
  const aiStatus = document.getElementById('ai-status');
  const ragStatus = document.getElementById('rag-status');

  if (sbDot) sbDot.style.background = sbOk ? 'var(--green)' : '#d1d5db';
  if (aiDot) aiDot.style.background = aiOk ? 'var(--green)' : '#d1d5db';
  if (ragDot) ragDot.style.background = ragOk ? 'var(--green)' : '#d1d5db';
  if (sbStatus) sbStatus.textContent = sbOk ? 'Supabase 연결됨' : 'Supabase 미연결';
  if (aiStatus) aiStatus.textContent = aiOk ? 'Claude API 설정됨' : 'Claude API 미설정';
  if (ragStatus) ragStatus.textContent = ragOk ? 'RAG 활성 (하이브리드 검색)' : 'RAG 하이브리드 검색';
}

// ════════════════════════════════════════════
//  Navigation
// ════════════════════════════════════════════
// ── 운영 상태 (설정 밑 탭) ───────────────────────────────
function opsAgoText(iso) {
  if (!iso) return '기록 없음';
  var mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return '방금 전';
  if (mins < 60) return mins + '분 전';
  var hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + '시간 ' + (mins % 60) + '분 전';
  return Math.floor(hrs / 24) + '일 ' + (hrs % 24) + '시간 전';
}

function opsRow(label, value, ok, hint) {
  var color = ok === true ? '#16a34a' : (ok === false ? '#dc2626' : '#9ca3af');
  var icon  = ok === true ? '✅' : (ok === false ? '⚠️' : '•');
  return '<div style="display:flex;align-items:center;gap:10px;padding:10px 4px;border-bottom:1px solid #f0f0f0">' +
           '<span style="font-size:15px">' + icon + '</span>' +
           '<div style="flex:1"><div style="font-weight:600;font-size:13px">' + label + '</div>' +
           (hint ? '<div style="font-size:11px;color:#9ca3af">' + hint + '</div>' : '') +
           '</div><div style="font-size:12px;color:' + color + ';font-weight:600;text-align:right">' + value + '</div></div>';
}

async function loadOpsStatus() {
  var el = document.getElementById('ops-status-body');
  if (!el) return;
  if (!sb) { el.innerHTML = '<p style="color:#9ca3af">Supabase 연결 대기 중…</p>'; return; }
  el.innerHTML = '<p style="color:#9ca3af">불러오는 중…</p>';
  try {
    var kstNow = new Date(Date.now() + 9 * 3600000);
    var todayKst = kstNow.toISOString().slice(0, 10);
    var kstHour = kstNow.getUTCHours();

    var r = await Promise.all([
      sb.from('news_feed').select('created_at').order('created_at', { ascending: false }).limit(1),
      sb.from('system_health').select('key,updated_at,note'),
      sb.from('daily_briefings').select('briefing_date,created_at').order('created_at', { ascending: false }).limit(1),
      sb.from('law_amendments').select('created_at').eq('law_type', 'lsAnc').order('created_at', { ascending: false }).limit(1),
      sb.from('assembly_bills').select('created_at').order('created_at', { ascending: false }).limit(1),
      sb.from('news_feed').select('*', { count: 'exact', head: true })
    ]);

    function first(x) { return (x && x.data && x.data[0]) ? x.data[0] : null; }
    var hb = {};
    (r[1].data || []).forEach(function(row){ hb[row.key] = row; });
    function hbTime(k){ return hb[k] ? hb[k].updated_at : null; }
    function hbNote(k){ return hb[k] ? (hb[k].note || '') : ''; }
    var lastNews    = first(r[0]) ? first(r[0]).created_at : null;
    var lastCrawl   = hbTime('last_crawl_run');
    var lastGov     = hbTime('last_gov_notice_run');
    var lastRefetch = hbTime('last_refetch_run');
    var crawlNote   = hbNote('last_crawl_run');
    var briefRow  = first(r[2]);
    var lastLaw   = first(r[3]) ? first(r[3]).created_at : null;
    var lastBill  = first(r[4]) ? first(r[4]).created_at : null;
    var newsCount = (typeof r[5].count === 'number') ? r[5].count : null;

    function hoursAgo(iso) { return iso ? (Date.now() - new Date(iso).getTime()) / 3600000 : Infinity; }
    var crawlerOk = hoursAgo(lastCrawl) < 1.5;
    var govOk = hoursAgo(lastGov) < 25;   // 매일 17:00 → 25h 내면 정상
    var newsH = hoursAgo(lastNews);
    var briefOk = !!(briefRow && briefRow.briefing_date === todayKst);

    var rows = '';
    rows += opsRow('크롤러 실행 (heartbeat)', opsAgoText(lastCrawl),
                   lastCrawl ? crawlerOk : null,
                   crawlNote ? ('최근 결과: ' + crawlNote) : '매시간 자동 실행');
    rows += opsRow('뉴스 마지막 입력', opsAgoText(lastNews),
                   crawlerOk ? true : (newsH < 14 ? true : false),
                   crawlerOk ? '크롤러 정상 — 새 기사 없으면 간격이 벌어져도 정상' : '크롤러 점검 필요할 수 있음');
    rows += opsRow('오늘 모닝 브리핑',
                   briefOk ? ('생성됨 (' + briefRow.briefing_date + ')') : '미생성',
                   briefOk ? true : (kstHour < 9 ? null : false),
                   '매일 06:00 KST');
    rows += opsRow('입법예고·정부고시 크롤러 (heartbeat)', opsAgoText(lastGov),
                   lastGov ? govOk : null,
                   lastGov ? '매일 17:00 PC 실행 — 새 예고 없어도 정상' : 'PC 17:00 스케줄러 (heartbeat 대기)');
    rows += opsRow('└ 입법예고 최근 새 항목', opsAgoText(lastLaw), null, '매칭되는 새 입법예고가 드물어 간격 큼(정상)');
    rows += opsRow('본문 수집 (refetch, heartbeat)', opsAgoText(lastRefetch), null,
                   lastRefetch ? ('최근 결과: ' + hbNote('last_refetch_run')) : 'PC 본문 수집 (heartbeat 대기)');
    rows += opsRow('국회 법안 최근 갱신', opsAgoText(lastBill), null, '매일 10:00');
    rows += opsRow('뉴스 보관 건수', (newsCount != null ? newsCount + '건' : '—'), null, '60일 유지');

    el.innerHTML =
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">' +
        '<button class="btn" style="font-size:11px;padding:3px 10px" onclick="loadOpsStatus()"><i class="ti ti-refresh"></i> 새로고침</button>' +
        '<span style="font-size:11px;color:#9ca3af;margin-left:auto">' + new Date().toLocaleString('ko-KR') + ' 기준</span>' +
      '</div>' +
      '<div style="background:#fff;border:1px solid #eee;border-radius:8px;padding:4px 14px">' + rows + '</div>' +
      '<div id="ops-kb-quality" style="background:#fff;border:1px solid #eee;border-radius:8px;padding:12px 14px;margin-top:12px">' +
        '<div style="font-weight:700;font-size:13px;margin-bottom:6px">📚 KB 품질</div>' +
        '<p style="color:#9ca3af;font-size:12px;margin:0">불러오는 중…</p>' +
      '</div>' +
      '<p style="font-size:11px;color:#9ca3af;margin-top:10px">※ ✅ 정상 · ⚠️ 점검 권장. "뉴스 마지막 입력"은 새 기사가 없으면 자연히 벌어집니다(크롤러가 정상이면 문제 아님).</p>';
    loadKbQualityCard();   // 별도 비동기 — 하트비트 표시를 늦추지 않음
  } catch (e) {
    el.innerHTML = '<p style="color:#dc2626">불러오기 실패: ' + (e && e.message ? e.message : e) + '</p>';
  }
}

// ── KB 품질 카드 (개선⑫) — 뷰 kb_quality_low_docs·kb_quality_article_parse + 임베딩 누락 count
//    실패해도 이 카드에만 "조회 실패"를 표기하고 운영 상태 패널 전체는 살린다.
async function loadKbQualityCard() {
  var card = document.getElementById('ops-kb-quality');
  if (!card || !sb) return;
  var head = '<div style="font-weight:700;font-size:13px;margin-bottom:6px">📚 KB 품질</div>';
  try {
    var r = await Promise.all([
      sb.from('kb_quality_low_docs').select('doc_name,doc_category,chars,chunks'),
      sb.from('kb_quality_article_parse').select('doc_name,total_chunks,parsed_chunks,parse_pct'),
      sb.from('document_chunks').select('id', { count: 'exact', head: true }).is('embedding', null).eq('status', 'current')
    ]);
    if (r[0].error || r[1].error || r[2].error) throw (r[0].error || r[1].error || r[2].error);
    var lowRows = r[0].data || [];
    var parseRows = r[1].data || [];
    var embMissing = (typeof r[2].count === 'number') ? r[2].count : null;

    var lowBad = lowRows.filter(function(d) { return (d.chars || 0) < 2000; });
    var parseBad = parseRows.filter(function(d) { return (d.parse_pct == null ? 0 : d.parse_pct) < 90; });
    // 뷰가 하위 15행 상한이라 상한 도달 시 실제 건수는 더 많을 수 있음 → '+' 표기
    var lowN = lowBad.length + (lowBad.length >= 15 ? '+' : '');
    var parseN = parseBad.length + (parseBad.length >= 15 ? '+' : '');

    function kbLine(name, right, danger) {
      return '<div style="display:flex;gap:8px;justify-content:space-between;padding:4px 0;border-bottom:1px solid #f5f5f5;font-size:12px">' +
             '<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#374151">' + escHtml(name) + '</span>' +
             '<span style="white-space:nowrap;font-weight:600;color:' + (danger ? '#dc2626' : '#6b7280') + '">' + right + '</span></div>';
    }

    var html = head;
    html += '<div style="font-size:12px;color:#374151;margin-bottom:10px">본문 부실(2천자 미만) <b>' + lowN + '건</b> · 조문 인식 90% 미만 <b>' + parseN + '건</b> · 임베딩 누락 <b>' + (embMissing != null ? embMissing : '—') + '건</b></div>';

    html += '<div style="font-weight:600;font-size:12px;color:#6b7280;margin:8px 0 2px">📉 본문 부실 하위</div>';
    if (!lowRows.length) html += '<div style="font-size:12px;color:#9ca3af;padding:4px 0">해당 없음</div>';
    lowRows.slice(0, 8).forEach(function(d) {
      var chars = d.chars || 0;
      html += kbLine(d.doc_name + (d.doc_category ? ' (' + d.doc_category + ')' : ''),
                     chars.toLocaleString('ko-KR') + '자 · ' + (d.chunks || 0) + '청크', chars < 500);
    });

    html += '<div style="font-weight:600;font-size:12px;color:#6b7280;margin:10px 0 2px">📑 조문 인식률 하위 (법령류)</div>';
    if (!parseRows.length) html += '<div style="font-size:12px;color:#9ca3af;padding:4px 0">해당 없음</div>';
    parseRows.slice(0, 8).forEach(function(d) {
      var pct = Math.round(d.parse_pct == null ? 0 : d.parse_pct);
      html += kbLine(d.doc_name, pct + '% (' + (d.parsed_chunks || 0) + '/' + (d.total_chunks || 0) + ')', pct < 50);
    });

    html += '<p style="font-size:11px;color:#9ca3af;margin:8px 0 0">※ 빨간 항목 = 본문 500자 미만 / 조문 인식 50% 미만 — 원문 재수집·재분할 권장.</p>';
    card.innerHTML = html;
  } catch (e) {
    card.innerHTML = head + '<p style="color:#dc2626;font-size:12px;margin:0">조회 실패' + (e && e.message ? ' — ' + escHtml(e.message) : '') + '</p>';
  }
}

// ── 메뉴 개편(2026-08-03): 페이지 → 좌측 네비 data-nav 매핑. 탭·모바일에서 navEl 없이
//    go()가 호출돼도 좌측 네비 활성 표시가 새 계층에 맞게 동기화되도록 한다.
var PAGE_TO_NAV = {
  news: 'monitor', overseas: 'monitor',
  briefing: 'briefing', terms: 'terms',
  chat: 'chat', reportdraft: 'chat', lawmap: 'lawmap',
  assembly: 'assembly', minutes: 'minutes',
  lawtrack: 'lawrev', diff: 'lawrev',
  law: 'kb', press: 'kb', guide: 'kb', itu: 'kb', custom: 'kb'
};

function go(page, navEl, sourceType) {
  document.querySelectorAll('.panel').forEach(function(p) { p.classList.remove('active'); });
  document.querySelectorAll('.nav-item').forEach(function(n) { n.classList.remove('active'); });
  var panel = document.getElementById('panel-' + page);
  if (panel) panel.classList.add('active');
  var navTarget = (navEl && navEl.classList) ? navEl
    : (PAGE_TO_NAV[page] ? document.querySelector('.nav-item[data-nav="' + PAGE_TO_NAV[page] + '"]') : null);
  if (navTarget && navTarget.classList) navTarget.classList.add('active');

  // 뉴스 소스 타입 설정
  if (page === 'news' && sourceType !== undefined) currentNewsSourceType = sourceType;

  // 상위 그룹 탭 바 (통합 모니터링 / 법령 개정 추적 / 지식베이스)
  renderGroupTabs(page);

  // 상단 바 제목 업데이트
  var newsTitle = currentNewsSourceType === 'gov' ? '정부 보도자료·공지사항 (최근 60일)' : (currentNewsSourceType === 'media' ? '뉴스 (최근 60일)' : '보도자료·뉴스 (최근 60일)');
  var titles = {home:'대시보드', chat:'AI 자문', reportdraft:'보고서 초안 제안', diff:'법령 개정 추적 — 조문 DIFF', law:'지식베이스 — 법령·고시', guide:'지식베이스 — 실무 안내', lawmap:'법령 관계도', itu:'지식베이스 — ITU-R', press:'지식베이스 — 보도자료', custom:'지식베이스 — 추가지식', terms:'기술 용어', news:newsTitle, briefing:'Daily Briefing', assembly:'국회 법안', minutes:'과방위 회의록', overseas:'해외 규제동향 (최근 60일)', lawtrack:'법령 개정 추적 — 입법예고·개정 현황', settings:'설정', opsstatus:'운영 상태'};
  var ttEl = document.getElementById('topbar-title');
  if (ttEl && titles[page]) ttEl.textContent = titles[page];

  // 모바일 하단 네비 동기화
  var pageTobn = {home:'bn-more', chat:'bn-chat', reportdraft:'bn-chat', lawmap:'bn-chat', law:'bn-law', guide:'bn-law', itu:'bn-law', press:'bn-law', custom:'bn-law', terms:'bn-monitor', news:'bn-monitor', briefing:'bn-monitor', assembly:'bn-bills', minutes:'bn-bills', overseas:'bn-monitor', lawtrack:'bn-bills', diff:'bn-bills', settings:'bn-more', opsstatus:'bn-more'};
  if (pageTobn[page]) setBottomNav(pageTobn[page]);

  if (page === 'news') loadNews();
  if (page === 'reportdraft') loadReportSamples();
  if (page === 'briefing') loadBriefing();
  if (page === 'settings') loadSettingsUI();
  if (page === 'press') loadPressFromSupabase();
  if (page === 'terms') loadTerms();
  if (page === 'law') loadKbDocs();
  if (page === 'guide') loadGuideDocs();
  if (page === 'lawmap') loadLawMap();
  if (page === 'assembly') loadAssemblyBills();
  if (page === 'minutes') loadAssemblyMinutes();
  if (page === 'overseas') loadOverseasNews();
  if (page === 'lawtrack') loadLawTrack();
  if (page === 'diff') _lawDiffsLoadPromise = loadLawDiffs();   // 국회 법안 → DIFF 딥링크가 await할 수 있게 Promise 보관
  if (page === 'opsstatus') loadOpsStatus();
}

// ════════════════════════════════════════════
//  상위 그룹 탭 바 — 메뉴 개편(2026-08-03) 공용 컴포넌트
//  기존 패널·로드 함수는 무수정: 탭 클릭 = 기존 go() 라우팅 호출
// ════════════════════════════════════════════
var PANEL_GROUP_OF = { news:'monitor', overseas:'monitor', lawtrack:'lawrev', diff:'lawrev', law:'kb', press:'kb', guide:'kb', itu:'kb', custom:'kb' };
var GROUP_TABS = {
  monitor: [
    { key: 'media',    label: '뉴스',              on: "go('news',null,'media')" },
    { key: 'gov',      label: '정부 보도자료·공지', on: "go('news',null,'gov')" },
    { key: 'overseas', label: '해외 규제동향',      on: "go('overseas',null)" }
  ],
  lawrev: [
    { key: 'lawtrack', label: '입법예고·개정 현황', on: "go('lawtrack',null)" },
    { key: 'diff',     label: '조문 DIFF',          on: "go('diff',null)" }
  ],
  kb: [
    { key: 'law',    label: '법령·고시', on: "go('law',null)" },
    { key: 'press',  label: '보도자료',  on: "go('press',null)" },
    { key: 'guide',  label: '실무 안내', on: "go('guide',null)" },
    { key: 'itu',    label: 'ITU-R',    on: "go('itu',null)" },
    { key: 'custom', label: '추가지식',  on: "go('custom',null)" }
  ]
};

function _activeGroupTabKey(group, page) {
  if (group === 'monitor') return page === 'overseas' ? 'overseas' : (currentNewsSourceType === 'gov' ? 'gov' : 'media');
  return page;
}

function renderGroupTabs(page) {
  var group = PANEL_GROUP_OF[page];
  if (!group) return;
  var panel = document.getElementById('panel-' + page);
  if (!panel) return;
  var bar = (panel.firstElementChild && panel.firstElementChild.classList.contains('group-tabbar'))
    ? panel.firstElementChild : null;
  if (!bar) {
    bar = document.createElement('div');
    bar.className = 'group-tabbar';
    bar.style.cssText = 'display:flex;gap:2px;margin-bottom:14px;border-bottom:1px solid var(--border);overflow-x:auto';
    panel.insertBefore(bar, panel.firstChild);
  }
  var act = _activeGroupTabKey(group, page);
  bar.innerHTML = GROUP_TABS[group].map(function(t) {
    var on = t.key === act;
    return '<div onclick="' + t.on + '" tabindex="0" role="button" aria-pressed="' + (on ? 'true' : 'false') + '" style="padding:7px 14px;font-size:12px;cursor:pointer;white-space:nowrap;margin-bottom:-1px;'
      + (on ? 'color:var(--accent);border-bottom:2px solid var(--accent);font-weight:600'
            : 'color:var(--text-secondary);border-bottom:2px solid transparent')
      + '">' + t.label + '</div>';
  }).join('');
}

// ════════════════════════════════════════════
//  상단바 상태등 — loadOpsStatus의 system_health 판정을 재사용한 경량 버전
//  임계는 loadOpsStatus와 동일 규약: crawl 1.5h / gov_notice 25h. 초과·부재 시 빨강.
// ════════════════════════════════════════════
async function refreshOpsLight() {
  var els = document.querySelectorAll('.ops-light');
  if (!els.length || !sb) return;
  var ok = null;
  try {
    var resp = await sb.from('system_health').select('key,updated_at');
    if (resp.error) throw resp.error;
    var hb = {};
    (resp.data || []).forEach(function(row) { hb[row.key] = row.updated_at; });
    var hoursAgo = function(iso) { return iso ? (Date.now() - new Date(iso).getTime()) / 3600000 : Infinity; };
    ok = hoursAgo(hb['last_crawl_run']) < 1.5 && hoursAgo(hb['last_gov_notice_run']) < 25;
  } catch (e) { ok = null; }
  els.forEach(function(el) {
    if (ok === null) { el.innerHTML = '⚪ <span>확인중</span>'; el.title = '상태 조회 실패 — 클릭해 운영 상태 확인'; return; }
    el.innerHTML = ok ? '🟢 <span>정상</span>' : '🔴 <span>점검</span>';
    el.title = ok ? '크롤러 하트비트 정상 — 클릭하면 운영 상태' : '하트비트 지연 감지 — 클릭해 운영 상태 확인';
  });
}

function setBottomNav(activeId) {
  document.querySelectorAll('.bottom-nav-item').forEach(function(b) { b.classList.remove('active'); });
  var el = document.getElementById(activeId);
  if (el) el.classList.add('active');
}

function showMobileSubMenu(id) {
  var el = document.getElementById(id);
  if (el) { el.style.display = 'block'; }
}

function closeMobileSubMenu(id) {
  var el = document.getElementById(id);
  if (el) { el.style.display = 'none'; }
}

// ════════════════════════════════════════════
//  보도자료 — Supabase document_chunks 검색
// ════════════════════════════════════════════
let pressData = null;
var currentPressAgency = '전체';  // 지식베이스 보도자료 기관 탭 상태
var PRESS_AGENCY_TABS = ['전체', '과기정통부', '전파연구원', '방통위', '전파관리소', 'ETRI', 'KISDI'];

// doc_name('{기관}_보도자료_{YYYY}.md')에서 기관 슬러그 추출 — 미지의 접두는 그대로 반환(깨지지 않게)
function pressAgencyOf(docName) {
  var name = docName || '';
  var i = name.indexOf('_보도자료_');
  if (i > 0) return name.substring(0, i);
  return '기타';
}

async function loadPressJSON() {
  var listEl = document.getElementById('press-list');
  if (listEl) listEl.innerHTML = '<div style="padding:20px;text-align:center;color:#aaa">로딩 중...</div>';

  if (!sb) { if (listEl) listEl.innerHTML = '<div style="padding:20px;color:#f66">Supabase 미연결</div>'; return; }

  try {
    // 1) 보도자료 전체 청크 조회 — ## YYMMDD 패턴 포함 청크만 ({n} 대신 명시적 반복)
    // 주의: Supabase는 요청당 최대 1,000행이라 .limit(2000)도 1,000에서 잘린다(무정렬이면
    // 어떤 1,000이 올지도 임의 → 최근분 누락). 백필로 6기관 1,100+섹션이 되면서 실제로
    // 발생 — 반드시 order+range 페이징으로 전량 수집 (2026-08-02, #53)
    var titleChunks = [];
    var queryErr    = null;
    var pageStart   = 0;
    while (true) {
      var resp = await sb
        .from('document_chunks')
        .select('doc_name, content')
        .eq('doc_category', '보도자료')
        // PostgREST의 정규식 연산자는 'match'(~에 해당) — '~'를 그대로 넘기면 PGRST100 파싱 실패로
        // 항상 폴백(전량 6,000+청크·4MB+)에 빠진다. 실측: match는 1,035청크·2요청으로 축소 (#61)
        .filter('content', 'match', '## [0-9][0-9][0-9][0-9][0-9][0-9]')
        .order('id')
        .range(pageStart, pageStart + 999);
      if (resp.error) { queryErr = resp.error; break; }
      titleChunks = titleChunks.concat(resp.data || []);
      if (!resp.data || resp.data.length < 1000) break;
      pageStart += 1000;
    }

    console.log('[보도자료] 쿼리 결과:', titleChunks ? titleChunks.length + '개 청크' : '없음', queryErr || '');

    // 정규식 필터가 지원되지 않으면 doc별 chunk_index=0만 조회 (각 파일 첫 청크에 목차 포함)
    if (queryErr || !titleChunks || titleChunks.length === 0) {
      console.warn('[보도자료] 정규식 필터 실패, chunk_index=0 폴백:', queryErr);
      // 각 doc의 모든 청크를 doc_name 순 정렬로 가져와 2026 포함 보장
      var results = [];
      // chunk_index=0 행만 조회하면 doc당 1행 → 수십 행으로 limit 초과 없음
      var docResp = await sb
        .from('document_chunks')
        .select('doc_name')
        .eq('doc_category', '보도자료')
        .eq('chunk_index', 0)
        .order('doc_name');
      var docNames = (docResp.data || []).map(function(r){ return r.doc_name; });
      for (var di = 0; di < docNames.length; di++) {
        // 문서 하나가 2,000청크를 넘을 수 있어(과기정통부) 여기도 range 페이징
        var docStart = 0;
        while (true) {
          var cr = await sb
            .from('document_chunks')
            .select('doc_name, content')
            .eq('doc_category', '보도자료')
            .eq('doc_name', docNames[di])
            .order('chunk_index')
            .range(docStart, docStart + 999);
          results = results.concat(cr.data || []);
          if (!cr.data || cr.data.length < 1000) break;
          docStart += 1000;
        }
      }
      titleChunks = results;
      console.log('[보도자료] doc별 폴백 결과:', titleChunks.length + '개 청크');
    }

    // 2) 제목 파싱
    var titleMap = {};
    var releases = [];

    titleChunks.forEach(function(chunk) {
      var lines = (chunk.content || '').split('\n');
      lines.forEach(function(line) {
        var m = line.match(/^##\s+(\d{6})\s*(.+)/);
        if (!m) return;
        var yymmdd   = m[1];
        var rawTitle = m[2].trim()
          .replace(/^(석간|조간)\s*/g, '')
          .replace(/^\(보도\)\s*/g,   '')
          .replace(/\s*\(수정\)\s*$/g, '')
          .replace(/^\[.*?\]\s*/g,    '')
          .trim();
        if (!rawTitle || rawTitle.length < 4) return;

        var yy   = parseInt(yymmdd.substring(0, 2), 10);
        var yyyy = '20' + (yy < 10 ? '0' + yy : '' + yy);
        var dateStr = yyyy + '-' + yymmdd.substring(2, 4) + '-' + yymmdd.substring(4, 6);
        var key  = dateStr + '_' + rawTitle.substring(0, 30);
        if (titleMap[key]) return;
        titleMap[key] = true;
        releases.push({ title: rawTitle, date: dateStr, doc_name: chunk.doc_name, agency: pressAgencyOf(chunk.doc_name) });
      });
    });

    releases.sort(function(a, b) { return b.date.localeCompare(a.date); });
    pressData = releases;

    // 3) 통계 — 연도별 건수 (청크가 아닌 보도자료 건수)
    var cnt = { total: releases.length, '2026': 0, '2025': 0, old: 0 };
    releases.forEach(function(r) {
      var y = r.date.substring(0, 4);
      if (y === '2026')      cnt['2026']++;
      else if (y === '2025') cnt['2025']++;
      else                   cnt.old++;
    });

    console.log('[보도자료] 파싱 결과:', cnt);

    var e;
    e = document.getElementById('ps-total'); if (e) e.textContent = cnt.total;
    e = document.getElementById('ps-2026');  if (e) e.textContent = cnt['2026'];
    e = document.getElementById('ps-2025');  if (e) e.textContent = cnt['2025'];
    e = document.getElementById('ps-old');   if (e) e.textContent = cnt.old;

    // stat-sub 텍스트도 "건"으로 (HTML 기본값 유지되므로 생략 가능)

    // 상단 출처 문구 동적 갱신 ("원본 파일 136개" 하드코딩 대체)
    var srcLine = document.getElementById('press-source-line');
    if (srcLine) srcLine.textContent = '보도자료 ' + cnt.total + '건 · 6개 기관 · 매일 17시 자동 수집 · 영구 누적';

    // 기관 탭·검색어 필터를 반영해 렌더
    filterPressList();

  } catch(err) {
    console.error('보도자료 로드 오류:', err);
    if (listEl) listEl.innerHTML = '<div style="padding:20px;color:#f66">오류: ' + (err.message || err) + '</div>';
  }
}

function renderPressList(list) {
  var el = document.getElementById('press-list');
  if (!el) return;

  if (!list || list.length === 0) {
    el.innerHTML = '<div style="padding:20px;text-align:center;color:#aaa">표시할 보도자료가 없습니다.</div>';
    return;
  }

  var groups = {};
  list.forEach(function(item) {
    var y = item.date.substring(0, 4);
    if (!groups[y]) groups[y] = [];
    groups[y].push(item);
  });

  var years = Object.keys(groups).sort(function(a, b) { return b - a; });
  var html = '';

  years.forEach(function(year) {
    var items = groups[year];
    html += '<div style="margin-bottom:20px">';
    html += '<div style="font-size:12px;font-weight:700;color:#888;letter-spacing:1px;' +
            'margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid #2a2a3a">' +
            year + '년 (' + items.length + '건)</div>';
    html += '<div style="display:flex;flex-direction:column;gap:4px">';
    items.forEach(function(item) {
      var dateLabel = item.date.substring(5);
      // onclick 인자: JS 문자열 이스케이프(\\, \') 후 속성 전체를 HTML 이스케이프 — 외부 유래 제목의 속성 탈출·스크립트 주입 차단 (#61)
      var jsTitle = escHtml(String(item.title).replace(/\\/g,'\\\\').replace(/'/g,"\\'"));
      var jsDoc   = escHtml(String(item.doc_name || '').replace(/\\/g,'\\\\').replace(/'/g,"\\'"));
      var agencyTag = item.agency
        ? '<span style="flex-shrink:0;font-size:10px;color:#8888aa;border:1px solid #33334a;border-radius:4px;padding:0 5px;margin-top:2px;white-space:nowrap">' + escHtml(item.agency) + '</span>'
        : '';
      html += '<div class="press-item" ' +
        'style="display:flex;align-items:flex-start;gap:8px;padding:5px 8px;' +
        'border-radius:6px;cursor:pointer;background:#1a1a2a" ' +
        'onclick="openPressDetail(\'' + jsTitle + '\',\'' + item.date + '\',\'' + jsDoc + '\')" ' +
        'onmouseover="this.style.background=\'#22223a\'" ' +
        'onmouseout="this.style.background=\'#1a1a2a\'">' +
        '<span style="flex-shrink:0;font-size:11px;color:#6c757d;width:36px;margin-top:2px">' + dateLabel + '</span>' +
        agencyTag +
        '<span style="font-size:13px;color:#d0d0e0;line-height:1.4">' + escHtml(item.title) + '</span>' +
        '</div>';
    });
    html += '</div></div>';
  });

  el.innerHTML = html;
}

function askAboutPress(el) {
  var title = el.getAttribute('data-title');
  go('chat');
  setTimeout(function() {
    var inp = document.getElementById('chat-input');
    if (inp) { inp.value = '"' + title + '" 보도자료의 주요 내용을 요약해 주세요.'; inp.focus(); }
  }, 300);
}

async function openPressDetail(title, date, docName) {
  var modal  = document.getElementById('press-detail-modal');
  var titleEl = document.getElementById('press-detail-title');
  var dateEl  = document.getElementById('press-detail-date');
  var bodyEl  = document.getElementById('press-detail-body');
  if (!modal) return;

  titleEl.textContent = title;
  dateEl.textContent  = date;
  bodyEl.innerHTML = '<div style="text-align:center;padding:30px;color:#aaa">불러오는 중...</div>';
  modal.style.display = 'flex';

  // '2026-01-15' → '260115'
  var yymmdd = date.replace(/-/g, '').substring(2);

  try {
    // 문서 하나가 2,000청크를 넘을 수 있어(과기정통부 백필) 500 limit → range 페이징 (#53)
    var chunks = [];
    var pageStart = 0;
    while (true) {
      var cr = await sb.from('document_chunks')
        .select('chunk_index, content')
        .eq('doc_name', docName)
        .order('chunk_index')
        .range(pageStart, pageStart + 999);
      if (cr.error) break;
      chunks = chunks.concat(cr.data || []);
      if (!cr.data || cr.data.length < 1000) break;
      pageStart += 1000;
    }

    if (chunks.length === 0) {
      bodyEl.innerHTML = '<div style="color:#f66;padding:20px">내용을 찾을 수 없습니다.</div>';
      return;
    }

    // 전체 텍스트 합치기 (청킹은 개행 경계라 join('')이 원문 그대로 복원)
    var fullText = chunks.map(function(c) { return c.content; }).join('');

    // ## YYMMDD 경계로 섹션 분리
    var sections = fullText.split(/(?=^## \d{6})/m);

    // 해당 날짜 + 제목이 함께 맞는 섹션 우선 (같은 날 여러 건이면 날짜만으론 오표시 — #53)
    var titleKey = (title || '').replace(/\s+/g, '').substring(0, 12).toLowerCase();
    var targetSection = null;
    var dateOnlyMatch = null;
    for (var i = 0; i < sections.length; i++) {
      if (!new RegExp('^## ' + yymmdd).test(sections[i])) continue;
      if (!dateOnlyMatch) dateOnlyMatch = sections[i];
      var headerLine = (sections[i].split('\n')[0] || '').replace(/\s+/g, '').toLowerCase();
      if (titleKey && headerLine.indexOf(titleKey) !== -1) {
        targetSection = sections[i];
        break;
      }
    }
    if (!targetSection) targetSection = dateOnlyMatch;

    if (!targetSection) {
      // 제목으로 검색 폴백
      targetSection = sections.find(function(s) {
        return s.toLowerCase().indexOf(title.toLowerCase().substring(0, 10)) !== -1;
      }) || null;
    }

    if (!targetSection) {
      bodyEl.innerHTML = '<div style="color:#f66;padding:20px">해당 보도자료 내용을 찾을 수 없습니다.</div>';
      return;
    }

    // 불필요한 이미지 설명, 중복 제목 라인 정리
    var cleaned = targetSection
      .replace(/그림입니다\.\n원본 그림의 이름:[^\n]+\n원본 그림의 크기:[^\n]+/g, '')
      .replace(/^# \d{6}[^\n]*\n/m, '')  // # YYMMDD 중복 제목 제거
      .replace(/\n{3,}/g, '\n\n')
      .trim();

    // 수집 시 저장해 둔 '(원문: URL)' 추출 — 본문에서는 빼고 상단 버튼으로 노출 (#53)
    var srcUrl = null;
    var srcMatch = cleaned.match(/\(원문:\s*(https?:[^\s)]+)\)/);
    if (srcMatch) {
      srcUrl = srcMatch[1];
      cleaned = cleaned.replace(/\(원문:\s*https?:[^\s)]+\)\s*/g, '').trim();
    }

    // 간단한 마크다운 → HTML 변환
    var html = cleaned
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/^## (.+)$/gm, '<h3 style="color:var(--accent-purple);font-size:14px;margin:16px 0 6px">$1</h3>')
      .replace(/^### (.+)$/gm, '<h4 style="color:var(--text-primary);font-size:13px;margin:12px 0 4px;font-weight:600">$1</h4>')
      .replace(/^- (.+)$/gm, '<li style="margin:2px 0">$1</li>')
      .replace(/(<li[^>]*>.*<\/li>\n?)+/g, function(m){ return '<ul style="padding-left:20px;margin:6px 0">' + m + '</ul>'; })
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\n/g, '<br>');

    if (srcUrl) {
      // 원문 페이지에는 첨부(HWPX/PDF)도 있어 그림·인포그래픽까지 확인 가능 (스킴은 위 정규식이 https?:로 한정)
      html = '<div style="margin-bottom:12px"><a href="' + escHtml(srcUrl)
           + '" target="_blank" rel="noopener" class="btn" style="font-size:12px;text-decoration:none">'
           + '<i class="ti ti-external-link"></i> 원문 보기 (기관 사이트 · 첨부 포함)</a></div>' + html;
    }

    bodyEl.innerHTML = html;

  } catch(e) {
    bodyEl.innerHTML = '<div style="color:#f66;padding:20px">오류: ' + (e.message || e) + '</div>';
  }
}

function closePressDetail() {
  var modal = document.getElementById('press-detail-modal');
  if (modal) modal.style.display = 'none';
}

async function filterPressList() {
  if (!pressData) return;
  var list = pressData;
  // 1) 기관 탭 필터
  if (currentPressAgency !== '전체') {
    list = list.filter(function(item) { return item.agency === currentPressAgency; });
  }
  // 2) 검색어 필터
  var q = (document.getElementById('press-search-input') || {}).value || '';
  if (q.trim()) {
    var lower = q.toLowerCase();
    list = list.filter(function(item) {
      return item.title.toLowerCase().includes(lower) ||
             (item.doc_name || '').toLowerCase().includes(lower) ||
             item.date.includes(lower);
    });
  }
  renderPressList(list);
}

// 지식베이스 보도자료 기관 탭 클릭
function filterPressAgency(el, agency) {
  currentPressAgency = agency;
  document.querySelectorAll('#press-agency-tabs .tag').forEach(function(t) { t.classList.remove('selected'); });
  if (el && el.classList) el.classList.add('selected');
  filterPressList();
}

function loadPressFromSupabase() { loadPressJSON(); }

// ── 수집 키워드 관리 (app_config key='press_keywords') ─────────────
// 보도자료 크롤러가 매일 17시 수집 시 참조하는 키워드 목록을 대시보드에서 편집한다.
var _pressKeywords = [];      // 편집 중인 키워드 배열
var _pkLoaded = false;        // 최초 열림 시 1회만 로드

function togglePressKeywordCard() {
  var body = document.getElementById('pk-body');
  var icon = document.getElementById('pk-toggle-icon');
  if (!body) return;
  var open = body.style.display === 'none';
  body.style.display = open ? 'block' : 'none';
  if (icon) icon.style.transform = open ? 'rotate(180deg)' : '';
  if (open && !_pkLoaded) loadPressKeywords();
}

function _pkShowMsg(text, isError) {
  var el = document.getElementById('pk-msg');
  if (!el) return;
  if (!text) { el.style.display = 'none'; el.textContent = ''; return; }
  el.style.display = 'block';
  el.textContent = text;
  el.style.color = isError ? '#ef4444' : '#22c55e';
}

async function loadPressKeywords() {
  var chipsEl = document.getElementById('pk-chips');
  if (chipsEl) chipsEl.innerHTML = '<span style="font-size:12px;color:var(--text-tertiary)">불러오는 중...</span>';
  _pkShowMsg('');
  if (!sb) { _pkShowMsg('Supabase 미연결 — 키워드를 불러올 수 없습니다.', true); if (chipsEl) chipsEl.innerHTML = ''; return; }
  try {
    var resp = await sb.from('app_config').select('value').eq('key', 'press_keywords').limit(1);
    if (resp.error) throw resp.error;
    var raw = (resp.data && resp.data[0]) ? resp.data[0].value : null;
    var arr = [];
    if (raw) {
      try { arr = JSON.parse(raw); } catch(pe) { console.warn('press_keywords JSON 파싱 실패:', pe); }
    }
    _pressKeywords = Array.isArray(arr) ? arr.filter(function(k) { return typeof k === 'string' && k.trim(); }) : [];
    _pkLoaded = true;
    renderPressKeywordChips();
  } catch(e) {
    if (chipsEl) chipsEl.innerHTML = '';
    _pkShowMsg('키워드 불러오기 실패: ' + (e.message || e), true);
  }
}

function renderPressKeywordChips() {
  var el = document.getElementById('pk-chips');
  if (!el) return;
  if (!_pressKeywords.length) {
    el.innerHTML = '<span style="font-size:12px;color:var(--text-tertiary)">등록된 키워드가 없습니다. 아래에서 추가하세요.</span>';
    return;
  }
  el.innerHTML = _pressKeywords.map(function(kw, i) {
    var safe = kw.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return '<span class="tag" style="cursor:default;display:inline-flex;align-items:center;gap:5px">' + safe +
      '<span onclick="removePressKeyword(' + i + ')" title="삭제" ' +
      'style="cursor:pointer;font-weight:700;opacity:.6;line-height:1">&times;</span></span>';
  }).join('');
}

function addPressKeyword() {
  var inp = document.getElementById('pk-new-input');
  if (!inp) return;
  var kw = (inp.value || '').trim();
  if (!kw) return;
  if (_pressKeywords.indexOf(kw) !== -1) { _pkShowMsg('이미 있는 키워드입니다: ' + kw, true); return; }
  _pressKeywords.push(kw);
  inp.value = '';
  _pkShowMsg('');
  renderPressKeywordChips();
}

function removePressKeyword(idx) {
  _pressKeywords.splice(idx, 1);
  _pkShowMsg('');
  renderPressKeywordChips();
}

async function savePressKeywords(btn) {
  if (!sb) { _pkShowMsg('Supabase 미연결 — 저장할 수 없습니다.', true); return; }
  if (btn) btn.disabled = true;
  _pkShowMsg('저장 중...');
  try {
    var resp = await sb.from('app_config').upsert(
      { key: 'press_keywords', value: JSON.stringify(_pressKeywords) },
      { onConflict: 'key' }
    );
    if (resp.error) throw resp.error;
    _pkShowMsg('저장됨 — 다음 수집(매일 17시)부터 적용');
  } catch(e) {
    _pkShowMsg('저장 실패: ' + (e.message || e), true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ════════════════════════════════════════════
//  기술 용어 자동 추출 (하루 1회, 백그라운드)
// ════════════════════════════════════════════
// ── 신규 용어 상세 자동 채움 (배경역사 #46) ──────────────────────
// 순차 실행한다 — 동시에 던지면 API 레이트리밋에 걸리고, 어차피 백그라운드라
// 빠를 이유가 없다. 한 건이 실패해도 나머지는 계속 채운다(부분 성공 허용).
async function backfillTermDetails(rows, claudeKey) {
  if (!sb || !claudeKey || !rows || !rows.length) return;
  var ok = 0;
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i];
    try {
      var parsed = await _fetchTermDetail(row, claudeKey);
      if (!parsed.description) continue;      // 빈 응답이면 덮어쓰지 않는다
      var up = await sb.from('tech_terms').update({
        description:   parsed.description,
        diagram_html:  parsed.diagram_html,
        related_terms: parsed.related_terms
      }).eq('id', row.id);
      if (!up.error) {
        ok++;
        // 목록이 이미 떠 있으면 즉시 반영 (안 떠 있으면 다음 loadTerms에서 반영됨)
        var idx = (typeof termsData !== 'undefined' && termsData)
          ? termsData.findIndex(function(x) { return x.id === row.id; }) : -1;
        if (idx >= 0) {
          termsData[idx].description   = parsed.description;
          termsData[idx].diagram_html  = parsed.diagram_html;
          termsData[idx].related_terms = parsed.related_terms;
        }
      }
    } catch(e) {
      console.warn('[기술 용어] 상세 자동 생성 실패(' + row.term + '):', e.message);
    }
  }
  console.log('[기술 용어] 상세 자동 생성 ' + ok + '/' + rows.length + '건');
  if (ok && document.getElementById('panel-terms')
      && document.getElementById('panel-terms').classList.contains('active')) {
    loadTerms();
  }
}

async function autoExtractTermsIfNeeded() {
  var today = new Date().toISOString().slice(0, 10);
  var lastRun = localStorage.getItem('last_terms_extraction');
  if (lastRun === today) return; // 오늘 이미 실행함
  if (!sb) return;
  var { claudeKey } = getConfig();
  if (!claudeKey) return;

  try {
    var cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - 7);
    var cutoffStr = cutoff.toISOString().split('T')[0];
    var newsResp = await sb.from('news_feed')
      .select('title,source,published_at')
      .gte('created_at', cutoffStr)
      .order('created_at', { ascending: false })
      .limit(30);
    var newsList = (newsResp.data || []).map(function(n) {
      return '[' + (n.published_at || '').slice(0, 10) + '] ' + n.title + ' (' + (n.source || '') + ')';
    }).join('\n');
    if (!newsList) { console.log('[기술 용어] 최근 뉴스 없음, 스킵'); return; }

    var existingResp = await sb.from('tech_terms').select('term').limit(500);
    var existingSet = new Set((existingResp.data || []).map(function(t) { return t.term.toLowerCase(); }));

    var userMsg = '아래 뉴스 목록에서 이동통신·전파 분야 기술 용어(영문 약어, 표준명, 새 기술명)를 추출하세요.\n' +
      '흔한 용어(5G, LTE, Wi-Fi 등)는 제외하세요.\n\n' +
      '뉴스 목록:\n' + newsList + '\n\n' +
      'JSON 배열로만 출력 (신규 용어만, 없으면 []): [{"term":"...","term_en":"...","category":"...","definition":"...","source":"..."}]';

    var res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'x-api-key': claudeKey,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
        'anthropic-dangerous-direct-browser-access': 'true'
      },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 1000,
        messages: [{ role: 'user', content: userMsg }]
      })
    });
    var data = await res.json();
    var textBlock = data.content && data.content.find(function(b) { return b.type === 'text'; });
    var text = textBlock ? textBlock.text : '';
    if (!text) return;

    var firstBracket = text.indexOf('[');
    var lastBracket = text.lastIndexOf(']');
    if (firstBracket === -1 || lastBracket === -1) return;
    var terms = [];
    try { terms = JSON.parse(text.slice(firstBracket, lastBracket + 1)); } catch(e) { return; }
    if (!terms.length) { console.log('[기술 용어] 신규 용어 없음'); return; }

    var saved = 0, newRows = [];
    for (var t of terms) {
      if (!t.term || existingSet.has(t.term.toLowerCase())) continue;
      var payload = {
        term: t.term,
        term_en: t.term_en || '',
        category: t.category || '기타',
        definition: t.definition || '',
        source: t.source || '뉴스 자동 추출',
        is_reviewed: false
      };
      // 이어서 상세 생성을 걸어야 하므로 삽입된 행(id 포함)을 받아 둔다
      var r2 = await sb.from('tech_terms').insert(payload).select('id,term,term_en,category,definition');
      if (!r2.error) {
        saved++;
        existingSet.add(t.term.toLowerCase());
        if (r2.data && r2.data[0]) newRows.push(r2.data[0]);
      }
    }
    localStorage.setItem('last_terms_extraction', today);
    console.log('[기술 용어] 자동 추출 완료:', saved, '건 저장');

    // 신규 용어의 상세 설명·개념도를 곧바로 채운다 — 운영자가 클릭할 때까지
    // 비워 두면 열어 볼 때마다 수십 초를 기다려야 한다. (배경역사 #46)
    if (newRows.length) await backfillTermDetails(newRows, claudeKey);

    // 과거에 생성이 실패했거나 자동화 이전에 들어온 빈 용어도 같이 메운다.
    // 하루 5건으로 제한 — 한 번에 몰아 돌리면 API 비용·시간이 튄다.
    try {
      var empties = await sb.from('tech_terms')
        .select('id,term,term_en,category,definition')
        .or('description.is.null,description.eq.')
        .limit(5);
      var pending = (empties.data || []).filter(function(r) {
        return !newRows.some(function(n) { return n.id === r.id; });
      });
      if (pending.length) {
        console.log('[기술 용어] 미완성 ' + pending.length + '건 보충 생성');
        await backfillTermDetails(pending, claudeKey);
      }
    } catch(e) { console.warn('[기술 용어] 미완성 보충 조회 실패:', e); }
  } catch(e) {
    console.warn('[기술 용어] 자동 추출 오류:', e);
  }
}

// ════════════════════════════════════════════
//  추가 지식 — UI 함수 (패널 탭 전환 / 저장 / 목록 렌더)
// ════════════════════════════════════════════
var _editingCustomId = null; // null이면 신규 입력, 숫자면 수정 중인 항목 id

function switchCustomTab(tab) {
  document.getElementById('custom-tab-input').style.display = tab === 'input' ? '' : 'none';
  document.getElementById('custom-tab-list').style.display  = tab === 'list'  ? '' : 'none';
  document.getElementById('ctab-input').classList.toggle('active', tab === 'input');
  document.getElementById('ctab-list').classList.toggle('active',  tab === 'list');
  if (tab === 'list') renderCustomKnowledgeList();
}

function setCustomEditMode(id) {
  _editingCustomId = id;
  var banner = document.getElementById('ck-edit-banner');
  var saveBtn = document.getElementById('ck-save-btn');
  var cancelBtn = document.getElementById('ck-cancel-btn');
  if (id) {
    if (banner) { banner.style.display = ''; banner.textContent = '✏️ 수정 모드 — 내용을 변경한 뒤 저장하세요.'; }
    if (saveBtn) { saveBtn.textContent = '수정 저장'; saveBtn.style.background = '#f59e0b'; }
    if (cancelBtn) cancelBtn.style.display = '';
  } else {
    if (banner) banner.style.display = 'none';
    if (saveBtn) { saveBtn.textContent = '저장하기'; saveBtn.style.background = ''; }
    if (cancelBtn) cancelBtn.style.display = 'none';
    // 폼 초기화
    var t = document.getElementById('ck-title');
    var c = document.getElementById('ck-content');
    var g = document.getElementById('ck-tags');
    var cat = document.getElementById('ck-category');
    if (t) t.value = '';
    if (c) c.value = '';
    if (g) g.value = '';
    if (cat) cat.value = '일반';
  }
}

async function renderCustomKnowledgeList(filterText) {
  var listEl = document.getElementById('custom-list-items');
  if (!listEl) return;
  listEl.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-secondary);font-size:12px"><i class="ti ti-loader"></i> 불러오는 중...</div>';
  try {
    var ckItems = await loadCustomKnowledgeList();
    var fileItems = await loadCustomFileList();
    var items = ckItems.concat(fileItems).sort(function(a, b) {
      return (b.created_at || '').localeCompare(a.created_at || '');
    });
    if (filterText) {
      var q = filterText.toLowerCase();
      items = items.filter(function(i) {
        var name = (i._type === 'file' ? i.doc_name : i.title) || '';
        return name.toLowerCase().includes(q) || (i.tags || []).join(' ').toLowerCase().includes(q);
      });
    }
    if (items.length === 0) {
      listEl.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-secondary);font-size:12px">저장된 지식이 없습니다.</div>';
      return;
    }
    listEl.innerHTML = items.map(function(item) {
      if (item._type === 'file') {
        var fdate = (item.created_at || '').slice(0, 10);
        var pending = item.embedded < item.chunks;
        var nameEsc = chEsc(item.doc_name);
        var attrEsc = nameEsc.replace(/"/g, '&quot;');
        var statusBadge = pending
          ? '<span style="font-size:10px;background:#fef3c7;color:#92400e;border-radius:4px;padding:1px 6px">임베딩 대기</span>'
          : '<span style="font-size:10px;background:#dcfce7;color:#166534;border-radius:4px;padding:1px 6px">임베딩 완료</span>';
        // 원본 파일이 보관돼 있으면(file_path) 파일명 클릭 시 다운로드
        var hasFile = !!item.file_path;
        var pathAttr = hasFile ? item.file_path.replace(/"/g, '&quot;') : '';
        var nameHtml = hasFile
          ? '<a href="#" data-path="' + pathAttr + '" data-name="' + attrEsc + '" onclick="onDownloadCustomFile(this.getAttribute(\'data-path\'),this.getAttribute(\'data-name\'));return false;" style="font-size:12px;font-weight:600;color:var(--accent);text-decoration:none;cursor:pointer" title="원본 파일 다운로드">' + nameEsc + ' <i class="ti ti-download" style="font-size:11px"></i></a>'
          : '<span style="font-size:12px;font-weight:600;color:var(--text-primary)" title="원본 파일 미보관 — 텍스트만 저장됨">' + nameEsc + '</span>';
        return '<div style="display:flex;align-items:flex-start;gap:10px;padding:10px 0;border-bottom:0.5px solid var(--border-light)">' +
          '<div style="flex:1;min-width:0">' +
            '<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">' +
              '<span style="font-size:10px;background:#6366f1;color:#fff;border-radius:4px;padding:1px 6px">📎 파일</span>' +
              nameHtml +
            '</div>' +
            '<div style="font-size:11px;color:var(--text-tertiary)">' + fdate + ' · 청크 ' + item.chunks + '개 · ' + statusBadge + '</div>' +
          '</div>' +
          '<button data-doc="' + attrEsc + '" onclick="onDeleteCustomFile(this.getAttribute(\'data-doc\'),this)" style="background:none;border:none;color:var(--text-tertiary);cursor:pointer;font-size:13px;padding:2px 4px" title="파일 삭제"><i class="ti ti-trash"></i></button>' +
        '</div>';
      }
      var tagsHtml = (item.tags || []).map(function(t) {
        return '<span style="background:var(--bg-tertiary);border-radius:4px;padding:1px 6px;font-size:10px;color:var(--text-secondary)">' + escHtml(t) + '</span>';
      }).join(' ');
      var date = (item.created_at || '').slice(0, 10);
      return '<div style="display:flex;align-items:flex-start;gap:10px;padding:10px 0;border-bottom:0.5px solid var(--border-light)">' +
        '<div style="flex:1;min-width:0">' +
          '<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">' +
            '<span style="font-size:10px;background:var(--accent);color:#fff;border-radius:4px;padding:1px 6px">' + escHtml(item.category || '일반') + '</span>' +
            '<span style="font-size:12px;font-weight:600;color:var(--text-primary)">' + escHtml(item.title) + '</span>' +
          '</div>' +
          '<div style="font-size:11px;color:var(--text-tertiary)">' + date + (tagsHtml ? ' · ' + tagsHtml : '') + '</div>' +
        '</div>' +
        '<button onclick="onEditCustom(' + item.id + ')" style="background:none;border:none;color:var(--accent);cursor:pointer;font-size:13px;padding:2px 4px;margin-right:2px" title="수정"><i class="ti ti-edit"></i></button>' +
        '<button onclick="onDeleteCustom(' + item.id + ',this)" style="background:none;border:none;color:var(--text-tertiary);cursor:pointer;font-size:13px;padding:2px 4px" title="삭제"><i class="ti ti-trash"></i></button>' +
      '</div>';
    }).join('');
  } catch(e) {
    listEl.innerHTML = '<div style="padding:16px;color:#dc2626;font-size:12px">목록 로드 실패: ' + e.message + '</div>';
  }
}

async function onEditCustom(id) {
  // Supabase에서 해당 항목 전체 내용 불러오기
  try {
    var { data, error } = await sb.from('custom_knowledge')
      .select('id, title, content, category, tags')
      .eq('id', id)
      .single();
    if (error || !data) { alert('항목을 불러올 수 없습니다.'); return; }
    // 입력 탭으로 전환 후 폼에 채워 넣기
    switchCustomTab('input');
    document.getElementById('ck-title').value   = data.title || '';
    document.getElementById('ck-content').value = data.content || '';
    document.getElementById('ck-category').value = data.category || '일반';
    document.getElementById('ck-tags').value    = (data.tags || []).join(', ');
    setCustomEditMode(id);
    // 화면 상단으로 스크롤
    document.getElementById('ck-title').scrollIntoView({ behavior: 'smooth', block: 'center' });
  } catch(e) {
    alert('항목 로드 실패: ' + e.message);
  }
}

async function onSaveCustomKnowledge() {
  var title    = (document.getElementById('ck-title')   || {}).value || '';
  var category = (document.getElementById('ck-category')|| {}).value || '일반';
  var content  = (document.getElementById('ck-content') || {}).value || '';
  var tags     = (document.getElementById('ck-tags')    || {}).value || '';
  var btn      = document.getElementById('ck-save-btn');
  if (!title.trim() || !content.trim()) { alert('제목과 내용을 모두 입력하세요.'); return; }
  var isEdit = !!_editingCustomId;
  btn.disabled = true;
  btn.textContent = isEdit ? '수정 중...' : '저장 중...';
  try {
    if (isEdit) {
      await updateCustomKnowledge(_editingCustomId, title.trim(), content.trim(), category, tags);
    } else {
      await saveCustomKnowledge(title.trim(), content.trim(), category, tags);
    }
    btn.textContent = isEdit ? '✅ 수정됨' : '✅ 저장됨';
    btn.style.background = '#22c55e';
    setCustomEditMode(null); // 수정 모드 해제 + 폼 초기화
    setTimeout(function() { btn.disabled = false; btn.style.background = ''; }, 2000);
  } catch(e) {
    alert((isEdit ? '수정' : '저장') + ' 실패: ' + e.message);
    btn.disabled = false;
    btn.textContent = isEdit ? '수정 저장' : '저장하기';
  }
}

async function onDeleteCustom(id, btn) {
  if (!confirm('이 지식을 삭제하시겠습니까?')) return;
  btn.disabled = true;
  try {
    await deleteCustomKnowledge(id);
    renderCustomKnowledgeList(
      (document.getElementById('ck-list-search') || {}).value || ''
    );
  } catch(e) {
    alert('삭제 실패: ' + e.message);
    btn.disabled = false;
  }
}

// ════════════════════════════════════════════
//  PDF 업로드 — 법령·고시 / 보도자료 → document_chunks
// ════════════════════════════════════════════
let _pdfUploadCtx = 'law'; // 'law' | 'press'

function openPdfUpload(ctx) {
  _pdfUploadCtx = ctx;
  var modal = document.getElementById('pdf-upload-modal');
  var title = document.getElementById('pdf-modal-title');
  var catRow = document.getElementById('pdf-cat-row');
  var dateRow = document.getElementById('pdf-date-row');
  var prog = document.getElementById('pdf-progress');
  var btn = document.getElementById('pdf-upload-btn');
  var label = document.getElementById('pdf-file-label');
  document.getElementById('pdf-doc-name').value = '';
  document.getElementById('pdf-file-input').value = '';
  document.getElementById('pdf-press-date').value = new Date().toISOString().slice(0,10);
  if (prog) prog.style.display = 'none';
  if (btn) { btn.disabled = false; btn.innerHTML = '<i class="ti ti-upload"></i> 업로드'; }
  if (label) label.textContent = 'PDF · MD · Word · PPTX 파일 클릭 선택 또는 드래그';

  if (ctx === 'press') {
    if (title) title.textContent = '정부 보도자료 업로드 (PDF · MD · Word · PPTX)';
    if (catRow) catRow.style.display = 'none';
    if (dateRow) dateRow.style.display = 'none';
  } else if (ctx === 'itu') {
    if (title) title.textContent = 'ITU-R 문서 업로드 (PDF · MD · Word · PPTX)';
    if (catRow) catRow.style.display = 'none';
    if (dateRow) dateRow.style.display = 'none';
  } else {
    // 'custom'(추가 지식) — 법령·고시 업로드 진입점은 없앴다(#52). API(law_sync.py)가
    // 조문 구조를 그대로 가져와 PDF 추출보다 정확하고, PDF로 넣으면 article_no가 어긋난다.
    // API에 없는 예외 문서는 PC에서 upload_law_pdf.py로 넣는다.
    if (title) title.textContent = '추가 지식 파일 업로드 (PDF · MD · Word · PPTX)';
    if (catRow) catRow.style.display = 'none';
    if (dateRow) dateRow.style.display = 'none';
  }
  modal.style.display = 'flex';
}

function closePdfUpload() {
  var modal = document.getElementById('pdf-upload-modal');
  if (modal) modal.style.display = 'none';
}

function handlePdfFileSelect(input) {
  if (!input.files || !input.files[0]) return;
  var files = Array.from(input.files);
  var nameInput = document.getElementById('pdf-doc-name');
  var label = document.getElementById('pdf-file-label');
  if (files.length === 1) {
    var file = files[0];
    if (label) label.textContent = file.name + ' (' + (file.size / 1024).toFixed(0) + ' KB)';
    if (nameInput && !nameInput.value) {
      nameInput.value = file.name.replace(/\.(pdf|md|pptx|docx)$/i, '').replace(/[_-]/g, ' ');
    }
  } else {
    if (label) label.textContent = files.length + '개 파일 선택됨';
    if (nameInput && !nameInput.value) nameInput.value = '(파일명 자동)';
  }
}

async function _extractMdText(file) {
  return new Promise(function(resolve, reject) {
    var reader = new FileReader();
    reader.onload = function(e) { resolve(e.target.result); };
    reader.onerror = reject;
    reader.readAsText(file, 'UTF-8');
  });
}

async function _extractPptxText(file) {
  if (typeof JSZip === 'undefined') throw new Error('JSZip 라이브러리 미로드');
  var arrayBuffer = await file.arrayBuffer();
  var zip = await JSZip.loadAsync(arrayBuffer);
  var slideTexts = [];
  var slideFiles = Object.keys(zip.files)
    .filter(function(name) { return /^ppt\/slides\/slide[0-9]+\.xml$/.test(name); })
    .sort();
  for (var i = 0; i < slideFiles.length; i++) {
    var xml = await zip.files[slideFiles[i]].async('string');
    var text = xml
      .replace(/<a:t>/g, ' ')
      .replace(/<\/a:t>/g, '')
      .replace(/<[^>]+>/g, '')
      .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
      .replace(/\s+/g, ' ').trim();
    if (text.length > 10) slideTexts.push('--- 슬라이드 ' + (i + 1) + ' ---\n' + text);
  }
  return slideTexts.join('\n\n');
}

async function _extractDocxText(file) {
  if (typeof mammoth === 'undefined') throw new Error('mammoth 라이브러리 미로드');
  var arrayBuffer = await file.arrayBuffer();
  var result = await mammoth.extractRawText({ arrayBuffer: arrayBuffer });
  return (result && result.value) ? result.value : '';
}

function handlePdfDrop(event) {
  event.preventDefault();
  var dz = document.getElementById('pdf-drop-zone');
  if (dz) dz.style.borderColor = 'var(--border-mid)';
  var files = Array.from(event.dataTransfer.files || []);
  var allowed = /\.(pdf|md|pptx|docx)$/i;
  files = files.filter(function(f) { return allowed.test(f.name); });
  if (files.length === 0) {
    alert('PDF · MD · Word(docx) · PPTX 파일만 업로드 가능합니다.');
    return;
  }
  var input = document.getElementById('pdf-file-input');
  // DataTransfer로 file input 설정 (다중 파일 지원)
  var dt = new DataTransfer();
  files.forEach(function(f) { dt.items.add(f); });
  input.files = dt.files;
  handlePdfFileSelect(input);
}

function _setPdfProgress(pct, text) {
  var bar = document.getElementById('pdf-progress-bar');
  var txt = document.getElementById('pdf-progress-text');
  if (bar) bar.style.width = pct + '%';
  if (txt) txt.textContent = text;
}

async function _extractPdfText(file) {
  var arrayBuffer = await file.arrayBuffer();
  var loadingTask = pdfjsLib.getDocument({ data: arrayBuffer });
  var pdf = await loadingTask.promise;
  var pages = [];
  for (var i = 1; i <= pdf.numPages; i++) {
    var page = await pdf.getPage(i);
    var tc = await page.getTextContent();
    var pageText = tc.items.map(function(item) { return item.str; }).join(' ');
    pages.push(pageText.trim());
  }
  return pages.join('\n\n');
}

function _chunkText(text) {
  var CHUNK_SIZE = 800;
  var OVERLAP = 100;
  var chunks = [];

  // 조항 경계 기준으로 우선 분할
  var blocks = text.split(/(?=제\d+조)/);
  if (blocks.length < 5) blocks = [text];

  blocks.forEach(function(block) {
    block = block.trim();
    if (!block) return;
    if (block.length <= CHUNK_SIZE) {
      if (block.length > 50) chunks.push(block);
    } else {
      var start = 0;
      while (start < block.length) {
        var chunk = block.slice(start, start + CHUNK_SIZE).trim();
        if (chunk.length > 50) chunks.push(chunk);
        start += CHUNK_SIZE - OVERLAP;
      }
    }
  });
  return chunks;
}

async function doPdfUpload() {
  if (!sb) { alert('Supabase 연결이 필요합니다.'); return; }
  var fileInput = document.getElementById('pdf-file-input');
  var docName = (document.getElementById('pdf-doc-name').value || '').trim();
  var category = _pdfUploadCtx === 'press'
    ? '보도자료'
    : _pdfUploadCtx === 'itu'
    ? 'ITU-R'
    : _pdfUploadCtx === 'custom'
    ? '추가지식'
    : (document.getElementById('pdf-category').value || '고시');
  var pressDate = (document.getElementById('pdf-press-date').value || '');

  if (!fileInput.files || !fileInput.files[0]) { alert('파일을 선택해주세요.'); return; }
  if (!docName && fileInput.files.length === 1) { alert('문서명을 입력해주세요.'); return; }
  if (_pdfUploadCtx === 'press' && !pressDate) { alert('보도자료 날짜를 입력해주세요.'); return; }

  var btn = document.getElementById('pdf-upload-btn');
  var prog = document.getElementById('pdf-progress');
  btn.disabled = true;
  btn.innerHTML = '<i class="ti ti-loader"></i> 처리 중...';
  prog.style.display = 'block';

  var files = Array.from(fileInput.files);
  var totalFiles = files.length;
  var totalChunks = 0;

  try {
    for (var fi = 0; fi < files.length; fi++) {
      var file = files[fi];
      var ext = file.name.split('.').pop().toLowerCase();
      // 다중 파일일 때 doc_name은 파일명(확장자 제거), 단일 파일이면 입력값
      var thisDocName = (totalFiles > 1)
        ? file.name.replace(/\.[^.]+$/, '')
        : (docName || file.name.replace(/\.[^.]+$/, ''));

      var fileProgress = fi / totalFiles;
      var fileProgressEnd = (fi + 1) / totalFiles;

      // 1. 텍스트 추출
      _setPdfProgress(
        Math.round(fileProgress * 80 + 5),
        '(' + (fi+1) + '/' + totalFiles + ') ' + file.name + ' 텍스트 추출 중...'
      );
      var text;
      if (ext === 'pdf') {
        text = await _extractPdfText(file);
        if (text.replace(/\s/g, '').length < 100) {
          throw new Error(file.name + ': 텍스트를 추출할 수 없습니다. 스캔 이미지 PDF이거나 암호화된 파일일 수 있습니다.');
        }
      } else if (ext === 'md') {
        text = await _extractMdText(file);
        if (text.replace(/\s/g, '').length < 10) {
          throw new Error(file.name + ': 내용이 없거나 읽을 수 없는 파일입니다.');
        }
      } else if (ext === 'pptx') {
        text = await _extractPptxText(file);
        if (text.replace(/\s/g, '').length < 10) {
          throw new Error(file.name + ': 텍스트를 추출할 수 없습니다.');
        }
      } else if (ext === 'docx') {
        text = await _extractDocxText(file);
        if (text.replace(/\s/g, '').length < 10) {
          throw new Error(file.name + ': 텍스트를 추출할 수 없습니다. 내용이 없거나 .doc(구버전) 파일일 수 있습니다.');
        }
      } else {
        throw new Error(file.name + ': 지원하지 않는 형식입니다. PDF, MD, Word(docx), PPTX만 가능합니다.');
      }

      // 1-b. 추가지식: 원본 파일을 Storage(uploads)에 보관 → 목록에서 클릭 다운로드
      var thisFilePath = null;
      if (_pdfUploadCtx === 'custom') {
        try {
          var keyBase = file.name.replace(/\.[^.]+$/, '')
            .replace(/[^\x00-\x7F]/g, '')      // 비ASCII 제거 (Storage 키 안전)
            .replace(/[^\w.\-]/g, '_') || 'file';
          thisFilePath = 'custom/' + Date.now() + '_' + keyBase + '.' + ext;
          var up = await sb.storage.from('uploads').upload(thisFilePath, file, {
            upsert: true,
            contentType: file.type || undefined
          });
          if (up.error) { console.warn('원본 파일 보관 실패:', up.error.message); thisFilePath = null; }
        } catch(se) { console.warn('원본 파일 보관 예외:', se); thisFilePath = null; }
      }

      // 2. 보도자료 MD 파일: ## YYMMDD 기준으로 보도자료별 청킹
      var allRows = [];
      if (_pdfUploadCtx === 'press' && ext === 'md') {
        // ## 로 시작하는 섹션 분리
        var sections = text.split(/(?=^## )/m).filter(function(s){ return s.trim().length > 0; });
        if (sections.length === 0) sections = [text];
        for (var si = 0; si < sections.length; si++) {
          var sec = sections[si].trim();
          var secChunks = _chunkText(sec);
          for (var ci = 0; ci < secChunks.length; ci++) {
            allRows.push({
              doc_name: thisDocName,
              doc_category: category,
              chunk_index: allRows.length,
              content: secChunks[ci],
              file_path: thisFilePath
            });
          }
        }
      } else {
        // 3. 일반 청킹
        _setPdfProgress(
          Math.round(fileProgress * 80 + 15),
          '(' + (fi+1) + '/' + totalFiles + ') 텍스트 청킹 중...'
        );
        var chunks = _chunkText(text);
        if (chunks.length === 0) throw new Error(file.name + ': 청킹 결과가 없습니다.');
        // 업로드 파일은 '승인 대기'(is_approved=false)로 저장 → 설정에서 승인해야 AI가 참조.
        // (보도자료는 별도 흐름이라 승인 게이트 제외)
        var approvedFlag = (_pdfUploadCtx === 'press');
        allRows = chunks.map(function(c, i) {
          return { doc_name: thisDocName, doc_category: category, chunk_index: i, content: c, file_path: thisFilePath, is_approved: approvedFlag };
        });
      }

      // 4. 기존 동일 문서명 청크 삭제
      _setPdfProgress(
        Math.round(fileProgress * 80 + 20),
        '(' + (fi+1) + '/' + totalFiles + ') 기존 데이터 정리 중...'
      );
      // RLS로 프런트 직접 delete가 막혀 조용히 0건 처리된다 — 그대로 두면 같은 이름으로
      // 재업로드할 때 옛 청크가 남아 중복 누적된다. 관리자 RPC로 지운다. (#48)
      // 비밀번호가 없으면(취소) 정리를 건너뛰되, 중복 위험을 알린다.
      var _cleanPwd = _ensureAdminPwd();
      if (_cleanPwd) {
        var _del = await sb.rpc('admin_delete_kb_document', { p_doc_name: thisDocName, p_pwd: _cleanPwd });
        if (_del.error) console.warn('기존 청크 정리 실패(중복 누적 가능):', _del.error.message);
      } else {
        console.warn('기존 청크 정리 건너뜀 — 같은 문서명이 이미 있으면 청크가 중복될 수 있습니다.');
      }

      // 5. 청크 배치 삽입 (50개씩)
      var BATCH = 50;
      for (var i = 0; i < allRows.length; i += BATCH) {
        await sb.from('document_chunks').insert(allRows.slice(i, i + BATCH));
        _setPdfProgress(
          Math.round((fileProgress + (i + BATCH) / allRows.length / totalFiles) * 80 + 10),
          '(' + (fi+1) + '/' + totalFiles + ') 업로드 중... (' + Math.min(i + BATCH, allRows.length) + '/' + allRows.length + '개 청크)'
        );
      }
      totalChunks += allRows.length;

      // 6. 보도자료면 메모리 pressData에도 추가 → 목록 즉시 반영
      if (_pdfUploadCtx === 'press') {
        if (!pressData) pressData = [];
        pressData.unshift({
          id: 'upload_' + Date.now() + '_' + fi,
          title: thisDocName,
          date: pressDate,
          doc_name: thisDocName,
          agency: pressAgencyOf(thisDocName),
          content: text.slice(0, 3000)
        });
      }

      // 7. ITU-R이면 화면 목록에 추가
      //    법령·고시('law')는 업로드 진입점을 없앴다 — API(law_sync.py)가 조문 구조를
      //    그대로 가져와 PDF 추출보다 정확하기 때문. 여기 'law' 분기도 함께 정리. (#52)
      if (_pdfUploadCtx === 'itu') {
        var listEl = document.getElementById('itu-upload-list');
        if (listEl) {
          var item = document.createElement('div');
          item.className = 'card';
          item.style.cssText = 'cursor:default;margin-bottom:10px';
          item.innerHTML = '<div class="file-item">' +
            '<div class="file-icon fi-purple"><i class="ti ti-file-upload"></i></div>' +
            '<div style="flex:1"><div class="file-name">' + thisDocName + '</div>' +
            '<div class="file-size">' + category + ' · 직접 업로드 · ' + allRows.length + '개 청크</div></div>' +
            '<span class="badge badge-teal">최신</span>' +
            '</div>';
          listEl.appendChild(item);
        }
      }
    } // end for files

    // 보도자료 목록 갱신
    if (_pdfUploadCtx === 'press') {
      renderPressList(null);
    }

    _setPdfProgress(100, '완료!');
    setTimeout(function() {
      closePdfUpload();
      var pendingNote = (_pdfUploadCtx === 'press')
        ? ''
        : '\n\n⏳ 승인 대기 상태로 등록되었습니다. 설정 → 승인 대기 문서에서 승인하면 AI 자문 반영 + 의미검색 임베딩까지 자동 생성됩니다.';
      var msg = totalFiles === 1
        ? '✅ "' + (docName || files[0].name.replace(/\.[^.]+$/, '')) + '" 업로드 완료!\n' + totalChunks + '개 청크가 등록되었습니다.' + pendingNote
        : '✅ ' + totalFiles + '개 파일 업로드 완료!\n총 ' + totalChunks + '개 청크가 등록되었습니다.' + pendingNote;
      alert(msg);
    }, 400);

  } catch(e) {
    alert('업로드 실패: ' + (e.message || e));
    btn.disabled = false;
    btn.innerHTML = '<i class="ti ti-upload"></i> 업로드';
    prog.style.display = 'none';
  }
}

// ════════════════════════════════════════════
//  국회 법안 모니터링
// ════════════════════════════════════════════
let assemblyBillsCache = null;
let assemblyFilterMode = '전체';
var _asmDiffCache = null;   // law_diffs 경량 캐시(law_name/diff_kind/origin/new_doc) — '조문 DIFF 보기' 링크 판정용

async function loadAssemblyBills(forceRefresh) {
  if (!sb) return;
  var listEl = document.getElementById('assembly-list');
  if (!listEl) return;

  if (!assemblyBillsCache || forceRefresh) {
    listEl.innerHTML = '<div style="color:var(--text-secondary);padding:20px;text-align:center;font-size:12px">불러오는 중...</div>';
    try {
      var results = await Promise.all([
        sb.from('assembly_bills')
          .select('*')
          .eq('age', 22)
          .order('updated_at', { ascending: false }),
        // 경량 병행 조회 — 실패해도 법안 목록 자체는 뜨도록 에러는 무시하고 링크만 생략
        sb.from('law_diffs').select('law_name,diff_kind,origin,new_doc').limit(200)
      ]);
      if (results[0].error) throw results[0].error;
      assemblyBillsCache = results[0].data || [];
      if (!results[1].error) _asmDiffCache = results[1].data || [];
    } catch(e) {
      listEl.innerHTML = '<div style="color:#f66;padding:20px;text-align:center;font-size:12px">불러오기 실패: ' + e.message + '</div>';
      return;
    }
  }
  renderAssemblyBills(assemblyBillsCache);
}

// 의견등록 가능 판정 — notice_end_dt(YYYY-MM-DD)가 오늘(KST) 이후. 통계 계산부와
// assemblyMatchesFilter 양쪽에서 같은 함수를 써 판정이 갈리지 않게 한다.
function _billCommentOpen(b) {
  return !!(b && b.notice_end_dt && String(b.notice_end_dt).slice(0, 10) >= _todayKstStr());
}

// 법령명 비교용 정규화 — 공백·가운뎃점 제거
function _normLawName(s) { return String(s || '').replace(/[\s·]/g, ''); }

// '전파법 일부개정법률안' → '전파법' (정규화 후). 매칭 실패 시 null.
function _billToLawName(billName) {
  var m = String(billName || '').match(/([가-힣0-9·\s]+?(?:법률|시행령|시행규칙|규정|규칙|고시|법))\s*(?:일부|전부)?\s*개정(?:법률)?\s*안/);
  return m ? _normLawName(m[1]) : null;
}

// 통과 판정 — assemblyStatusLabel/통계와 같은 기준(가결·본회의 통과·공포·정부이송)
function _billIsPassed(p) {
  p = p || '';
  return p.includes('가결') || p === '본회의 통과' || p === '공포' || p === '정부이송';
}

// 이 법안 카드에 '조문 DIFF 보기' 링크를 붙일 수 있는가 — _asmDiffCache 기준
// (a) 의견등록 법안: origin='assembly' proposed & new_doc==bill_no
// (b) 통과 법안: 법안명→법령명 추출 후 pending/promoted law_name 매칭
function _billDiffLink(b) {
  if (!_asmDiffCache || !_asmDiffCache.length || !b) return null;
  var i, d;
  if (_billCommentOpen(b) && b.bill_no) {
    var billNo = String(b.bill_no);
    for (i = 0; i < _asmDiffCache.length; i++) {
      d = _asmDiffCache[i];
      if (d.origin === 'assembly' && d.diff_kind === 'proposed' && String(d.new_doc || '') === billNo)
        return { type: 'bill', key: billNo };
    }
  }
  if (_billIsPassed(b.proc_result)) {
    var ln = _billToLawName(b.bill_name);
    if (ln) {
      for (i = 0; i < _asmDiffCache.length; i++) {
        d = _asmDiffCache[i];
        if ((d.diff_kind === 'pending' || d.diff_kind === 'promoted') && _normLawName(d.law_name) === ln)
          return { type: 'law', key: ln };
      }
    }
  }
  return null;
}

// 법안 카드 → 법령 DIFF 상세로 딥링크. go('diff')가 _lawDiffsLoadPromise를 잡아두므로
// 로드 완료를 기다렸다가 정렬된 _lawDiffsCache에서 인덱스를 찾아 연다(실패 시 목록만 표시).
async function openDiffFromAssembly(type, key) {
  go('diff', null);
  try { if (_lawDiffsLoadPromise) await _lawDiffsLoadPromise; } catch (e) {}
  var rows = _lawDiffsCache || [];
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    if (type === 'bill') {
      if (r.origin === 'assembly' && r.diff_kind === 'proposed' && String(r.new_doc || '') === key) { openLawDiff(i); return; }
    } else {
      if ((r.diff_kind === 'pending' || r.diff_kind === 'promoted') && _normLawName(r.law_name) === key) { openLawDiff(i); return; }
    }
  }
}

function filterAssembly(el, mode) {
  assemblyFilterMode = mode;
  if (assemblyBillsCache) renderAssemblyBills(assemblyBillsCache);
}

function _parseProposeDt(s) {
  if (!s) return null;
  if (s.length === 8) s = s.slice(0,4) + '-' + s.slice(4,6) + '-' + s.slice(6);
  var d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

function assemblyStatusLabel(proc) {
  if (!proc || proc === '접수') return { text: '접수', color: '#6b7280' };
  if (proc.includes('가결') || proc === '본회의 통과' || proc === '공포' || proc === '정부이송') return { text: proc, color: '#22c55e' };
  if (proc.includes('폐기') || proc === '부결' || proc === '철회') return { text: proc, color: '#ef4444' };
  if (proc.includes('소관위')) return { text: proc, color: '#3b82f6' };
  if (proc.includes('법사위')) return { text: proc, color: '#8b5cf6' };
  if (proc.includes('본회의')) return { text: proc, color: '#f59e0b' };
  return { text: proc, color: '#6b7280' };
}

function assemblyMatchesFilter(bill) {
  var p = bill.proc_result || '접수';
  if (assemblyFilterMode === '전체') return true;
  if (assemblyFilterMode === '최근') { var d = _parseProposeDt(bill.propose_dt); return !!d && d >= new Date(Date.now() - 7 * 86400000); }
  if (assemblyFilterMode === '의견') return _billCommentOpen(bill);
  if (assemblyFilterMode === '접수') return !bill.proc_result || p === '접수';
  if (assemblyFilterMode === '통과') return p.includes('가결') || p === '본회의 통과' || p === '공포' || p === '정부이송';
  if (assemblyFilterMode === '폐기') return p.includes('폐기') || p === '부결' || p === '철회';
  return true;
}

function renderAssemblyBills(bills) {
  var listEl = document.getElementById('assembly-list');
  if (!listEl) return;

  // 통계
  var now = new Date();
  var weekAgo = new Date(now - 7 * 86400000);
  var totalCount   = bills.length;
  var newCount     = bills.filter(function(b) { var d = _parseProposeDt(b.propose_dt); return d && d >= weekAgo; }).length;
  var commentCount = bills.filter(function(b) { return _billCommentOpen(b); }).length;   // assemblyMatchesFilter('의견')와 동일 판정
  var activeCount  = bills.filter(function(b) { var p = b.proc_result || ''; return !p || p === '접수'; }).length;
  var passedCount  = bills.filter(function(b) { var p = b.proc_result || ''; return p.includes('가결') || p === '본회의 통과' || p === '공포' || p === '정부이송'; }).length;
  var discardedCount = bills.filter(function(b) { var p = b.proc_result || ''; return p.includes('폐기') || p === '부결' || p === '철회'; }).length;

  var setVal = function(id, v) { var el = document.getElementById(id); if (el) el.textContent = v; };
  setVal('asm-total',  totalCount);
  setVal('asm-new',    newCount);
  setVal('asm-comment', commentCount);
  setVal('asm-active', activeCount);
  setVal('asm-passed', passedCount);
  setVal('asm-discarded', discardedCount);

  // 선택된 카드 강조 (필터 버튼 줄 제거 → 카드가 필터 겸용)
  document.querySelectorAll('#assembly-stats .stat-card').forEach(function(c) {
    var on = c.getAttribute('data-mode') === assemblyFilterMode;
    c.style.outline = on ? '2px solid var(--accent)' : '';
    c.style.outlineOffset = on ? '-2px' : '';
  });

  var filtered = bills.filter(assemblyMatchesFilter).slice().sort(function(a, b) {
    // 의견등록 가능 행은 최상단 — 그 이후는 기존 발의일 최신순 유지
    var ca = _billCommentOpen(a) ? 1 : 0, cb = _billCommentOpen(b) ? 1 : 0;
    if (ca !== cb) return cb - ca;
    var da = _parseProposeDt(a.propose_dt), db = _parseProposeDt(b.propose_dt);
    return (db ? db.getTime() : 0) - (da ? da.getTime() : 0);
  });

  if (filtered.length === 0) {
    listEl.innerHTML = '<div style="color:var(--text-secondary);padding:24px;text-align:center;font-size:12px">해당하는 법안이 없습니다</div>';
    return;
  }

  var html = '<div class="card" style="cursor:default;padding:0;overflow:hidden">';
  filtered.forEach(function(b, i) {
    var sl = assemblyStatusLabel(b.proc_result);
    var kws = (b.matched_keywords || []).slice(0, 3).join(', ');
    var proposeDt = b.propose_dt
      ? (b.propose_dt.length === 8
          ? b.propose_dt.slice(0,4) + '.' + b.propose_dt.slice(4,6) + '.' + b.propose_dt.slice(6)
          : b.propose_dt)
      : '—';
    var isNew = (function() { var d = _parseProposeDt(b.propose_dt); return d && d >= weekAgo; })();
    var borderTop = i === 0 ? '' : 'border-top:1px solid var(--border);';
    // 열린국회정보 API가 LINK_URL을 안 주는 경우 bill_id로 의안정보시스템 상세 URL 구성
    var linkUrl = b.link_url || (b.bill_id ? 'https://likms.assembly.go.kr/bill/billDetail.do?billId=' + encodeURIComponent(b.bill_id) : '');
    var link = linkUrl
      ? '<a href="' + escHtml(linkUrl) + '" target="_blank" rel="noopener" onclick="event.stopPropagation()" style="color:var(--accent);font-size:11px;text-decoration:none;white-space:nowrap"><i class="ti ti-external-link" style="font-size:11px"></i> 의안보기</a>'
      : '';

    // 의견등록 가능 pill — proposed 배지 색 관례(rgba 빨강 배경). notice_url 있으면 새창 링크.
    var commentPill = '';
    if (_billCommentOpen(b)) {
      var endStr = String(b.notice_end_dt).slice(0, 10);
      var dRemain = Math.round((new Date(endStr + 'T00:00:00Z').getTime() - new Date(_todayKstStr() + 'T00:00:00Z').getTime()) / 86400000);
      var pillTxt = '🗳️ 의견등록 ~' + endStr.slice(5) + ' · D-' + dRemain;
      var pillStyle = 'font-size:10px;background:rgba(239,68,68,.12);color:#dc2626;padding:1px 7px;border-radius:99px;flex-shrink:0;font-weight:700;white-space:nowrap';
      commentPill = b.notice_url
        ? '<a href="' + escHtml(b.notice_url) + '" target="_blank" rel="noopener" onclick="event.stopPropagation()" style="' + pillStyle + ';text-decoration:none">' + pillTxt + '</a>'
        : '<span style="' + pillStyle + '">' + pillTxt + '</span>';
    }

    // 조문 DIFF 보기 — 카드 onclick(의안 새창)과 충돌하지 않게 stopPropagation
    var dl = _billDiffLink(b);
    var diffLink = dl
      ? '<a href="javascript:void(0)" onclick="event.stopPropagation();openDiffFromAssembly(\'' + dl.type + '\',\'' + String(dl.key).replace(/['"\\]/g, '') + '\')" style="color:#dc2626;font-size:11px;text-decoration:none;white-space:nowrap"><i class="ti ti-arrows-diff" style="font-size:11px"></i> 조문 DIFF 보기</a>'
      : '';

    html += '<div style="' + borderTop + 'padding:12px 14px' + (linkUrl ? ';cursor:pointer' : '') + '"'
      + (linkUrl ? ' onclick="window.open(\'' + escHtml(linkUrl) + '\',\'_blank\',\'noopener\')"' : '')
      + '>'
      + '<div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:4px">'
      + '<span style="flex:1;font-size:12px;font-weight:600;color:var(--text-primary);line-height:1.4">' + escHtml(b.bill_name) + '</span>'
      + commentPill
      + (isNew ? '<span style="font-size:10px;background:#dcfce7;color:#16a34a;padding:1px 6px;border-radius:99px;flex-shrink:0">신규</span>' : '')
      + '</div>'
      + '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">'
      + '<span style="font-size:10px;color:var(--text-muted)">' + escHtml(b.proposer || '—') + '</span>'
      + '<span style="font-size:10px;color:var(--text-muted)">|</span>'
      + '<span style="font-size:10px;color:var(--text-muted)">' + escHtml(b.committee || '—') + '</span>'
      + '<span style="font-size:10px;color:var(--text-muted)">|</span>'
      + '<span style="font-size:10px;color:var(--text-muted)">발의 ' + proposeDt + '</span>'
      + '<span style="margin-left:auto;font-size:10px;font-weight:600;color:' + sl.color + '">' + escHtml(sl.text) + '</span>'
      + '</div>'
      + (b.summary ? '<div style="font-size:11px;color:var(--text-secondary);line-height:1.45;margin:6px 0 0">' + escHtml(b.summary) + '</div>' : '')
      + (kws ? '<div style="margin-top:4px;font-size:10px;color:var(--text-muted)">키워드: ' + escHtml(kws) + '</div>' : '')
      + ((link || diffLink) ? '<div style="margin-top:4px;display:flex;gap:12px;align-items:center">' + link + diffLink + '</div>' : '')
      + '</div>';
  });
  html += '</div>';

  html += '<div style="font-size:11px;color:var(--text-muted);margin-top:8px;text-align:right">'
    + filtered.length + '건 표시 (전체 ' + totalCount + '건)</div>';

  listEl.innerHTML = html;
}

function escHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// 외부·DB 유래 URL을 href 속성에 넣기 전 정화 — http/https만 허용('javascript:' 등 스킴 차단) + HTML 이스케이프
function safeUrl(u) {
  var s = String(u == null ? '' : u).trim();
  return /^https?:\/\//i.test(s) ? escHtml(s) : '';
}

// ════════════════════════════════════════════
//  과방위 회의록 — document_chunks doc_category='회의록' (2026-08-02)
//  doc_name='과방위_회의록_{YYYY}.md', 섹션 '## YYMMDD 제N차 (안건)' 형식.
// ════════════════════════════════════════════
var _assemblyMinutesCache = null;

// 해외 규제동향 — 독립 메뉴 (news_feed category='해외', 2026-08-02 #54)
var _overseasCache = null;
async function loadOverseasNews(force) {
  var el = document.getElementById('overseas-list');
  if (!el || !sb) return;
  if (!_overseasCache || force) {
    el.innerHTML = '<div style="color:var(--text-secondary);padding:20px;text-align:center;font-size:12px">로딩 중...</div>';
    try {
      var resp = await sb.from('news_feed')
        .select('title, source, url, summary, published_at')
        .eq('category', '해외')
        .order('published_at', { ascending: false })
        .limit(100);
      if (resp.error) throw resp.error;
      _overseasCache = resp.data || [];
    } catch (e) {
      el.innerHTML = '<div style="color:#f66;padding:20px;text-align:center;font-size:12px">불러오기 실패: ' + escHtml((e && e.message) || String(e)) + '</div>';
      return;
    }
  }
  var rows = _overseasCache;
  if (rows.length === 0) {
    el.innerHTML = '<div style="color:var(--text-secondary);padding:20px;text-align:center;font-size:12px">수집된 해외 동향이 없습니다 (매일 05:30 수집)</div>';
    return;
  }
  var SRC_COLOR = { FCC: '#2563eb', Ofcom: '#7c3aed', BEREC: '#0891b2', '日총무성': '#dc2626', ITU: '#16a34a' };
  el.innerHTML = rows.map(function(n) {
    var c = SRC_COLOR[n.source] || 'var(--text-muted)';
    return '<div class="card" style="cursor:default;padding:12px 14px;margin-bottom:8px">' +
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap">' +
        '<span style="font-size:10px;font-weight:700;color:' + c + ';border:1px solid ' + c + ';padding:0 6px;border-radius:4px;white-space:nowrap">' + escHtml(n.source || '') + '</span>' +
        '<span style="font-size:10px;color:var(--text-muted)">' + escHtml(String(n.published_at || '').slice(0, 10)) + '</span>' +
        (n.url ? '<a href="' + escHtml(n.url) + '" target="_blank" rel="noopener" style="margin-left:auto;font-size:10px;text-decoration:none">원문 <i class="ti ti-external-link"></i></a>' : '') +
      '</div>' +
      '<div style="font-size:12px;font-weight:600;color:var(--text-primary);line-height:1.5;margin-bottom:4px">' + escHtml(n.title || '') + '</div>' +
      (n.summary ? '<div style="font-size:11px;color:var(--text-secondary);line-height:1.6">' + escHtml(n.summary) + '</div>' : '') +
    '</div>';
  }).join('');
}

async function loadAssemblyMinutes(force) {
  var listEl = document.getElementById('assembly-minutes-list');
  if (!listEl || !sb) return;

  if (!_assemblyMinutesCache || force) {
    listEl.innerHTML = '<div style="color:var(--text-secondary);padding:12px;text-align:center;font-size:12px">불러오는 중...</div>';
    try {
      // 회의록 전체 청크를 문서별로 이어붙여 섹션 단위 파싱 (order+range 페이징 — 1,000행 컷 #53).
      // 헤더-청크만 읽으면 '요약:' 줄이 다음 청크에 걸릴 때 놓치므로 전체를 읽는다(문서가 작아 부담 없음).
      var chunks = [];
      var pageStart = 0;
      while (true) {
        var resp = await sb.from('document_chunks')
          .select('doc_name, chunk_index, content')
          .eq('doc_category', '회의록')
          .order('doc_name').order('chunk_index')
          .range(pageStart, pageStart + 999);
        if (resp.error) throw resp.error;
        chunks = chunks.concat(resp.data || []);
        if (!resp.data || resp.data.length < 1000) break;
        pageStart += 1000;
      }
      var docsMap = {};
      chunks.forEach(function(c) { (docsMap[c.doc_name] = docsMap[c.doc_name] || []).push(c); });
      var minutes = [];
      Object.keys(docsMap).forEach(function(dn) {
        var full = docsMap[dn]
          .sort(function(a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); })
          .map(function(c) { return c.content || ''; }).join('');
        full.split(/(?=^## \d{6} )/m).forEach(function(s) {
          var m = s.match(/^## (\d{6}) (.+)/);
          if (!m) return;
          var sm = s.slice(0, 900).match(/^요약:\s*(.+)$/m);
          // 구버전 수집분의 '# 요약' 접두 중복 표시 방어 (데이터는 소급 작업이 정리, #54)
          var smText = sm ? sm[1].replace(/^[#\s]*(요약\s*[:：]?\s*)+/, '').trim() : '';
          minutes.push({
            title: m[2].trim(),
            date: '20' + m[1].slice(0, 2) + '-' + m[1].slice(2, 4) + '-' + m[1].slice(4, 6),
            doc_name: dn,
            summary: smText
          });
        });
      });
      minutes.sort(function(a, b) { return b.date.localeCompare(a.date); });
      _assemblyMinutesCache = minutes;
    } catch (e) {
      listEl.innerHTML = '<div style="color:#f66;padding:12px;text-align:center;font-size:12px">회의록 불러오기 실패: ' + escHtml((e && e.message) || String(e)) + '</div>';
      return;
    }
  }

  var minutes = _assemblyMinutesCache;
  if (minutes.length === 0) {
    listEl.innerHTML = '<div style="color:var(--text-secondary);padding:12px;text-align:center;font-size:12px">수집된 회의록이 없습니다(수집기 가동 후 표시)</div>';
    return;
  }

  var html = '<div class="card" style="cursor:default;padding:0;overflow:hidden">';
  minutes.forEach(function(mt, i) {
    html += '<div style="' + (i ? 'border-top:1px solid var(--border);' : '') + 'padding:10px 14px;cursor:pointer" onclick="openAssemblyMinute(' + i + ')">' +
      '<div style="display:flex;gap:10px;align-items:baseline">' +
        '<span style="font-size:11px;color:var(--text-muted);white-space:nowrap">' + mt.date + '</span>' +
        '<span style="font-size:12px;color:var(--text-primary);line-height:1.4">' + escHtml(mt.title) + '</span>' +
      '</div>' +
      (mt.summary
        ? '<div style="font-size:11px;color:var(--text-secondary);line-height:1.5;margin:4px 0 0 76px">' +
            '<span style="font-size:10px;font-weight:700;color:var(--accent-purple);background:rgba(139,92,246,.1);padding:0 5px;border-radius:3px;margin-right:6px">요약</span>' +
            escHtml(mt.summary) +
          '</div>'
        : '') +
    '</div>';
  });
  html += '</div>';
  listEl.innerHTML = html;
}

function openAssemblyMinute(idx) {
  var mt = _assemblyMinutesCache && _assemblyMinutesCache[idx];
  if (!mt) return;
  // 보도자료 상세 모달 재사용 — doc_name 기반 '## YYMMDD 제목' 섹션 조회라 회의록 형식과 동일
  openPressDetail(mt.title, mt.date, mt.doc_name);
}

// ════════════════════════════════════════════
//  입법예고·법령 개정 타임라인
// ════════════════════════════════════════════

var lawTrackCache = null;
var lawTrackFilterMode = '입법예고중';

async function loadLawTrack(forceRefresh) {
  if (!sb) return;
  var listEl = document.getElementById('lawtrack-list');
  if (!listEl) return;

  if (!lawTrackCache || forceRefresh) {
    listEl.innerHTML = '<div style="color:var(--text-secondary);padding:20px;text-align:center;font-size:12px">불러오는 중...</div>';
    try {
      var resp = await sb
        .from('law_amendments')
        .select('*')
        .order('updated_at', { ascending: false })
        .limit(500);
      if (resp.error) throw resp.error;
      lawTrackCache = resp.data || [];
    } catch(e) {
      listEl.innerHTML = '<div style="color:#f66;padding:20px;text-align:center;font-size:12px">불러오기 실패: ' + e.message + '</div>';
      return;
    }
  }
  renderLawTrack(lawTrackCache);
}

function filterLawTrack(el, mode) {
  lawTrackFilterMode = mode;
  if (lawTrackCache) renderLawTrack(lawTrackCache);
}

function lawTrackTypeLabel(law_type) {
  var map = { lsAnc:'입법예고', bylaw:'시행령', rules:'시행규칙', admrul:'고시' };
  var colors = { lsAnc:'#f59e0b', bylaw:'#3b82f6', rules:'#8b5cf6', admrul:'#6b7280' };
  return { text: map[law_type] || law_type, color: colors[law_type] || '#6b7280' };
}

function fmtLawDate(dt) {
  // YYYYMMDD → YYYY.MM.DD
  if (!dt) return null;
  dt = String(dt).replace(/-/g, '');
  if (dt.length === 8) return dt.slice(0,4) + '.' + dt.slice(4,6) + '.' + dt.slice(6);
  return dt;
}

function lawTrackDetailUrl(r) {
  var id = r.law_id || '', m;
  if ((m = id.match(/^admrul_(\d+)$/))) return 'https://www.law.go.kr/admRulInfoP.do?admRulSeq=' + m[1];
  if ((m = id.match(/^(?:law|bylaw|rules)_(\d+)$/))) return 'https://www.law.go.kr/lsInfoP.do?lsiSeq=' + m[1];
  return r.link_url || '';
}

function renderLawTrack(items) {
  var listEl = document.getElementById('lawtrack-list');
  if (!listEl) return;

  var now = new Date();
  var weekAgo = new Date(now - 7 * 86400000);
  var todayStr = now.toISOString().slice(0,10).replace(/-/g,'');

  var recent90Str = new Date(now - 90 * 86400000).toISOString().slice(0,10).replace(/-/g,'');
  var year1Str    = new Date(now - 365 * 86400000).toISOString().slice(0,10).replace(/-/g,'');
  var _d = function(v) { return String(v || '').replace(/\D/g, ''); };

  // ── 추적 대상 정비: 현행 중복 제거 + 최근 1년 변동분만 표시 ──
  //   · 입법예고(lsAnc)는 개별 유지, 그 외는 같은 법령명에서 공포일 최신 1건만(연혁 중복 제거)
  //   · 표시 대상 = 입법예고 OR 시행예정(미래 시행일) OR 최근 1년 내 공포·개정
  //   ※ 오래전 공포된 현행법(상시 참조용)은 지식베이스 '국내 법령·고시'에서 조회
  var _latest = {};
  (items || []).forEach(function(r) {
    if (r.law_type === 'lsAnc') { _latest['lsAnc::' + (r.law_id || r.law_nm)] = r; return; }
    var k = r.law_nm || r.law_id;
    if (!_latest[k] || _d(r.public_dt) > _d(_latest[k].public_dt)) _latest[k] = r;
  });
  var tracked = Object.keys(_latest).map(function(k) { return _latest[k]; }).filter(function(r) {
    if (r.law_type === 'lsAnc') return true;
    if (_d(r.enf_dt) >= todayStr) return true;          // 시행 예정
    return _d(r.public_dt) >= year1Str;                 // 최근 1년 공포·개정
  });

  function ltFilter(r) {
    if (lawTrackFilterMode === '전체') return true;
    if (lawTrackFilterMode === '입법예고중') return r.law_type === 'lsAnc';
    if (lawTrackFilterMode === '시행예정') return r.enf_dt && r.enf_dt.replace(/\D/g,'') >= todayStr;
    if (lawTrackFilterMode === '신규개정') return _d(r.public_dt) >= recent90Str || (r.prev_public_dt && r.prev_public_dt !== r.public_dt);
    return true;
  }
  var filtered = tracked.filter(ltFilter).slice().sort(function(a, b) {
    // 공포일 최신순(desc), 같거나 없으면 시행일로 보조 정렬
    var pa = _d(a.public_dt), pb = _d(b.public_dt);
    if (pa !== pb) return pb.localeCompare(pa);
    return _d(b.enf_dt).localeCompare(_d(a.enf_dt));
  });

  // 통계 (정비된 추적 대상 기준)
  var ancCount  = tracked.filter(function(r) { return r.law_type === 'lsAnc'; }).length;
  var newCount  = tracked.filter(function(r) { return _d(r.public_dt) >= recent90Str || (r.prev_public_dt && r.prev_public_dt !== r.public_dt); }).length;
  var enfCount  = tracked.filter(function(r) { return r.enf_dt && r.enf_dt.replace(/\D/g,'') >= todayStr; }).length;
  var setV = function(id, v) { var e = document.getElementById(id); if (e) e.textContent = v; };
  setV('lt-total', tracked.length);
  setV('lt-anc',   ancCount);
  setV('lt-new',   newCount);
  setV('lt-enf',   enfCount);

  // 선택된 카드 강조 (필터 버튼 줄 제거 → 카드가 필터 겸용)
  document.querySelectorAll('#lawtrack-stats .stat-card').forEach(function(c) {
    var on = c.getAttribute('data-mode') === lawTrackFilterMode;
    c.style.outline = on ? '2px solid var(--accent)' : '';
    c.style.outlineOffset = on ? '-2px' : '';
  });

  if (filtered.length === 0) {
    listEl.innerHTML = '<div style="color:var(--text-secondary);padding:24px;text-align:center;font-size:12px">해당 항목이 없습니다</div>';
    return;
  }

  var html = '';
  filtered.forEach(function(r) {
    var tl   = lawTrackTypeLabel(r.law_type);
    var kws  = (r.matched_keywords || []).slice(0,3).join(', ');
    var isNew = _d(r.public_dt) >= recent90Str;
    var pubDt = fmtLawDate(r.public_dt);
    var enfDt = fmtLawDate(r.enf_dt);
    var prevDt = fmtLawDate(r.prev_public_dt);
    var isUpdated = prevDt && prevDt !== pubDt;
    var _lturl = lawTrackDetailUrl(r);
    var link = _lturl
      ? '<a href="' + escHtml(_lturl) + '" target="_blank" rel="noopener" style="color:var(--accent);font-size:11px;text-decoration:none"><i class="ti ti-external-link" style="font-size:10px"></i> 상세보기</a>'
      : '';

    // 타임라인 스텝 생성
    // 입법예고(lsAnc): [입법예고 시작] → [의견마감] → [공포·시행 미정]
    //   ※ lsAnc는 enf_dt에 '의견 수렴 마감일'이 저장됨(공포·시행일은 입법예고 시점 미정)
    // 시행령/규칙/고시: [공포] → [시행]
    var steps = [];
    if (r.law_type === 'lsAnc') {
      steps.push({ label:'입법예고',   date: pubDt, done: !!pubDt, icon:'📢' });
      steps.push({ label:'의견마감',   date: enfDt, done: !!(enfDt && enfDt.replace(/\./g,'') <= todayStr), icon:'⏰' });
      steps.push({ label:'공포·시행', date: null,  done: false, icon:'📋' });
    } else {
      steps.push({ label:'공포',  date: pubDt, done: !!pubDt, icon:'📋' });
      steps.push({ label:'시행',  date: enfDt, done: enfDt && enfDt.replace(/\./g,'') <= todayStr, icon:'✅' });
    }

    // 타임라인 HTML
    var tlHtml = '<div style="display:flex;align-items:flex-start;gap:0;margin:10px 0 4px">';
    steps.forEach(function(step, idx) {
      var doneColor = step.done ? 'var(--accent)' : '#d1d5db';
      var dotBg     = step.done ? 'var(--accent)' : 'var(--bg-secondary)';
      var textColor = step.done ? 'var(--text-primary)' : 'var(--text-muted)';
      var connector = idx < steps.length - 1
        ? '<div style="flex:1;height:2px;background:' + doneColor + ';margin-top:7px;min-width:24px"></div>'
        : '';
      tlHtml += '<div style="display:flex;flex-direction:column;align-items:center;min-width:64px">'
        + '<div style="width:14px;height:14px;border-radius:50%;background:' + dotBg + ';border:2px solid ' + doneColor + ';display:flex;align-items:center;justify-content:center;font-size:8px">'
        + (step.done ? '<span style="color:#fff;font-size:8px">✓</span>' : '') + '</div>'
        + '<div style="font-size:10px;font-weight:600;color:' + textColor + ';margin-top:3px;text-align:center">' + step.label + '</div>'
        + '<div style="font-size:9px;color:var(--text-muted);text-align:center;line-height:1.3">' + (step.date || '—') + '</div>'
        + '</div>'
        + connector;
    });
    tlHtml += '</div>';

    html += '<div class="card" style="margin-bottom:10px;padding:12px 14px">'
      // 헤더
      + '<div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:2px">'
      + '<span style="flex:1;font-size:12px;font-weight:600;color:var(--text-primary);line-height:1.4">' + escHtml(r.law_nm) + '</span>'
      + (isNew ? '<span style="font-size:10px;background:#dcfce7;color:#16a34a;padding:1px 6px;border-radius:99px;flex-shrink:0">신규</span>' : '')
      + (isUpdated ? '<span style="font-size:10px;background:#fef3c7;color:#b45309;padding:1px 6px;border-radius:99px;flex-shrink:0">개정</span>' : '')
      + '</div>'
      // 메타
      + '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:2px">'
      + '<span style="font-size:10px;font-weight:600;color:' + tl.color + ';background:' + tl.color + '1a;padding:1px 7px;border-radius:99px">' + tl.text + '</span>'
      + (r.ann_type ? '<span style="font-size:10px;color:var(--text-muted)">' + escHtml(r.ann_type) + '</span>' : '')
      + (kws ? '<span style="font-size:10px;color:var(--text-muted)">키워드: ' + escHtml(kws) + '</span>' : '')
      + '</div>'
      // 개정이유 요약 (AI)
      + (r.summary ? '<div style="font-size:11px;color:var(--text-secondary);line-height:1.45;margin:2px 0 0">' + escHtml(r.summary) + '</div>' : '')
      // 타임라인
      + tlHtml
      // 개정 이력
      + (isUpdated ? '<div style="font-size:10px;color:#b45309;margin-top:2px">이전 공포: ' + prevDt + ' → ' + (pubDt || '—') + '</div>' : '')
      // 링크
      + (link ? '<div style="margin-top:6px">' + link + '</div>' : '')
      + '</div>';
  });

  html += '<div style="font-size:11px;color:var(--text-muted);margin-top:4px;text-align:right">'
    + filtered.length + '건 표시 (전체 ' + items.length + '건)</div>';

  listEl.innerHTML = html;
}

// ════════════════════════════════════════════
//  보고서 초안 제안 — 내 보고서(형식·톤) + RAG(내용) 결합
//  데이터: report_samples / report_style_rules / report_feedback (Supabase)
//  재사용: searchKeywords·buildRagContext·getQueryEmbedding·파서·callClaude SSE 패턴
// ════════════════════════════════════════════
var lastReportDraftText = '';
var lastReportDraftReq = '';
var lastReportDraftSources = [];
var lastReportFinal = '';       // 사용자가 채택·교정한 최종본 (편집-diff 학습용)
var _reportPickedFile = null;   // 등록 화면에서 선택한 파일(텍스트 추출 전)

// 탭 전환 (초안 생성 / 내 보고서 관리)
function switchReportTab(tab) {
  var genT = document.getElementById('report-tab-gen');
  var mngT = document.getElementById('report-tab-manage');
  var genB = document.getElementById('rtab-gen');
  var mngB = document.getElementById('rtab-manage');
  var isGen = (tab === 'gen');
  if (genT) genT.style.display = isGen ? 'block' : 'none';
  if (mngT) mngT.style.display = isGen ? 'none' : 'block';
  if (genB) { genB.classList.toggle('btn-primary', isGen); genB.classList.toggle('active', isGen); }
  if (mngB) { mngB.classList.toggle('btn-primary', !isGen); mngB.classList.toggle('active', !isGen); }
  if (!isGen) loadReportSamples();
}

// 보고서 샘플 1건 저장 (전문 보관, 청킹 안 함)
async function addReportSample(title, reportType, content, summary) {
  if (!sb) { alert('Supabase 연결이 필요합니다.'); return false; }
  var ins = await sb.from('report_samples').insert({
    title: title, report_type: reportType || null,
    content: content, summary: summary || null
  });
  if (ins.error) { alert('저장 실패: ' + ins.error.message); return false; }
  return true;
}

// 등록 화면: 파일 선택(클릭) → 공통 처리
async function onReportFileSelect(input) {
  var files = Array.from(input.files || []);
  if (files.length === 0) return;
  await _processReportFile(files[0]);
}

// 드래그앤드롭 핸들러
function handleReportFileDragOver(ev) {
  ev.preventDefault();
  var dz = document.getElementById('report-drop-zone');
  if (dz) dz.style.borderColor = 'var(--accent, #6366f1)';
}
function handleReportFileDragLeave(ev) {
  ev.preventDefault();
  var dz = document.getElementById('report-drop-zone');
  if (dz) dz.style.borderColor = 'var(--border-mid)';
}
async function handleReportFileDrop(ev) {
  ev.preventDefault();
  var dz = document.getElementById('report-drop-zone');
  if (dz) dz.style.borderColor = 'var(--border-mid)';
  var files = Array.from((ev.dataTransfer && ev.dataTransfer.files) || []);
  if (files.length === 0) return;
  await _processReportFile(files[0]);
}

// 파일 1건 → 텍스트 추출해 내용란 채움 (기존 파서 재사용 · 클릭/드롭 공용)
async function _processReportFile(file) {
  var ext = (file.name.split('.').pop() || '').toLowerCase();
  var labelEl = document.getElementById('report-file-label');
  if (labelEl) labelEl.textContent = file.name + ' 추출 중...';
  try {
    var text = '';
    if (ext === 'pdf') text = await _extractPdfText(file);
    else if (ext === 'md' || ext === 'txt') text = await _extractMdText(file);
    else if (ext === 'pptx') text = await _extractPptxText(file);
    else if (ext === 'docx') text = await _extractDocxText(file);
    else { alert('지원 형식: PDF · Word(docx) · PPTX · MD · TXT'); if (labelEl) labelEl.textContent=''; return; }
    if (!text || text.replace(/\s/g,'').length < 30) {
      alert('텍스트를 충분히 추출하지 못했습니다(스캔 PDF·빈 파일일 수 있음). 내용을 직접 붙여넣어 주세요.');
      if (labelEl) labelEl.textContent = '';
      return;
    }
    var contentEl = document.getElementById('report-sample-content');
    if (contentEl) contentEl.value = text;
    var titleEl = document.getElementById('report-sample-title');
    if (titleEl && !titleEl.value) titleEl.value = file.name.replace(/\.[^.]+$/, '').replace(/[_-]/g, ' ');
    if (labelEl) labelEl.textContent = file.name + ' · ' + text.length.toLocaleString() + '자 추출됨';
  } catch(e) {
    alert('파일 추출 실패: ' + (e.message || e));
    if (labelEl) labelEl.textContent = '';
  }
}

// 등록 버튼
async function onSaveReportSample() {
  var title = (document.getElementById('report-sample-title') || {}).value || '';
  var type = (document.getElementById('report-sample-type') || {}).value || '';
  var content = (document.getElementById('report-sample-content') || {}).value || '';
  var summary = (document.getElementById('report-sample-summary') || {}).value || '';
  title = title.trim(); content = content.trim(); summary = summary.trim();
  if (!title) { alert('제목을 입력하세요.'); return; }
  if (content.replace(/\s/g,'').length < 50) { alert('보고서 본문이 너무 짧습니다(형식 학습용 전문 필요).'); return; }
  var btn = document.getElementById('report-save-btn');
  if (btn) { btn.disabled = true; btn.textContent = '저장 중...'; }
  var ok = await addReportSample(title, type, content, summary);
  if (btn) { btn.disabled = false; btn.innerHTML = '<i class="ti ti-device-floppy"></i> 보고서 등록'; }
  if (ok) {
    ['report-sample-title','report-sample-content','report-sample-summary'].forEach(function(id){
      var el = document.getElementById(id); if (el) el.value='';
    });
    var labelEl = document.getElementById('report-file-label'); if (labelEl) labelEl.textContent='';
    var fi = document.getElementById('report-file-input'); if (fi) fi.value='';
    alert('✅ 보고서가 등록되었습니다.\n\n의미(시맨틱) 검색을 적용하려면 PC에서 다음을 1회 실행하세요:\n  python backfill_report_embeddings.py\n(실행 전에도 키워드·유형 필터로는 즉시 사용됩니다.)');
    loadReportSamples();
  }
}

async function onDeleteReportSample(id) {
  if (!confirm('이 보고서 샘플을 삭제할까요?')) return;
  var del = await sb.from('report_samples').delete().eq('id', id);
  if (del.error) { alert('삭제 실패: ' + del.error.message); return; }
  loadReportSamples();
}

// 등록된 보고서 목록 렌더 (+ 임베딩 대기 배지)
async function loadReportSamples() {
  var listEl = document.getElementById('report-sample-list');
  if (!listEl || !sb) return;
  listEl.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-secondary);font-size:12px">불러오는 중...</div>';
  var rows = (await sb.from('report_samples')
    .select('id,title,report_type,summary,created_at')
    .order('created_at', { ascending:false }).limit(100)).data || [];
  // 임베딩 대기(embedding NULL) id 집합
  var pend = (await sb.from('report_samples').select('id').is('embedding','null').limit(200)).data || [];
  var pendSet = new Set(pend.map(function(r){ return r.id; }));
  // 스타일 학습 상태 갱신
  refreshStyleStatus(rows.length);
  loadReportDirectives();   // 항상 적용 지시 목록도 함께
  if (rows.length === 0) {
    listEl.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-secondary);font-size:12px">등록된 보고서가 없습니다. 위에서 내 보고서를 등록하면 그 형식·톤으로 초안을 만들어 줍니다.</div>';
    return;
  }
  listEl.innerHTML = rows.map(function(r) {
    var pending = pendSet.has(r.id);
    var badge = pending
      ? '<span style="font-size:10px;background:#fef3c7;color:#b45309;padding:1px 7px;border-radius:99px">임베딩 대기</span>'
      : '<span style="font-size:10px;background:#dcfce7;color:#16a34a;padding:1px 7px;border-radius:99px">임베딩 완료</span>';
    var dt = (r.created_at || '').slice(0,10);
    return '<div class="card" style="margin-bottom:8px;cursor:default">'
      + '<div style="display:flex;align-items:flex-start;gap:8px">'
      + '<div style="flex:1">'
      + '<div style="font-size:12px;font-weight:600;color:var(--text-primary);line-height:1.4">' + escHtml(r.title) + '</div>'
      + '<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:3px">'
      + (r.report_type ? '<span style="font-size:10px;background:var(--bg-tertiary,#eef);color:var(--text-secondary);padding:1px 7px;border-radius:99px">' + escHtml(r.report_type) + '</span>' : '')
      + badge
      + '<span style="font-size:10px;color:var(--text-muted)">' + dt + '</span>'
      + '</div>'
      + (r.summary ? '<div style="font-size:11px;color:var(--text-secondary);margin-top:3px;line-height:1.45">' + escHtml(r.summary) + '</div>' : '')
      + '</div>'
      + '<button class="btn" style="font-size:11px;padding:3px 8px;flex-shrink:0" onclick="onDeleteReportSample(' + r.id + ')"><i class="ti ti-trash"></i></button>'
      + '</div></div>';
  }).join('');
}

function refreshStyleStatus(count) {
  var el = document.getElementById('report-style-status');
  if (!el) return;
  if (count < 2) {
    el.textContent = '보고서 2편 이상 등록하면 공통 형식을 학습합니다. (현재 ' + count + '편)';
  } else {
    el.textContent = '등록 ' + count + '편 · [스타일 재학습]으로 형식 규칙을 갱신할 수 있습니다.';
  }
}

// 스타일 가이드 증류 (Haiku) — 기준 예시 + 편집-diff(빨간펜) + 부정 피드백
//  재증류 트리거: 강제 / 규칙 없음 / 샘플 +2편 / 피드백 +2건 (피드백이 자동 학습 연료)
async function distillReportStyle(force) {
  if (!sb) return '';
  var saved = (await sb.from('report_style_rules').select('rules,sample_count,feedback_count').eq('id',1).maybeSingle()).data || {};
  var cnt = (await sb.from('report_samples').select('id', { count:'exact', head:true })).count || 0;
  var fbCount = (await sb.from('report_feedback').select('id', { count:'exact', head:true })).count || 0;
  if (cnt < 2) return saved.rules || '';   // 구조 학습엔 기본 샘플 2편 이상 필요
  var sampleDelta = cnt - (saved.sample_count || 0);
  var fbDelta = fbCount - (saved.feedback_count || 0);
  if (!force && saved.rules && sampleDelta < 2 && fbDelta < 2) return saved.rules;

  var samples = (await sb.from('report_samples').select('title,report_type,content')
    .order('created_at', { ascending:false }).limit(8)).data || [];
  var joined = samples.map(function(r,i){
    return '### 예시 ' + (i+1) + ' [' + (r.report_type||'기타') + '] ' + r.title + '\n' + (r.content||'').slice(0,2200);
  }).join('\n\n');

  // ── 빨간펜 학습: 최근 피드백(초안→최종본 차이 / 부정 평가) ──
  var fb = (await sb.from('report_feedback').select('request,draft,final,rating')
    .order('created_at', { ascending:false }).limit(12)).data || [];
  var corrections = fb.filter(function(f){ return f.final && f.final.trim(); }).slice(0,4);
  var negatives = fb.filter(function(f){ return f.rating === -1 && !(f.final && f.final.trim()); }).slice(0,3);
  var corrBlock = corrections.map(function(f,i){
    return '〔교정 ' + (i+1) + '〕 요청: ' + (f.request||'').slice(0,120) +
      '\n[AI 초안 발췌]\n' + (f.draft||'').slice(0,1200) +
      '\n[사용자 최종본 발췌]\n' + (f.final||'').slice(0,1200);
  }).join('\n\n');
  var negBlock = negatives.map(function(f,i){
    return '〔불만족 초안 ' + (i+1) + '〕 ' + (f.draft||'').slice(0,700);
  }).join('\n\n');

  var claudeKey = getConfig().claudeKey;
  if (!claudeKey) return saved.rules || '';
  var userMsg =
    '다음 자료로 "보고서 작성 규칙"을 만들어줘. 8~14줄, 지시문 형태로만 출력(설명 금지).\n\n' +
    '[A. 기준 예시 보고서 — 기본 구조·톤]\n' + (joined || '(없음)') +
    (corrBlock ? '\n\n[B. 사용자 교정 사례 — 초안을 사용자가 이렇게 고쳤음. 이 변화(구조 이동·표현 교체·길이·어미 등)를 규칙에 "반드시 반영"으로 명시]\n' + corrBlock : '') +
    (negBlock ? '\n\n[C. 사용자가 별로라고 평가한 초안 — 이런 패턴은 "피하라"로 명시]\n' + negBlock : '') +
    '\n\n항목: ① 전체 구조(섹션 순서/제목 방식) ② 문단·문장 톤(격식/길이/어미) ③ 자주 쓰는 표현·머리말 ④ 도입·결론 처리 ⑤ 위 교정에서 드러난 사용자 선호(최우선).';
  try {
    var res = await fetch('https://api.anthropic.com/v1/messages', {
      method:'POST',
      headers:{ 'x-api-key':claudeKey, 'anthropic-version':'2023-06-01', 'content-type':'application/json', 'anthropic-dangerous-direct-browser-access':'true' },
      body: JSON.stringify({
        model:'claude-haiku-4-5-20251001', max_tokens:800,
        system:'당신은 문서 편집 전문가입니다. 기준 예시의 공통 형식을 잡되, 사용자의 교정 사례(초안→최종본 차이)에서 드러난 선호를 최우선으로 반영해 재사용 가능한 작성 규칙으로 일반화합니다.',
        messages:[{ role:'user', content: userMsg }]
      })
    });
    if (!res.ok) return saved.rules || '';
    var data = await res.json();
    var rules = (data.content && data.content[0] && data.content[0].text) || '';
    if (rules) {
      await sb.from('report_style_rules').upsert({ id:1, rules:rules, sample_count:cnt, feedback_count:fbCount, updated_at:new Date().toISOString() });
    }
    return rules || saved.rules || '';
  } catch(e) { console.warn('스타일 증류 실패:', e); return saved.rules || ''; }
}

// 수동 "스타일 재학습" 버튼
async function onRelearnStyle() {
  var claudeKey = getConfig().claudeKey;
  if (!claudeKey) { alert('Claude API 키가 설정되지 않았습니다.'); return; }
  var btn = document.getElementById('report-relearn-btn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="ti ti-loader"></i> 학습 중...'; }
  var rules = await distillReportStyle(true);
  if (btn) { btn.disabled = false; btn.innerHTML = '<i class="ti ti-refresh"></i> 스타일 재학습'; }
  var box = document.getElementById('report-style-rules-box');
  if (box) {
    box.style.display = rules ? 'block' : 'none';
    box.textContent = rules || '';
  }
  if (!rules) alert('학습할 규칙을 생성하지 못했습니다. 보고서가 2편 이상인지 확인하세요.');
}

// 핵심: 초안 생성 (형식=내 보고서, 내용=RAG) — callClaude SSE 패턴 복제
//  opts.reviseInstruction: 기존 초안(opts.priorDraft)을 말로 수정하는 다회 대화 모드
async function callReportDraft(userText, reportType, onDelta, opts) {
  opts = opts || {};
  var claudeKey = getConfig().claudeKey;
  if (!claudeKey) throw new Error('Claude API 키가 설정되지 않았습니다.');

  // ① 형식: 스타일 가이드 + 유사 샘플 1~2편
  var styleRules = await distillReportStyle(false);
  var emb = await getQueryEmbedding(userText);
  var samples = [];
  if (emb) {
    samples = (await sb.rpc('match_report_samples',
      { query_embedding: emb, match_count: 2, filter_type: reportType || null })).data || [];
  }
  // 임베딩 없거나 결과 없으면 유형/최신순 폴백
  if (samples.length === 0) {
    var q = sb.from('report_samples').select('title,report_type,content').order('created_at',{ascending:false}).limit(2);
    if (reportType) q = q.eq('report_type', reportType);
    samples = (await q).data || [];
  }
  var sampleBlock = samples.map(function(s,i){
    return '[예시 보고서 ' + (i+1) + ' · ' + (s.report_type||'기타') + ' · ' + s.title + ']\n' + (s.content||'').slice(0,3000);
  }).join('\n\n---\n\n');

  // ② 내용: 기존 RAG(법령·고시·뉴스) 재사용
  var ragChunks = await searchKeywords(userText, false);
  var ragContext = buildRagContext(ragChunks);
  // 자문과 같은 시행예정 컨텍스트를 붙인다. 보고서는 임원 보고로 나가므로
  // "현행은 X"라고만 써 두면 시행이 임박한 개정을 빠뜨린 문서가 된다.
  var pendingContext = await buildPendingContext(ragChunks);
  // 보고서에 금액·요율이 들어갈 때 조문만 보고 쓰면 숫자가 빠진다 — 별표도 같이 붙인다
  var annexContext = await buildAnnexContext(ragChunks, userText);

  // 참고 출처 기록
  lastReportDraftSources = samples.map(function(s){ return '내 보고서: ' + s.title; })
    .concat((ragChunks||[]).map(function(c){ return c.doc_name; }))
    .concat((lastAnnexSources||[]).map(function(a){ return '별표: ' + a; }))
    .concat((lastPendingNotice||[]).map(function(p){
      var d = p.enf_date || '';
      return '시행예정: ' + p.law_name + ' ' + (d.length === 8 ? d.slice(2,4)+'.'+d.slice(4,6)+'.'+d.slice(6,8) : d);
    }));

  // ③ 시스템 프롬프트 조합
  var system =
    '당신은 사용자의 기존 보고서 스타일을 그대로 재현하는 전파·통신 정책 보고서 작성 도우미입니다.\n' +
    '아래 [예시 보고서]의 구조·톤·표현을 충실히 따르고, 내용 근거는 [법령·자료]에서 인용하세요.\n' +
    '확정 사실/해석/추정/의견을 구분하고, 단정 대신 검토의견 톤을 유지하세요. 법령 인용은 조항+핵심내용을 함께 적습니다.\n\n' +
    '[보고서 작성 규칙(내 스타일)]\n' + (styleRules || '(아직 학습된 규칙 없음 — 예시를 직접 모방)') +
    '\n\n[예시 보고서 — 형식·톤의 기준]\n' + (sampleBlock || '(등록된 예시 없음 — 표준 정책보고서 형식 사용)') +
    ragContext + annexContext + pendingContext;

  // 항상 적용할 사용자 지시(영구) 주입 — 최우선
  try {
    var directives = (await sb.from('report_directives').select('directive').order('created_at',{ascending:true})).data || [];
    if (directives.length) {
      system += '\n\n[항상 반영할 사용자 지시 — 최우선]\n' + directives.map(function(d,i){ return (i+1) + '. ' + d.directive; }).join('\n');
    }
  } catch(e) { /* 지시 없음 무시 */ }

  // 메시지: 신규 작성 vs 기존 초안 말로 수정(다회 대화)
  var messages;
  if (opts.reviseInstruction) {
    messages = [
      { role:'user', content: '다음 주제로 보고서 초안을 작성해줘:\n' + userText },
      { role:'assistant', content: opts.priorDraft || lastReportDraftText || '' },
      { role:'user', content: '위 초안을 아래 지시대로 수정해서, 전체 보고서를 완성본으로 다시 출력해줘(설명 없이 보고서 본문만):\n' + opts.reviseInstruction }
    ];
  } else {
    messages = [{ role:'user', content: '다음 주제로 보고서 초안을 작성해줘:\n' + userText }];
  }

  var res = await fetch('https://api.anthropic.com/v1/messages', {
    method:'POST',
    headers:{ 'x-api-key':claudeKey, 'anthropic-version':'2023-06-01', 'content-type':'application/json', 'anthropic-dangerous-direct-browser-access':'true' },
    body: JSON.stringify({
      model:'claude-sonnet-5', max_tokens:24000, stream:true,
      system: system,
      tools:[{ type:'web_search_20250305', name:'web_search', max_uses:3 }],
      messages: messages
    })
  });
  if (!res.ok) {
    var err = await res.json().catch(function(){ return {}; });
    throw new Error((err.error && err.error.message) || 'API 오류 (HTTP ' + res.status + ')');
  }

  // ── SSE 파싱 (callClaude와 동일 로직) ──
  var aiText = '';
  var cited = [];
  var seenUrl = new Set();
  function addCitation(c){ if (c && c.url && !seenUrl.has(c.url)) { seenUrl.add(c.url); cited.push({ url:c.url, title:c.title||c.url }); } }
  var reader = res.body.getReader();
  var decoder = new TextDecoder('utf-8');
  var buf = '';
  while (true) {
    var chunk = await reader.read();
    if (chunk.done) break;
    buf += decoder.decode(chunk.value, { stream:true });
    var events = buf.split(/\r?\n\r?\n/);
    buf = events.pop();
    for (var ei=0; ei<events.length; ei++) {
      var lines = events[ei].split(/\r?\n/);
      for (var li=0; li<lines.length; li++) {
        var line = lines[li];
        if (line.indexOf('data:') !== 0) continue;
        var payload = line.slice(5).trim();
        if (!payload || payload === '[DONE]') continue;
        var evt; try { evt = JSON.parse(payload); } catch(e) { continue; }
        if (evt.type === 'content_block_delta' && evt.delta) {
          if (evt.delta.type === 'text_delta' && evt.delta.text) {
            aiText += evt.delta.text;
            if (typeof onDelta === 'function') onDelta(aiText);
          } else if (evt.delta.type === 'citations_delta' && evt.delta.citation) {
            addCitation(evt.delta.citation);
          }
        } else if (evt.type === 'content_block_start' && evt.content_block) {
          (evt.content_block.citations || []).forEach(addCitation);
        } else if (evt.type === 'error') {
          throw new Error((evt.error && evt.error.message) || '스트리밍 오류');
        }
      }
    }
  }
  if (cited.length > 0) {
    cited.slice(0,5).forEach(function(c){ lastReportDraftSources.push(c.title); });
  }
  return aiText;
}

// 초안 생성 UI 오케스트레이션
async function onGenerateDraft() {
  var reqEl = document.getElementById('report-req-input');
  var typeEl = document.getElementById('report-gen-type');
  var outEl = document.getElementById('report-draft-output');
  var actionsEl = document.getElementById('report-draft-actions');
  var btn = document.getElementById('report-gen-btn');
  var userText = (reqEl && reqEl.value || '').trim();
  if (!userText) { alert('어떤 보고서를 만들지 입력하세요. 예: 주파수 재할당 관련 정책검토 보고서 초안 만들어줘'); return; }
  if (!getConfig().claudeKey) { alert('Claude API 키가 설정되지 않았습니다.'); return; }
  var reportType = (typeEl && typeEl.value) || '';
  if (reportType === '전체') reportType = '';
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="ti ti-loader"></i> 생성 중...'; }
  if (actionsEl) actionsEl.style.display = 'none';
  if (outEl) outEl.innerHTML = '<div style="color:var(--text-secondary);font-size:12px">내 보고서 형식 + 법령·자료를 결합해 초안을 작성 중입니다... (웹검색 포함 시 1~2분 소요, 실시간 표시)</div>';
  lastReportDraftReq = userText;
  lastReportDraftText = '';
  lastReportFinal = '';
  var editArea = document.getElementById('report-edit-area'); if (editArea) editArea.style.display = 'none';
  var promoBtn = document.getElementById('report-promote-btn'); if (promoBtn) promoBtn.style.display = 'none';
  var reviseRow = document.getElementById('report-revise-row'); if (reviseRow) reviseRow.style.display = 'none';
  var noteEl = document.getElementById('report-feedback-note'); if (noteEl) noteEl.textContent = '';
  try {
    var text = await callReportDraft(userText, reportType, function(partial){
      lastReportDraftText = partial;
      if (outEl) outEl.innerHTML = renderMd(partial);
    });
    lastReportDraftText = text;
    if (outEl) {
      var srcHtml = '';
      if (lastReportDraftSources.length > 0) {
        var uniq = lastReportDraftSources.filter(function(v,i,a){ return a.indexOf(v)===i; }).slice(0,10);
        srcHtml = '<div style="margin-top:14px;padding-top:10px;border-top:0.5px solid var(--border-light);font-size:11px;color:var(--text-muted)">참고: ' + uniq.map(escHtml).join(' · ') + '</div>';
      }
      outEl.innerHTML = renderMd(text) + srcHtml;
    }
    if (actionsEl) actionsEl.style.display = 'flex';
    if (reviseRow) reviseRow.style.display = 'flex';
  } catch(e) {
    if (outEl) outEl.innerHTML = '<div style="color:#dc2626;font-size:12px">생성 실패: ' + escHtml(e.message || String(e)) + '</div>';
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="ti ti-sparkles"></i> 초안 생성'; }
  }
}

// 말로 지시해서 고치기 — scope: 'once'(이번만) / 'always'(영구 지시 저장)
async function onReviseDraft(scope) {
  if (!lastReportDraftText) { alert('먼저 초안을 생성하세요.'); return; }
  var inp = document.getElementById('report-revise-input');
  var instruction = (inp && inp.value || '').trim();
  if (!instruction) { alert('어떻게 고칠지 입력하세요. 예: 결론을 앞으로 빼고 3문단으로 줄여줘'); return; }
  if (!getConfig().claudeKey) { alert('Claude API 키가 설정되지 않았습니다.'); return; }
  var outEl = document.getElementById('report-draft-output');
  var actionsEl = document.getElementById('report-draft-actions');
  var reviseRow = document.getElementById('report-revise-row');
  var onceBtn = document.getElementById('report-revise-once-btn');
  var alwaysBtn = document.getElementById('report-revise-always-btn');
  var note = document.getElementById('report-feedback-note');
  var reportType = ((document.getElementById('report-gen-type') || {}).value) || '';
  if (reportType === '전체') reportType = '';
  if (onceBtn) onceBtn.disabled = true;
  if (alwaysBtn) alwaysBtn.disabled = true;
  // '항상 적용'이면 영구 지시로 저장 (이후 모든 초안에 주입)
  if (scope === 'always') {
    try {
      await sb.from('report_directives').insert({ directive: instruction });
      if (note) note.textContent = '📌 "항상 적용" 지시로 저장됨 — 이후 모든 초안에 반영됩니다.';
      loadReportDirectives();
    } catch(e) { console.warn('지시 저장 실패:', e); }
  }
  var prior = lastReportDraftText;
  if (actionsEl) actionsEl.style.display = 'none';
  if (outEl) outEl.innerHTML = '<div style="color:var(--text-secondary);font-size:12px">지시대로 초안을 수정 중입니다... (실시간 표시)</div>';
  try {
    var text = await callReportDraft(lastReportDraftReq, reportType, function(partial){
      lastReportDraftText = partial;
      if (outEl) outEl.innerHTML = renderMd(partial);
    }, { reviseInstruction: instruction, priorDraft: prior });
    lastReportDraftText = text;
    if (outEl) {
      var srcHtml = '';
      if (lastReportDraftSources.length > 0) {
        var uniq = lastReportDraftSources.filter(function(v,i,a){ return a.indexOf(v)===i; }).slice(0,10);
        srcHtml = '<div style="margin-top:14px;padding-top:10px;border-top:0.5px solid var(--border-light);font-size:11px;color:var(--text-muted)">참고: ' + uniq.map(escHtml).join(' · ') + '</div>';
      }
      outEl.innerHTML = renderMd(text) + srcHtml;
    }
    if (inp) inp.value = '';
    if (actionsEl) actionsEl.style.display = 'flex';
    if (note && scope !== 'always') note.textContent = '✏️ 지시대로 수정했습니다. 이어서 더 고치거나 채택하세요.';
  } catch(e) {
    if (outEl) outEl.innerHTML = '<div style="color:#dc2626;font-size:12px">수정 실패: ' + escHtml(e.message || String(e)) + '</div>';
    if (actionsEl) actionsEl.style.display = 'flex';
  } finally {
    if (onceBtn) onceBtn.disabled = false;
    if (alwaysBtn) alwaysBtn.disabled = false;
  }
}

// 영구 지시 목록 렌더 / 삭제
async function loadReportDirectives() {
  var el = document.getElementById('report-directives-list');
  if (!el || !sb) return;
  var rows = (await sb.from('report_directives').select('id,directive,created_at')
    .order('created_at', { ascending:false }).limit(50)).data || [];
  if (rows.length === 0) { el.innerHTML = ''; return; }
  el.innerHTML = '<div style="font-size:11px;color:var(--text-secondary);margin:6px 0 4px">항상 적용 중인 지시 (' + rows.length + ')</div>' +
    rows.map(function(r){
      return '<div style="display:flex;align-items:center;gap:6px;padding:4px 8px;background:var(--bg-secondary);border:0.5px solid var(--border-light);border-radius:var(--radius-md);margin-bottom:4px">'
        + '<span style="flex:1;font-size:11px;color:var(--text-primary)">📌 ' + escHtml(r.directive) + '</span>'
        + '<button class="btn" style="font-size:10px;padding:2px 6px" onclick="onDeleteDirective(' + r.id + ')">삭제</button>'
        + '</div>';
    }).join('');
}
async function onDeleteDirective(id) {
  if (!sb) return;
  await sb.from('report_directives').delete().eq('id', id);
  loadReportDirectives();
}

// DOCX(간편) 내보내기 — HTML→Blob(.doc)
function exportReportDraftDoc() {
  if (!lastReportDraftText) { alert('먼저 초안을 생성하세요.'); return; }
  var bodyHtml = renderMd(lastReportDraftText);
  var html = '<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">'
    + '<head><meta charset="utf-8"><title>보고서 초안</title></head>'
    + '<body style="font-family:맑은 고딕,Malgun Gothic,sans-serif;font-size:11pt;line-height:1.7">'
    + bodyHtml + '</body></html>';
  var blob = new Blob(['﻿', html], { type:'application/msword' });
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  var fname = (lastReportDraftReq || '보고서초안').replace(/[\\/:*?"<>|]/g,'').slice(0,30);
  a.href = url; a.download = fname + '_초안.doc';
  document.body.appendChild(a); a.click();
  document.body.removeChild(a);
  setTimeout(function(){ URL.revokeObjectURL(url); }, 1000);
}

// 👍/👎 — 약한 신호. 임계 도달 시 자동 재증류에 반영됨
async function submitReportFeedback(rating) {
  if (!lastReportDraftText || !sb) return;
  await sb.from('report_feedback').insert({
    request: lastReportDraftReq, draft: lastReportDraftText, rating: rating
  });
  var fb = document.getElementById('report-feedback-note');
  if (fb) { fb.textContent = rating > 0 ? '👍 피드백 저장됨 — 감사합니다.' : '👎 피드백 저장됨 — 다음 초안 개선에 반영합니다.'; }
  // 부정 평가 등이 임계(+2건) 넘으면 자동 재학습
  try {
    var rules = await distillReportStyle(false);
    var box = document.getElementById('report-style-rules-box');
    if (box && rules && box.style.display === 'block') box.textContent = rules;
  } catch(e) { /* 자동 학습 실패는 조용히 무시 */ }
}

// ── v3 빨간펜 학습: 초안을 고쳐 "최종본 채택" → 초안↔최종본 차이를 학습 ──
function startEditDraft() {
  if (!lastReportDraftText) { alert('먼저 초안을 생성하세요.'); return; }
  var area = document.getElementById('report-edit-area');
  var ta = document.getElementById('report-final-input');
  if (ta) ta.value = lastReportDraftText;   // 초안 원문(마크다운 평문)을 그대로 편집
  if (area) area.style.display = 'block';
  var promo = document.getElementById('report-promote-btn'); if (promo) promo.style.display = 'none';
  if (ta) { ta.focus(); ta.scrollIntoView({ behavior:'smooth', block:'nearest' }); }
}

function cancelEditDraft() {
  var area = document.getElementById('report-edit-area');
  if (area) area.style.display = 'none';
}

async function saveReportFinal() {
  if (!sb) { alert('Supabase 연결이 필요합니다.'); return; }
  var ta = document.getElementById('report-final-input');
  var finalText = (ta && ta.value || '').trim();
  if (finalText.replace(/\s/g,'').length < 30) { alert('최종본 내용이 너무 짧습니다.'); return; }
  lastReportFinal = finalText;
  var btn = document.getElementById('report-final-save-btn');
  if (btn) { btn.disabled = true; btn.textContent = '저장 중...'; }
  await sb.from('report_feedback').insert({
    request: lastReportDraftReq, draft: lastReportDraftText, final: finalText, rating: 1
  });
  var note = document.getElementById('report-feedback-note');
  if (note) note.textContent = '✅ 최종본 저장됨 — 초안과의 차이를 학습합니다.';
  // 자동 재증류(임계 도달 시) + 스타일 박스 갱신
  try {
    var rules = await distillReportStyle(false);
    var box = document.getElementById('report-style-rules-box');
    if (box && rules) { box.style.display = 'block'; box.textContent = rules; }
  } catch(e) { console.warn('재학습 실패:', e); }
  if (btn) { btn.disabled = false; btn.innerHTML = '<i class="ti ti-check"></i> 최종본 채택'; }
  cancelEditDraft();
  var promo = document.getElementById('report-promote-btn'); if (promo) promo.style.display = 'inline-flex';
}

// 채택한 최종본을 예시 보고서(report_samples)로 승격 (선택)
async function promoteFinalToSample() {
  if (!lastReportFinal) { alert('먼저 최종본을 채택하세요.'); return; }
  var title = (lastReportDraftReq || '채택 보고서').replace(/\s+/g,' ').trim().slice(0,40);
  var type = ((document.getElementById('report-gen-type') || {}).value) || '';
  if (type === '전체') type = '';
  var ok = await addReportSample(title, type, lastReportFinal, '');
  if (ok) {
    var note = document.getElementById('report-feedback-note');
    if (note) note.textContent = '📌 예시 보고서로 추가됨 — PC에서 backfill_report_embeddings.py 실행 시 의미검색에 반영됩니다.';
    try { await distillReportStyle(false); } catch(e) { console.warn('보고서 스타일 재증류 실패(다음 등록 때 재시도됨):', e); }
    var promo = document.getElementById('report-promote-btn'); if (promo) promo.style.display = 'none';
  }
}

// ════════════════════════════════════════════
//  법령 관계도 (lawmap) — 주제↔법령 네트워크 그래프
//  데이터: law_graph_nodes / law_graph_edges (Supabase)
//  성장 경로: ①자문 자동 축적(<lawmap> 블록) ②탭 즉석 AI 생성 ③AI 보강 ④인용망 스크립트(build_law_citation_graph.py)
// ════════════════════════════════════════════
var LAWMAP_COLORS = { topic:'#5b7ff5', law:'#2ea060', decree:'#1f9e9e', rules:'#1f9e9e', notice:'#e08a3c', etc:'#d5486a' };
var LAWMAP_TYPE_LABEL = { topic:'주제', law:'법률', decree:'시행령', rules:'규칙·세칙', notice:'고시·행정규칙', etc:'기타·국제' };

let _lawMapLoaded = false;
let _lawMapNodes = [];
let _lawMapEdges = [];
let _lawMapNet = null;        // vis.Network 인스턴스
let _lawMapFocusId = null;    // 현재 포커스 노드(주제) id — null이면 전체 인용망
let _lawMapShowNotice = false; // 전체 뷰에서 고시·행정규칙 표시 여부 (기본 접힘 — 노드 과반이 고시라 조망 불가)
let _lawMapHiddenCount = 0;    // 접힌 고시 수 (토글 라벨용)
let _visNetLoadPromise = null;

function lmEsc(s) { return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function guessLawNodeType(name) {
  if (/시행령$/.test(name)) return 'decree';
  if (/(시행규칙|규칙|세칙)$/.test(name)) return 'rules';
  if (/(고시|공고|훈령|예규|지침|기준)/.test(name)) return 'notice';
  if (/법$/.test(name)) return 'law';
  return 'etc';
}

// vis-network 지연 로드 — lawmap 탭 첫 진입 시에만 CDN에서 1회 로드 (다른 탭 성능 무영향)
function loadVisNetwork() {
  if (window.vis && window.vis.Network) return Promise.resolve();
  if (_visNetLoadPromise) return _visNetLoadPromise;
  _visNetLoadPromise = new Promise(function(resolve, reject) {
    var s = document.createElement('script');
    s.src = 'https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js';
    s.onload = function() { resolve(); };
    s.onerror = function() { _visNetLoadPromise = null; reject(new Error('vis-network 로드 실패 — 네트워크 상태를 확인하세요')); };
    document.head.appendChild(s);
  });
  return _visNetLoadPromise;
}

function setLawMapStatus(html) {
  var el = document.getElementById('lawmap-status');
  if (el) el.innerHTML = html || '';
}

// 고시 접기 토글 — 전체 뷰에서만 노출. 숨긴 사실을 화면에 드러내 '정보가 없다'는 오해를 막는다. (배경역사 #36)
function updateLawMapNoticeToggle(isFullView) {
  var btn = document.getElementById('lawmap-notice-toggle');
  if (!btn) return;
  if (!isFullView) { btn.style.display = 'none'; return; }
  btn.style.display = 'inline-flex';
  if (_lawMapShowNotice) {
    btn.innerHTML = '<i class="ti ti-eye-off"></i> 고시 접기';
    btn.title = '고시·행정규칙을 접어 주제·법령 뼈대만 봅니다';
  } else {
    btn.innerHTML = '<i class="ti ti-eye"></i> 고시 ' + _lawMapHiddenCount + '개 펼치기';
    btn.title = '전체 조망을 위해 고시·행정규칙을 접어 두었습니다. 주제·법령을 클릭하면 접힌 고시도 그대로 보입니다.';
  }
}

function toggleLawMapNotice() {
  _lawMapShowNotice = !_lawMapShowNotice;
  renderLawMapGraph(null);
}

async function loadLawMap(force) {
  var el = document.getElementById('lawmap-graph');
  if (!el || !sb) return;
  if (_lawMapLoaded && !force) { return; }
  el.innerHTML = '<div style="color:var(--text-secondary);font-size:12px;padding:16px">불러오는 중...</div>';
  try {
    await loadVisNetwork();
    // 서버측 max-rows(1000행) 제한 회피 — 페이지네이션 전체 조회
    async function fetchAllRows(table, cols) {
      var all = [];
      for (var off = 0; off < 20000; off += 1000) {
        var resp = await sb.from(table).select(cols).range(off, off + 999);
        if (resp.error) throw resp.error;
        all = all.concat(resp.data || []);
        if ((resp.data || []).length < 1000) break;
      }
      return all;
    }
    var r = await Promise.all([
      fetchAllRows('law_graph_nodes', 'id,name,node_type,description,doc_name,source'),
      fetchAllRows('law_graph_edges', 'id,source_id,target_id,relation_type,description,source,weight')
    ]);
    _lawMapNodes = r[0];
    _lawMapEdges = r[1];
    _lawMapLoaded = true;
    fillLawMapTopicSelect();
    if (_lawMapNodes.length === 0) {
      el.innerHTML = '<div style="color:var(--text-secondary);font-size:12px;padding:16px">아직 관계 데이터가 없습니다. 위 질문창에 주제를 입력해 AI로 생성하거나, AI 자문을 이용하면 자동으로 쌓입니다.</div>';
      return;
    }
    // 기존 포커스가 새 데이터에도 있으면 유지, 없으면 전체 뷰
    if (_lawMapFocusId && !_lawMapNodes.some(function(n) { return n.id === _lawMapFocusId; })) _lawMapFocusId = null;
    renderLawMapGraph(_lawMapFocusId);
  } catch(e) {
    el.innerHTML = '<div style="color:#dc2626;font-size:12px;padding:16px">관계도 로드 실패: ' + lmEsc(e && e.message ? e.message : e) + '</div>';
  }
}

function fillLawMapTopicSelect() {
  var sel = document.getElementById('lawmap-topic-select');
  if (!sel) return;
  var cur = sel.value;
  var topics = _lawMapNodes.filter(function(n) { return n.node_type === 'topic'; })
    .sort(function(a, b) { return a.name.localeCompare(b.name, 'ko'); });
  var html = '<option value="">전체 인용망</option>';
  topics.forEach(function(t) { html += '<option value="' + t.id + '">' + lmEsc(t.name) + '</option>'; });
  sel.innerHTML = html;
  if (cur && topics.some(function(t) { return t.id === cur; })) sel.value = cur;
}

// 중심 노드의 포커스 서브그래프: 직접 이웃 + 계열(하위법령) 1단계 확장
// ※ 인용 이웃으로 2촌 확장하면 허브 법령(전파법 등)을 거쳐 수백 노드로 폭발 → 계열 엣지로만 확장
function lawmapNeighborhood(centerId) {
  var keep = new Set([centerId]);
  var direct = _lawMapEdges.filter(function(e) { return e.source_id === centerId || e.target_id === centerId; });
  // 허브 노드(피인용 수백 건) 포커스 시 강한 엣지 상위 80개만
  if (direct.length > 80) {
    direct = direct.slice().sort(function(a, b) { return (b.weight || 1) - (a.weight || 1); }).slice(0, 80);
  }
  direct.forEach(function(e) { keep.add(e.source_id); keep.add(e.target_id); });
  _lawMapEdges.forEach(function(e) {
    if (e.relation_type !== '하위법령') return;
    if (keep.has(e.source_id)) keep.add(e.target_id);
    else if (keep.has(e.target_id)) keep.add(e.source_id);
  });
  return {
    nodes: _lawMapNodes.filter(function(n) { return keep.has(n.id); }),
    edges: _lawMapEdges.filter(function(e) { return keep.has(e.source_id) && keep.has(e.target_id); })
  };
}

function lawmapWrapLabel(name) {
  if (name.length <= 10) return name;
  var mid = Math.ceil(name.length / 2);
  var sp = name.indexOf(' ', Math.max(0, mid - 3));
  if (sp !== -1 && sp < name.length - 2) return name.slice(0, sp) + '\n' + name.slice(sp + 1);
  return name.slice(0, mid) + '\n' + name.slice(mid);
}

function renderLawMapGraph(focusId) {
  _lawMapFocusId = focusId || null;
  var el = document.getElementById('lawmap-graph');
  if (!el) return;
  var nodes = _lawMapNodes, edges = _lawMapEdges;
  var focusNode = null;
  if (_lawMapFocusId) {
    focusNode = _lawMapNodes.find(function(n) { return n.id === _lawMapFocusId; }) || null;
    var sub = lawmapNeighborhood(_lawMapFocusId);
    nodes = sub.nodes; edges = sub.edges;
  } else {
    // 전체 뷰: '전파정책 관련 법'만 — 주제 + 주제·시드에 연결된 법 + 그 법의 계열(하위법령)로 코어를 정하고,
    //   엣지는 시드·주제 엣지 + (코어 내부의 계열·인용)만 표시. 지방세법처럼 세금 감면 조항에서 농지법·축산법 등
    //   타 분야 법을 대량 인용하는 허브의 바깥 인용은 코어 밖이라 제외됨(그 법의 전체 인용은 노드 클릭 시).
    var core = new Set();
    var topicIds = new Set();
    _lawMapNodes.forEach(function(n) { if (n.node_type === 'topic') { core.add(n.id); topicIds.add(n.id); } });
    // 주제에 닿은 엣지(seed·ai 등 출처 불문)의 양끝은 코어 — 시드 밖 법령만 근거로 가진 주제(예: 침해사고 신고→정보통신망법)가
    //   엣지 없는 단독 버블로 뜨던 문제 방지. 주제 엣지는 소수라 그래프 폭발 위험 없음.
    _lawMapEdges.forEach(function(e) { if (e.source === 'seed' || topicIds.has(e.source_id) || topicIds.has(e.target_id)) { core.add(e.source_id); core.add(e.target_id); } });
    _lawMapEdges.forEach(function(e) { if (e.source === 'family' && (core.has(e.source_id) || core.has(e.target_id))) { core.add(e.source_id); core.add(e.target_id); } });
    var keep = new Set();
    _lawMapEdges.forEach(function(e) {
      if (e.source === 'seed' || topicIds.has(e.source_id) || topicIds.has(e.target_id)) keep.add(e.id);
      else if (core.has(e.source_id) && core.has(e.target_id)) keep.add(e.id);
    });
    edges = _lawMapEdges.filter(function(e) { return keep.has(e.id); });
    var usedIds2 = new Set();
    edges.forEach(function(e) { usedIds2.add(e.source_id); usedIds2.add(e.target_id); });
    nodes = _lawMapNodes.filter(function(n) { return usedIds2.has(n.id) || n.node_type === 'topic'; });
    // 전체 뷰에서 고시·행정규칙 접기 — 노드의 절반 이상(96/178)이 고시라 중앙이 뭉개져 조망이 불가능했다.
    // 고시는 '법률→시행령→고시' 말단이라 전체 조망에선 잔가지이고, 주제·법령을 클릭하면 그대로 다 보인다.
    // ★ 단, 근거가 고시뿐인 주제(충전단자 표준화 등 3개)는 통째로 숨기면 엣지 없는 단독 버블이 된다 —
    //   #28에서 이미 고쳤던 회귀라, 그런 주제의 직결 고시는 예외로 남긴다. (배경역사 #36)
    if (!_lawMapShowNotice) {
      var noticeIds = new Set();
      nodes.forEach(function(n) { if (n.node_type === 'notice' || n.node_type === 'etc') noticeIds.add(n.id); });
      var degNoNotice = {};
      edges.forEach(function(e) {
        if (noticeIds.has(e.source_id) || noticeIds.has(e.target_id)) return;
        degNoNotice[e.source_id] = 1; degNoNotice[e.target_id] = 1;
      });
      var orphanTopics = new Set();
      nodes.forEach(function(n) { if (n.node_type === 'topic' && !degNoNotice[n.id]) orphanTopics.add(n.id); });
      var rescued = new Set();
      edges.forEach(function(e) {
        if (orphanTopics.has(e.source_id) && noticeIds.has(e.target_id)) rescued.add(e.target_id);
        if (orphanTopics.has(e.target_id) && noticeIds.has(e.source_id)) rescued.add(e.source_id);
      });
      var hiddenIds = new Set();
      noticeIds.forEach(function(id) { if (!rescued.has(id)) hiddenIds.add(id); });
      _lawMapHiddenCount = hiddenIds.size;
      if (hiddenIds.size) {
        edges = edges.filter(function(e) { return !hiddenIds.has(e.source_id) && !hiddenIds.has(e.target_id); });
        nodes = nodes.filter(function(n) { return !hiddenIds.has(n.id); });
      }
    } else {
      _lawMapHiddenCount = 0;
    }
  }
  updateLawMapNoticeToggle(!_lawMapFocusId);
  // 보강 버튼: 주제 포커스일 때만 노출
  var enrichBtn = document.getElementById('lawmap-enrich-btn');
  if (enrichBtn) enrichBtn.style.display = (focusNode && focusNode.node_type === 'topic') ? 'inline-flex' : 'none';

  var css = getComputedStyle(document.documentElement);
  var textColor = (css.getPropertyValue('--text-primary') || '').trim() || '#333';
  var bgColor = (css.getPropertyValue('--bg-primary') || '').trim() || '#fff';
  var visNodes = nodes.map(function(n) {
    return {
      id: n.id,
      label: lawmapWrapLabel(n.name),
      shape: 'dot',
      size: n.node_type === 'topic' ? 22 : 12,
      color: { background: LAWMAP_COLORS[n.node_type] || '#999', border: 'rgba(0,0,0,0.22)',
               highlight: { background: LAWMAP_COLORS[n.node_type] || '#999', border: textColor } },
      // 라벨에 배경색 외곽선 → 엣지·다른 노드 위에서도 글자가 읽힘
      font: { color: textColor, size: n.node_type === 'topic' ? 15 : 13, strokeWidth: 4, strokeColor: bgColor,
              vadjust: 0, bold: n.node_type === 'topic' }
    };
  });
  var visEdges = edges.map(function(e) {
    return {
      id: e.id, from: e.source_id, to: e.target_id,
      arrows: { to: { enabled: true, scaleFactor: 0.5 } },
      width: Math.min(1 + Math.log((e.weight || 1)) / Math.LN2 * 0.7, 4),
      color: { color: '#8a8f98', opacity: 0.5, highlight: '#5b7ff5' },
      title: (e.relation_type || '') + (e.description ? ' — ' + e.description : ''),
      smooth: { type: 'continuous' }
    };
  });
  el.innerHTML = '';
  var data = { nodes: new vis.DataSet(visNodes), edges: new vis.DataSet(visEdges) };
  var options = {
    physics: {
      barnesHut: { gravitationalConstant: -3000, springLength: 150, springConstant: 0.04, avoidOverlap: 0.4 },
      stabilization: { iterations: 250, updateInterval: 25, fit: true },
      minVelocity: 0.75
    },
    nodes: { scaling: { label: { enabled: true, min: 11, max: 20 } } },
    interaction: { hover: true, tooltipDelay: 120, hideEdgesOnDrag: visNodes.length > 60 },
    layout: { improvedLayout: visNodes.length <= 120 }
  };
  if (_lawMapNet) { try { _lawMapNet.destroy(); } catch(e) {} }
  _lawMapNet = new vis.Network(el, data, options);
  // 안정화가 끝나면 physics를 꺼서 노드가 계속 흔들리지 않게 함 (전체 인용망 '춤추는' 현상 방지)
  _lawMapNet.once('stabilizationIterationsDone', function() {
    try { _lawMapNet.setOptions({ physics: false }); _lawMapNet.fit({ animation: false }); } catch(e) {}
  });
  _lawMapNet.on('click', function(p) {
    if (!(p.nodes && p.nodes.length)) return;
    var id = p.nodes[0];
    var clicked = _lawMapNodes.find(function(x) { return x.id === id; });
    if (!clicked) return;
    var focusNode = _lawMapFocusId ? _lawMapNodes.find(function(x) { return x.id === _lawMapFocusId; }) : null;
    var inTopicView = !!(focusNode && focusNode.node_type === 'topic');
    if (!inTopicView && clicked.node_type === 'topic') {
      // 전체 인용망에서 주제 노드 클릭 → 주제 포커스로 전환
      var sel = document.getElementById('lawmap-topic-select');
      if (sel) sel.value = id;
      lawMapSelectTopic(id);
      return;
    }
    if (!inTopicView && clicked.node_type !== 'topic' && id !== _lawMapFocusId) {
      // 전체 인용망(또는 법령 포커스)에서 법령 클릭 → 그 법령 중심의 실제 인용·계열 관계로 드릴다운
      renderLawMapGraph(id);
      setLawMapStatus('법령 <b>' + lmEsc(clicked.name) + '</b> — 실제 인용·계열 관계 표시 중 · <a style="cursor:pointer;text-decoration:underline;color:var(--accent, #5b7ff5)" onclick="lawMapSelectTopic(\'\')">← 전체 인용망으로</a>');
    }
    showLawMapNodeDetail(id);
  });
}

function lawMapSelectTopic(id) {
  renderLawMapGraph(id || null);
  if (id) {
    var n = _lawMapNodes.find(function(x) { return x.id === id; });
    setLawMapStatus(n ? '주제 <b>' + lmEsc(n.name) + '</b> — 관련 법령·계열 표시 중' : '');
    if (n) showLawMapNodeDetail(id);
  } else {
    setLawMapStatus('전체 인용망 — 화살표 굵기는 인용·확인 횟수');
    var det = document.getElementById('lawmap-detail');
    if (det) det.innerHTML = '<span style="color:var(--text-secondary)">노드를 클릭하면 설명·주요 내용·근거 조문이 표시됩니다.</span>';
  }
}

// ── 질문 → ①주제 로컬 매칭(비용 0) → ②없으면 AI 생성 제안 ──
// 매칭은 **주제(topic) 노드로만** 한정 — 관계도는 주제 중심이라 법령·고시 노드에 매칭하면
// 질문과 무관한 그래프가 뜬다. '관련·법령·규정' 등 흔한 도메인 단어는 매칭에서 제외(오탐 방지).
var LAWMAP_MATCH_STOP = { '관련':1, '법령':1, '법률':1, '규정':1, '기준':1, '제도':1, '해당':1, '경우':1,
  '어디':1, '무엇':1, '방법':1, '절차':1, '내용':1, '사항':1, '관계':1, '전파':1, '통신':1, '무선':1,
  '주기':1, '대상':1, '요건':1, '현황':1, '개요':1 };

// 주제명을 의미 단어로 분해 (공백·가운뎃점·괄호 기준, 불용어·1글자 제거)
function lawmapTopicWords(name) {
  return name.split(/[\s·,()\/]+/)
    .map(function(w) { return w.replace(/[^가-힣A-Za-z0-9]/g, ''); })
    .filter(function(w) { return w.length >= 2 && !LAWMAP_MATCH_STOP[w]; });
}

async function askLawMap() {
  var input = document.getElementById('lawmap-q');
  var q = (input && input.value || '').trim();
  if (!q) return;
  if (!sb) { setLawMapStatus('⚠️ Supabase 연결이 필요합니다 (설정 탭)'); return; }
  if (!_lawMapLoaded) await loadLawMap();
  // 양방향 매칭: ① 주제명의 핵심 단어가 질문에 실제로 들어있어야 함(질문 공백 제거 후 부분일치)
  //             ② 질문 키워드가 주제 설명에 들어가면 가점(동점 해소)
  var qns = q.replace(/\s+/g, '').toLowerCase();
  var kws = extractKeywords(q).filter(function(k) { return !LAWMAP_MATCH_STOP[k]; });
  var best = null, bestScore = 0;
  _lawMapNodes.filter(function(n) { return n.node_type === 'topic'; }).forEach(function(n) {
    var words = lawmapTopicWords(n.name);
    var nameHits = words.filter(function(w) { return qns.indexOf(w.toLowerCase()) !== -1; });
    if (nameHits.length === 0) return;   // 주제의 핵심 단어가 질문에 없으면 후보 아님(오탐 차단)
    var s = nameHits.length * 3;
    var desc = (n.description || '').toLowerCase();
    kws.forEach(function(k) { if (desc.indexOf(k.toLowerCase()) !== -1) s += 1; });
    if (s > bestScore) { bestScore = s; best = n; }
  });
  if (best && bestScore >= 3) {
    var sel = document.getElementById('lawmap-topic-select');
    if (sel) sel.value = best.id;
    renderLawMapGraph(best.id);
    setLawMapStatus('✔ 기존 주제 매칭 (<b>' + lmEsc(best.name) + '</b>) — API 호출 없음 · 찾던 주제가 아니면 <button class="btn" style="font-size:11px;padding:2px 8px" onclick="generateLawMapTopic()"><i class="ti ti-sparkles"></i> AI로 새로 생성</button>');
    showLawMapNodeDetail(best.id);
  } else {
    // 엉뚱한 그래프를 그리지 않음 — 현재 화면 유지하고 생성만 제안
    setLawMapStatus('“' + lmEsc(q.slice(0, 30)) + '”에 맞는 주제가 관계망에 없습니다 — <button class="btn btn-primary" style="font-size:11px;padding:2px 10px" onclick="generateLawMapTopic()"><i class="ti ti-sparkles"></i> AI로 관계도 생성 (1회 과금)</button>');
  }
}

// ── AI 호출 공통 (비스트리밍·짧은 JSON) ──
var LAWMAP_GEN_SYSTEM = '당신은 한국 전파·통신 법령 체계 전문가입니다. 질문 주제와 관련된 법령(법률·시행령·시행규칙·고시)과 타 분야 법령(세법 등)까지 포함해 관계도를 JSON으로만 출력합니다. 형식: {"topic":"주제명(2~12자)","description":"주제 한줄 설명","relations":[{"law":"법령 정식명칭","type":"law|decree|rules|notice|etc","relation":"주제와의 관계 한줄","basis":"제N조 등 근거 조문","law_desc":"법령 한줄 설명"}]} — JSON 외 텍스트 금지. relations 최대 8개. 제공된 참고 원문에 근거가 있으면 basis에 조문을 명시하고, 근거가 불확실한 법령은 넣지 마세요.';

async function callLawmapAI(userMsg) {
  var cfg = getConfig();
  if (!cfg.claudeKey) throw new Error('Claude API 키가 설정되지 않았습니다 (설정 탭에서 입력)');
  var res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: { 'x-api-key': cfg.claudeKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json', 'anthropic-dangerous-direct-browser-access': 'true' },
    // thinking:disabled — Sonnet 5 적응형 추론이 첫 블록을 thinking으로 만들어 비스트리밍 파싱이 깨지는 함정 회피 (지침 do-not)
    body: JSON.stringify({ model: 'claude-sonnet-5', max_tokens: 2500, thinking: { type: 'disabled' }, system: LAWMAP_GEN_SYSTEM, messages: [{ role: 'user', content: userMsg }] })
  });
  if (!res.ok) {
    var err = await res.json().catch(function() { return {}; });
    throw new Error((err.error && err.error.message) || ('API 오류 HTTP ' + res.status));
  }
  var data = await res.json();
  // content[0] 가정 금지 — text 블록을 찾아 사용
  var tb = (data.content || []).find(function(b) { return b.type === 'text'; });
  var text = tb ? tb.text : '';
  var m = text.match(/\{[\s\S]*\}/);
  if (!m) throw new Error('AI 응답에서 JSON을 찾지 못했습니다');
  return JSON.parse(m[0]);
}

async function generateLawMapTopic() {
  var input = document.getElementById('lawmap-q');
  var q = (input && input.value || '').trim();
  if (!q) return;
  setLawMapStatus('🤖 RAG 근거 수집 + AI 생성 중… (20~40초)');
  try {
    var chunks = await searchKeywords(q, false);
    var ctx = (chunks || []).slice(0, 8).map(function(c) {
      return '[' + c.doc_name + (c.article_no ? ' ' + c.article_no : '') + ']\n' + (c.content || '').slice(0, 500);
    }).join('\n\n');
    var existingTopics = _lawMapNodes.filter(function(n) { return n.node_type === 'topic'; }).map(function(n) { return n.name; });
    var userMsg = '질문: ' + q +
      '\n\n기존 주제명 목록(같은 의미가 있으면 그대로 재사용): ' + (existingTopics.join(', ') || '(없음)') +
      (ctx ? '\n\n[참고 법령 원문]\n' + ctx : '');
    var data = await callLawmapAI(userMsg);
    var saved = await saveLawmapData(data, 'ai');
    await loadLawMap(true);
    if (saved.topicId) {
      var sel = document.getElementById('lawmap-topic-select');
      if (sel) sel.value = saved.topicId;
      renderLawMapGraph(saved.topicId);
      showLawMapNodeDetail(saved.topicId);
    }
    setLawMapStatus('✨ 생성 완료 · DB 저장 — 다음부터는 검색만으로 표시됩니다');
  } catch(e) {
    setLawMapStatus('⚠️ 생성 실패: ' + lmEsc(e && e.message ? e.message : e));
  }
}

// ── 저장 (병합 원칙: 기존 노드·엣지 절대 삭제 안 함 — 신규만 추가, 재확인 엣지는 weight+1) ──
async function saveLawmapData(data, src) {
  if (!sb || !data || !data.topic || !Array.isArray(data.relations)) return {};
  src = src || 'ai';
  async function getOrCreateNode(name, type, desc) {
    name = String(name || '').trim();
    if (!name || name.length > 60) return null;
    var ex = await sb.from('law_graph_nodes').select('id,description').eq('name', name).maybeSingle();
    if (ex.data && ex.data.id) {
      if (desc && !ex.data.description) {
        try { await sb.from('law_graph_nodes').update({ description: desc }).eq('id', ex.data.id); } catch(e) {}
      }
      return ex.data.id;
    }
    var ins = await sb.from('law_graph_nodes').insert({ name: name, node_type: type, description: desc || null, source: src }).select('id').single();
    if (ins.error) {
      // unique 충돌(동시 생성) 시 재조회
      var again = await sb.from('law_graph_nodes').select('id').eq('name', name).maybeSingle();
      return (again.data && again.data.id) || null;
    }
    return ins.data.id;
  }
  var topicId = await getOrCreateNode(data.topic, 'topic', data.description || null);
  if (!topicId) return {};
  var validTypes = { law:1, decree:1, rules:1, notice:1, etc:1 };
  var rels = data.relations.slice(0, 10);
  for (var i = 0; i < rels.length; i++) {
    var rel = rels[i];
    if (!rel || !rel.law) continue;
    var t = validTypes[rel.type] ? rel.type : guessLawNodeType(String(rel.law));
    var lawId = await getOrCreateNode(rel.law, t, rel.law_desc || null);
    if (!lawId || lawId === topicId) continue;
    var desc = (rel.relation || '관련') + (rel.basis ? ' (' + rel.basis + ')' : '');
    var exE = await sb.from('law_graph_edges').select('id,weight').eq('source_id', topicId).eq('target_id', lawId).eq('relation_type', '근거').maybeSingle();
    if (exE.data && exE.data.id) {
      try { await sb.from('law_graph_edges').update({ weight: (exE.data.weight || 1) + 1 }).eq('id', exE.data.id); } catch(e) {}
    } else {
      try { await sb.from('law_graph_edges').insert({ source_id: topicId, target_id: lawId, relation_type: '근거', description: desc, source: src, weight: 1 }); } catch(e) { console.warn('엣지 저장 실패(계속):', e); }
    }
  }
  return { topicId: topicId };
}

// ── AI 보강: 현재 주제 그래프를 통째로 보여주고 "빠진 관계만" 추가 (기존 유지) ──
async function enrichLawMapTopic() {
  var topic = _lawMapFocusId ? _lawMapNodes.find(function(n) { return n.id === _lawMapFocusId; }) : null;
  if (!topic || topic.node_type !== 'topic') { setLawMapStatus('주제를 먼저 선택하세요'); return; }
  setLawMapStatus('🔄 기존 그래프 기준 누락 관계 탐색 중… (20~40초, 1회 과금)');
  try {
    var sub = lawmapNeighborhood(topic.id);
    var curLines = sub.edges.filter(function(e) { return e.source_id === topic.id || e.target_id === topic.id; }).map(function(e) {
      var a = _lawMapNodes.find(function(n) { return n.id === e.source_id; });
      var b = _lawMapNodes.find(function(n) { return n.id === e.target_id; });
      return (a ? a.name : '?') + ' → ' + (b ? b.name : '?') + ' : ' + (e.description || e.relation_type || '');
    }).join('\n');
    var chunks = await searchKeywords(topic.name, false);
    var ctx = (chunks || []).slice(0, 6).map(function(c) {
      return '[' + c.doc_name + (c.article_no ? ' ' + c.article_no : '') + ']\n' + (c.content || '').slice(0, 400);
    }).join('\n\n');
    var userMsg = '주제 "' + topic.name + '"의 현재 관계도:\n' + (curLines || '(없음)') +
      '\n\n위 그래프에서 빠진 관련 법령·관계만 추가로 제시하세요. topic은 반드시 "' + topic.name + '" 그대로 사용하고, 이미 그래프에 있는 법령은 relations에 넣지 마세요.' +
      (ctx ? '\n\n[참고 법령 원문]\n' + ctx : '');
    var data = await callLawmapAI(userMsg);
    data.topic = topic.name; // 주제명 강제 고정
    await saveLawmapData(data, 'ai');
    await loadLawMap(true);
    var again = _lawMapNodes.find(function(n) { return n.name === topic.name && n.node_type === 'topic'; });
    if (again) renderLawMapGraph(again.id);
    setLawMapStatus('✨ 보강 완료 — 기존 관계는 유지, 신규만 추가됨');
  } catch(e) {
    setLawMapStatus('⚠️ 보강 실패: ' + lmEsc(e && e.message ? e.message : e));
  }
}

// ── 노드 상세 카드: 주제 맥락 인식형 ──
// 주제 포커스 중 법령 노드 클릭 → ① 이 주제에서의 역할 ② 근거 조문 원문 발췌 ③ 현재 그래프 내부 관계만.
// 법령 전체 요약(OKF)은 접힌 상태로만 제공 (주제와 무관한 전체 내용이 쏟아지지 않게)
async function showLawMapNodeDetail(nodeId) {
  var el = document.getElementById('lawmap-detail');
  if (!el) return;
  var n = _lawMapNodes.find(function(x) { return x.id === nodeId; });
  if (!n) return;
  var color = LAWMAP_COLORS[n.node_type] || '#999';

  // 주제 포커스 맥락: 포커스 주제와 이 노드를 잇는 엣지 (역할·근거 조문 출처)
  var focusTopic = null, topicEdge = null;
  if (_lawMapFocusId && _lawMapFocusId !== nodeId) {
    var f = _lawMapNodes.find(function(x) { return x.id === _lawMapFocusId; });
    if (f && f.node_type === 'topic') {
      focusTopic = f;
      topicEdge = _lawMapEdges.find(function(e) {
        return (e.source_id === f.id && e.target_id === nodeId) || (e.target_id === f.id && e.source_id === nodeId);
      }) || null;
    }
  }

  // 연결 관계: 포커스 중이면 화면에 보이는 서브그래프 내부 엣지만 (전체 인용 관계가 쏟아지지 않게)
  var scopeEdges = _lawMapEdges;
  if (_lawMapFocusId) scopeEdges = lawmapNeighborhood(_lawMapFocusId).edges;
  var rels = scopeEdges.filter(function(e) { return e.source_id === nodeId || e.target_id === nodeId; })
    .slice(0, 20)
    .map(function(e) {
      var otherId = e.source_id === nodeId ? e.target_id : e.source_id;
      var other = _lawMapNodes.find(function(x) { return x.id === otherId; });
      if (!other) return '';
      return '<li><b>' + lmEsc(other.name) + '</b> — ' + lmEsc(e.description || e.relation_type || '관련') + '</li>';
    }).join('');

  var html =
    '<div style="font-weight:700;color:var(--text-primary)">' + lmEsc(n.name) +
      ' <span style="font-size:10px;padding:1px 7px;border-radius:999px;background:' + color + '22;border:1px solid ' + color + '66;color:var(--text-secondary)">' + (LAWMAP_TYPE_LABEL[n.node_type] || n.node_type) + '</span></div>';
  if (focusTopic) {
    var roleText = topicEdge
      ? ('에서의 역할: ' + lmEsc(topicEdge.description || topicEdge.relation_type))
      : ' 맥락에서 관련 조문을 표시합니다';   // 직접 관계 엣지 없이 계열로 딸려온 노드
    html += '<div style="margin:5px 0;padding:6px 10px;border-left:3px solid ' + LAWMAP_COLORS.topic + ';background:var(--bg-secondary);border-radius:0 6px 6px 0;font-size:12.5px;color:var(--text-primary)">🎯 <b>' + lmEsc(focusTopic.name) + '</b>' + roleText + '</div>';
  }
  if (n.description) {
    html += '<div style="margin:4px 0 2px;color:var(--text-secondary)">' + lmEsc(n.description) + '</div>';
  }
  if (n.node_type !== 'topic') {
    html += '<div id="lawmap-article" style="margin:6px 0"></div>';   // 📌 근거 조문 발췌 (주제 맥락 있을 때)
    html += '<div id="lawmap-okf" style="margin:6px 0"><span style="font-size:11px;color:var(--text-tertiary)">📖 요약 확인 중…</span></div>';
  }
  html +=
    '<div style="font-size:11px;color:var(--text-tertiary);margin-top:4px">연결 관계' + (_lawMapFocusId ? ' <span style="opacity:.7">(현재 그래프 범위)</span>' : '') + '</div>' +
    '<ul style="margin:2px 0 0 18px;padding:0;font-size:12px;color:var(--text-secondary)">' + (rels || '<li>연결 없음</li>') + '</ul>' +
    '<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">' +
      '<button class="btn" id="lawmap-doc-btn" style="font-size:11px;padding:3px 10px;display:none"><i class="ti ti-file-text"></i> 원문 보기</button>' +
      '<button class="btn" id="lawmap-chat-btn" style="font-size:11px;padding:3px 10px"><i class="ti ti-message-circle"></i> AI 자문에 질문</button>' +
    '</div>';
  el.innerHTML = html;
  var chatBtn = document.getElementById('lawmap-chat-btn');
  if (chatBtn) chatBtn.addEventListener('click', function() { askLawMapToChat(n.name, n.node_type); });

  if (n.node_type === 'topic') return;

  // 원문 doc_name 확정: 노드 연결 → 없으면 document_chunks에서 이름으로 탐색 (조문 발췌·원문 버튼 공용)
  var docName = n.doc_name || null;
  if (!docName && sb) {
    try {
      var dq = await sb.from('document_chunks').select('doc_name').ilike('doc_name', n.name + '%').limit(1);
      if (dq.data && dq.data.length) docName = dq.data[0].doc_name;
    } catch(e) {}
  }
  var docBtn = document.getElementById('lawmap-doc-btn');
  if (docBtn && docName) {
    docBtn.style.display = 'inline-flex';
    docBtn.addEventListener('click', function() { openLawMapDoc(docName); });
  }
  // 위임 연결(delegation): 이 노드가 시행령·시행규칙이면, 그 상위법에 대한 주제 엣지의 근거 조문을 찾아
  //  전달 → fillLawMapArticle이 "법 제N조"를 인용하는(=위임받는) 하위법령 조문을 정확히 집어냄.
  var parentBasis = '';
  if (focusTopic && /(시행령|시행규칙)$/.test(n.name)) {
    var parentName = n.name.replace(/\s*(시행령|시행규칙)$/, '').trim();
    var parentNode = _lawMapNodes.find(function(x) { return x.name === parentName; });
    if (parentNode) {
      var pe = _lawMapEdges.find(function(e) {
        return (e.source_id === focusTopic.id && e.target_id === parentNode.id) || (e.target_id === focusTopic.id && e.source_id === parentNode.id);
      });
      if (pe && pe.description) parentBasis = pe.description;
    }
  }
  // 주제 포커스면 관련 조문 발췌를 먼저 표시. 법령 전체 요약(OKF)은 펼쳐서 표시.
  if (focusTopic) fillLawMapArticle(n, (topicEdge && topicEdge.description) || '', docName, focusTopic.name, parentBasis);
  fillLawMapMainContent(n, true);
}

// 조문 발췌 — 추측이 아니라 법령 구조로 정확히 집는다. 우선순위:
//  ① 명시된 조문(엣지 설명의 "제N조", 범위·의M 포함)
//  ② 위임 연결: 시행령·시행규칙이면 상위법의 근거 조문(parentBasis 제N조)을 "법 제N조"로 인용하는 조문
//  ③ 최후 폴백: 법령 내부 키워드+시맨틱 하이브리드 검색
var LAWMAP_ART_BOILER = /(목적|정의|적용\s*범위|다른\s*법령|개정|폐지|경과조치|시행일|약칭|권한의\s*위임|위임[ㆍ·]\s*위탁)/;

// PDF 추출 시 조문 본문에 섞여 들어간 편집 흔적 제거 (표시 전용 — 저장 데이터는 건드리지 않음)
//  · [N페이지] 페이지 구분 표시  · "법제처 N 국가법령정보센터" 쪽 하단 footer
//  · 페이지마다 반복되는 법령명 머리글(예: 단독 줄 "전파법")  · 과다 공백/개행
function lawmapCleanText(s, lawName) {
  var t = String(s == null ? '' : s)
    .replace(/\[\s*\d+\s*페이지\s*\]/g, '')
    .replace(/(?:법제처\s*)?\d*\s*국가법령정보센터/g, '');   // 청킹 경계에서 '법제처'가 잘려도 잡음
  var title = (lawName || '').trim();
  var lines = t.split('\n').filter(function(ln) {
    var v = ln.trim();
    return !(title && v === title);   // 줄 전체가 법령명(반복 머리글)이면 제거
  });
  return lines.join('\n').replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
}
function lawmapArtNoMatch(c, wants) {
  var aa = (c.article_no || '').replace(/^제/, '');
  return wants.some(function(w) { return aa === w || aa.indexOf(w + '(') === 0; });
}
function lawmapArtNums(basisText) {   // "제24~25조", "제24조의2" → 조문 키 배열
  var m = (basisText || '').match(/제\s*(\d+)\s*조?(?:의\s*(\d+))?\s*(?:[~∼\-]\s*(?:제\s*)?(\d+))?/);
  if (!m) return { nums: [], wants: [] };
  var start = parseInt(m[1], 10);
  var end = m[3] ? parseInt(m[3], 10) : start;
  if (isNaN(end) || end < start || end - start > 4) end = start;
  var nums = [], wants = [start + '조' + (m[2] ? '의' + m[2] : '')];
  for (var a = start; a <= end; a++) { nums.push(a); if (a !== start || !m[2]) wants.push(a + '조'); }
  return { nums: nums, wants: wants.filter(function(v, i, arr) { return arr.indexOf(v) === i; }) };
}

async function fillLawMapArticle(n, basisText, docName, topicName, parentBasis) {
  var box = document.getElementById('lawmap-article');
  if (!box || !sb || !docName) return;
  try {
    var r = await sb.from('document_chunks').select('content,article_no,chunk_index')
      .eq('doc_name', docName).order('chunk_index', { ascending: true }).limit(500);
    var all = r.data || [];
    if (!all.length) return;

    var picked = [], mode = '근거', searchMode = 'kw';
    // ① 명시된 조문
    var w1 = lawmapArtNums(basisText);
    if (w1.wants.length) all.forEach(function(c) { if (lawmapArtNoMatch(c, w1.wants) && picked.indexOf(c) === -1) picked.push(c); });

    // 위임 연결 후보군: 시행령·시행규칙이 상위법 근거 조문(parentBasis)을 "법 제N조"로 인용하는 조문 집합.
    //  이 집합으로 후보를 '구조적으로' 좁히고(아래 하이브리드가 그 안에서 주제 관련성으로 순위 매김).
    var delegSet = null;
    if (!picked.length && parentBasis) {
      var pnums = lawmapArtNums(parentBasis).nums;
      if (pnums.length) {
        var delegRe = new RegExp('법\\s*제\\s*(?:' + pnums.join('|') + ')\\s*조');
        var cand = {};
        all.forEach(function(c) {
          var art = c.article_no || '';
          if (!art || LAWMAP_ART_BOILER.test(art)) return;
          if (delegRe.test(c.content || '')) cand[art] = true;
        });
        if (Object.keys(cand).length) delegSet = cand;
      }
    }

    // ② 관련 조문 → (위임 후보군이 있으면 그 안에서) 키워드+시맨틱 하이브리드로 순위
    if (!picked.length) {
      mode = '관련';
      var qEl = document.getElementById('lawmap-q');
      var queryText = (topicName || '') + ' ' + (basisText || '') + ' ' + (parentBasis || '') + ' ' + (qEl ? qEl.value : '');

      // (a) 키워드: **조문 단위로 한 번만** 집계(청크 수 편향 제거). 제목 매칭 ×5, 본문 ×1.
      var terms = extractKeywords(queryText).filter(function(k) { return !LAWMAP_MATCH_STOP[k]; });
      (topicName || '').split(/[\s·]+/).forEach(function(w) { w = w.trim(); if (w.length >= 2 && !LAWMAP_MATCH_STOP[w] && terms.indexOf(w) === -1) terms.push(w); });
      var byArt = {};
      all.forEach(function(c) {
        var art = c.article_no || '';
        if (!art) return;
        var rec = byArt[art] || (byArt[art] = { art: art, chunks: [], body: '', kw: 0, sem: 0, ci: c.chunk_index || 0 });
        rec.chunks.push(c);
        rec.body += ' ' + (c.content || '');
      });
      Object.keys(byArt).forEach(function(k) {
        var rec = byArt[k];
        terms.forEach(function(t) {
          if (rec.art.indexOf(t) !== -1) rec.kw += 5;   // 제목 매칭(조문당 1회)
          if (rec.body.indexOf(t) !== -1) rec.kw += 1;  // 본문 매칭(조문당 1회)
        });
      });

      // (b) 시맨틱: 질의 임베딩 → 문서 한정 pgvector 검색 (실패 시 키워드만)
      try {
        var emb = await getQueryEmbedding(queryText);
        if (emb) {
          var sres = await sb.rpc('match_chunks_semantic_in_doc', { query_embedding: emb, p_doc_name: docName, match_count: 15 });
          (sres.data || []).forEach(function(row) {
            var art = row.article_no || '';
            if (!art || !byArt[art]) return;
            byArt[art].sem = Math.max(byArt[art].sem, row.similarity || 0);   // 조문 내 최고 유사도
          });
          searchMode = 'hybrid';
        }
      } catch(e) { console.warn('관계도 시맨틱 검색 실패(키워드로 진행):', e); }

      // (c) 결합: 키워드 0~1 정규화 + 시맨틱(0~1) 가중합. 총칙·부칙 제외.
      //     위임 후보군(delegSet)이 있으면 그 안에서만 순위 → 구조(위임)로 좁히고 관련성으로 고름.
      var recs = Object.keys(byArt).map(function(k) { return byArt[k]; })
        .filter(function(r) { return !LAWMAP_ART_BOILER.test(r.art) && (!delegSet || delegSet[r.art]); });
      var maxKw = recs.reduce(function(mx, r) { return Math.max(mx, r.kw); }, 0) || 1;
      recs.forEach(function(r) { r.combined = (r.kw / maxKw) * 0.45 + r.sem * 0.55; });
      var arts = recs.filter(function(r) { return r.combined > 0.02; })
        .sort(function(a, b) { return b.combined - a.combined || a.ci - b.ci; });
      if (arts.length) { picked = arts[0].chunks; searchMode = delegSet ? 'deleg' : searchMode; }
    }
    if (!picked.length) return;
    picked.sort(function(x, y) { return (x.chunk_index || 0) - (y.chunk_index || 0); });
    var labels = picked.map(function(c) { return c.article_no; }).filter(function(v, i, arr) { return v && arr.indexOf(v) === i; }).slice(0, 3);
    var text = picked.slice(0, 4).map(function(c) { return (c.article_no ? '【' + c.article_no + '】\n' : '') + lawmapCleanText(c.content, n.name); }).join('\n\n').slice(0, 1400);
    var modeLabel = searchMode === 'deleg' ? '위임 근거+관련성' : (searchMode === 'hybrid' ? '키워드+의미 검색' : '키워드 매칭');
    var title = mode === '근거' ? '📌 근거 조문' : ('📌 관련 조문(' + modeLabel + ')');
    box.innerHTML =
      '<details open><summary style="cursor:pointer;font-size:12px;color:var(--accent, #5b7ff5)">' + title + (labels.length ? ' — ' + lmEsc(labels.join(', ')) : '') + '</summary>' +
      '<div style="margin-top:5px;padding:7px 10px;border-left:3px solid ' + LAWMAP_COLORS.topic + '88;background:var(--bg-secondary);border-radius:0 6px 6px 0;font-size:12px;line-height:1.65;color:var(--text-secondary);white-space:pre-wrap">' +
      lmEsc(text) + (text.length >= 1400 ? '…' : '') + '</div></details>';
  } catch(e) {}
}

// 📖 법령 전체 요약: kb_documents(OKF) → 없으면 노드 설명으로 대체. openByDefault면 펼쳐서 표시.
async function fillLawMapMainContent(n, openByDefault) {
  var box = document.getElementById('lawmap-okf');
  if (!box || !sb) return;
  try {
    var r = await sb.from('kb_documents').select('title,description,body_md').eq('status', 'current').ilike('title', '%' + n.name + '%').limit(1);
    var doc = (r.data && r.data[0]) || null;
    if (doc) {
      var body = (doc.body_md || '').slice(0, 1200);
      box.innerHTML =
        '<details' + (openByDefault ? ' open' : '') + '><summary style="cursor:pointer;font-size:12px;color:var(--accent, #5b7ff5)">📖 법령 전체 요약 보기 (요약 지식베이스)</summary>' +
        '<div style="margin-top:5px;padding:7px 10px;border-left:3px solid ' + (LAWMAP_COLORS[n.node_type] || '#999') + '88;background:var(--bg-secondary);border-radius:0 6px 6px 0;font-size:12px;line-height:1.65;color:var(--text-secondary);white-space:pre-wrap">' +
        (doc.description ? lmEsc(doc.description) + '\n\n' : '') + lmEsc(body) + (doc.body_md && doc.body_md.length > 1200 ? '…' : '') +
        '</div></details>';
    } else {
      box.innerHTML = n.description
        ? '<div style="font-size:10.5px;color:var(--text-tertiary)">ℹ️ 요약 지식베이스(OKF) 미구축 법령 — 위 설명으로 대체 (원문 보기는 가능할 수 있음)</div>'
        : '<div style="font-size:10.5px;color:var(--text-tertiary)">ℹ️ 요약 정보 없음 — 원문 보기 또는 AI 자문을 이용하세요</div>';
    }
  } catch(e) {
    box.innerHTML = '<div style="font-size:10.5px;color:var(--text-tertiary)">주요 내용 조회 실패</div>';
  }
}

// 원문 미리보기 모달 — document_chunks 앞부분 조문
async function openLawMapDoc(docName) {
  var modal = document.getElementById('lawmap-doc-modal');
  var title = document.getElementById('lawmap-doc-title');
  var body = document.getElementById('lawmap-doc-body');
  if (!modal || !sb) return;
  modal.style.display = 'flex';
  title.innerHTML = '<i class="ti ti-file-text"></i> ' + lmEsc(docName);
  body.textContent = '불러오는 중...';
  try {
    var r = await sb.from('document_chunks').select('content,article_no,chunk_index').eq('doc_name', docName).order('chunk_index', { ascending: true }).limit(6);
    var rows = r.data || [];
    if (!rows.length) { body.textContent = '원문 청크를 찾지 못했습니다.'; return; }
    var docTitle = docName.split('(')[0].trim();   // "전파법(법률)(...)" → "전파법"
    body.textContent = rows.map(function(c) { return (c.article_no ? '【' + c.article_no + '】\n' : '') + lawmapCleanText(c.content, docTitle); }).join('\n\n────────\n\n') +
      '\n\n※ 앞부분 ' + rows.length + '개 청크 미리보기 — 전체 원문은 지식 베이스/AI 자문에서 확인';
  } catch(e) {
    body.textContent = '원문 조회 실패: ' + (e && e.message ? e.message : e);
  }
}

function askLawMapToChat(name, nodeType) {
  go('chat', null);
  var inp = document.getElementById('chat-input');
  if (inp) {
    inp.value = nodeType === 'topic'
      ? '"' + name + '" 관련 법령 체계와 실무 절차를 근거 조문과 함께 설명해줘.'
      : '"' + name + '"의 주요 내용과 우리 팀(전파정책) 업무 관련 조항을 설명해줘.';
    inp.focus();
  }
}

// 채팅 미니 관계도 클릭 → 관계도 탭에서 해당 주제 포커스
async function goLawMapTopicByName(topicName) {
  go('lawmap', null);
  if (!_lawMapLoaded) await loadLawMap();
  else await loadLawMap(true); // 방금 자문에서 저장된 신규 관계 반영
  var t = _lawMapNodes.find(function(n) { return n.node_type === 'topic' && n.name === topicName; });
  if (t) {
    var sel = document.getElementById('lawmap-topic-select');
    if (sel) sel.value = t.id;
    renderLawMapGraph(t.id);
    setLawMapStatus('주제 <b>' + lmEsc(t.name) + '</b> — 관련 법령·계열 표시 중');
    showLawMapNodeDetail(t.id);
  }
}

// 자문 답변 하단용 정적 SVG 미니 관계도 (주제 중심 방사형, vis-network 불필요)
function renderMiniLawMap(topic, relations) {
  var rels = (relations || []).slice(0, 8);
  if (!rels.length) return '';
  var W = 560, H = rels.length <= 4 ? 210 : 250;
  var cx = W / 2, cy = H / 2, R = Math.min(H / 2 - 40, 88);
  var validTypes = { law:1, decree:1, rules:1, notice:1, etc:1 };
  var svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;display:block" role="img">' +
    '<defs><marker id="lmArr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="rgba(128,128,128,.55)"/></marker></defs>';
  var pts = rels.map(function(r, i) {
    var ang = -Math.PI / 2 + (i * 2 * Math.PI / rels.length);
    return { x: cx + R * Math.cos(ang), y: cy + R * Math.sin(ang) * 0.82, rel: r };
  });
  pts.forEach(function(p) {
    var dx = p.x - cx, dy = p.y - cy, L = Math.sqrt(dx * dx + dy * dy) || 1;
    var x1 = cx + dx / L * 30, y1 = cy + dy / L * 30, x2 = p.x - dx / L * 17, y2 = p.y - dy / L * 17;
    svg += '<line x1="' + x1 + '" y1="' + y1 + '" x2="' + x2 + '" y2="' + y2 + '" stroke="rgba(128,128,128,.5)" stroke-width="1.3" marker-end="url(#lmArr)"/>';
  });
  pts.forEach(function(p) {
    var t = validTypes[p.rel.type] ? p.rel.type : guessLawNodeType(String(p.rel.law || ''));
    var name = String(p.rel.law || '').slice(0, 14);
    svg += '<circle cx="' + p.x + '" cy="' + p.y + '" r="12" fill="' + (LAWMAP_COLORS[t] || '#999') + '" fill-opacity=".9" stroke="rgba(0,0,0,.18)"/>';
    svg += '<text x="' + p.x + '" y="' + (p.y + 24) + '" text-anchor="middle" font-size="10" fill="currentColor">' + lmEsc(name) + '</text>';
  });
  svg += '<circle cx="' + cx + '" cy="' + cy + '" r="26" fill="' + LAWMAP_COLORS.topic + '" fill-opacity=".92" stroke="rgba(0,0,0,.18)"/>';
  svg += '<text x="' + cx + '" y="' + (cy + 4) + '" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">' + lmEsc(String(topic).slice(0, 8)) + '</text>';
  svg += '</svg>';
  return '<div class="lawmap-mini-svg">' + svg + '</div>';
}

// ════════════════════════════════════════════
//  앱 초기화 (DOCX 업로드 지원 — mammoth)
// ════════════════════════════════════════════
// 키보드 접근 — 사이드바 .nav-item·그룹탭(.group-tabbar > div)을 Enter/Space로 실행.
// 전역 위임 리스너 1개(동적 생성 그룹탭도 커버). Space는 preventDefault로 페이지 스크롤 방지.
document.addEventListener('keydown', function(e) {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  var t = e.target;
  if (!t || typeof t.matches !== 'function') return;
  if (t.matches('.nav-item, .group-tabbar > div')) {
    e.preventDefault();
    t.click();
  }
});

document.addEventListener('DOMContentLoaded', function() {
  initSupabase();
  updateStatusDots();
  loadSettingsUI();
  // loadPressJSON()은 진입 시 호출하지 않는다 — 보도자료 탭 진입(go('press') → loadPressFromSupabase)과
  // smartRefresh(panel-press)에서 로드된다. 첫 화면(뉴스)에서 불필요한 대량 조회 제거 (#61)
  loadRemoteConfig().then(function() { currentNewsSourceType = 'media'; loadNews(); renderGroupTabs('news'); });
  refreshOpsLight();   // 상단바 상태등 — 페이지 로드 시 1회 (이후 smartRefresh마다 갱신)
  setTimeout(autoExtractTermsIfNeeded, 60000);
});
