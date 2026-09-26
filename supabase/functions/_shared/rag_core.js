// ============================================================================
//  rag_core.js — 자문 검색의 **순수 규칙**(키워드 추출·법령 어휘 대응표·제외어·순위 융합·컨텍스트 문구·상한 상수)
//  한 파일 (#215, 2026-09-25, 개선안 §4-2-12 단계 A).
//
//  배경: 같은 규칙이 대시보드(app.js)와 텔레그램 봇(rag.ts)에 두 벌로 있었고 "동일 유지" 주석 52개로만 지켜졌다.
//  실측(2026-09-25) 결과 상수 표는 아직 같았지만 함수 3개는 이미 갈라져 있었다 — 뉴스 검색어 추출(불용어·분야어·정렬),
//  조문 참조 머리의 점수 표기(대시보드만), 법령요약 지시문(문장 수). 규율이 아니라 구조로 막는다: 여기 한 파일을
//  브라우저(index.html <script>, app.js보다 먼저), Deno Edge(rag.ts `import './rag_core.js'`), node 테스트
//  (tests/rag_core.test.js)가 그대로 쓴다 — cite_verify.js(#155)와 같은 방식이라 TS 문법·export 없이
//  globalThis.RagCore에 붙인다. 이 파일을 고치면 telegram-webhook 재배포 + index.html 캐시버스터 + node 테스트.
//
//  이 파일에 두는 것 / 두지 않는 것:
//   · 둔다 — DB·네트워크를 만지지 않는 함수와 상수. 입력은 배열·문자열, 출력도 그렇다.
//   · 두지 않는다 — Supabase 조회, Haiku 확장, 임베딩, 스트림, 로그 출력, 화면 상태(lastKbSources 등).
//     그런 건 app.js·rag.ts가 각자 갖고, 여기 함수를 부른다. 매체별로 다른 것(봇 3,000자 지시·출력 토큰 상한)도 각자.
//   · 규칙을 바꿀 때는 여기만 고친다. app.js·rag.ts에 같은 이름을 다시 정의하지 말 것 —
//     tests/rag_core.test.js가 두 파일에서 이 이름들의 재정의를 찾으면 실패한다.
// ============================================================================
(function (root) {
  'use strict';

  // ── 법령 검색용 키워드 추출 ─────────────────────────────────────────────
  // 우선 키워드(법령 명사) — 상한 5개를 앞에서부터 자르므로, 질문 앞에 전제 문장이 붙으면 '추가지원금·이용자' 같은
  // 법령 어휘가 '직접·운영' 뒤로 밀려 잘렸다(2026-09-17 실측, #173). 용언 어미는 '운영하고'·'지급하는'이 어미째
  // 키워드가 되면 ilike에 아무것도 안 걸리므로 뗀다.
  const PRIORITY_KW_RE = /제\d+조|주파수|할당|재할당|전자파|ITU|5G|6G|EMC|SAR|고시|시행령|시행규칙|적합성|기술기준|무선국|면허|허가|신청|승인|폐업|폐지|이용기간|지원금|장려금|차별|이용자|대리점|판매점|유통점|약관|요금|금지행위|과징금|과태료|벌칙|벌금|사업자|기지국|검사|등록|신고|취소|회수|위탁|도매|접속|설비|번호이동|결합|계약|고지|공시|재난|손해배상|개인정보|위치정보|단말|보조금|할인|선택약정|전기통신|전파|무선|공동이용|역무|커버리지|경매/;
  // 2026-09-26 사내 권고 반영(#244): '변경하려면'·'산정하나요'·'해야' 같은 어미가 통째 키워드로 남아 5칸을 먹었다.
  // 앞 13개 추가, 낱말 전체가 어미면 버린다.
  const VERB_TAIL = /(하려면|하려고|하려는|하는데|하는지|해야|한다|해서|하기|하나요|하나|했나|할까|하고|하는|하며|하여|되는|되어|하면|합니다|입니까|인지)$/;
  // 끝줄(알려줘·찾아줘·보여줘·설명해줘·다른가·무엇인가) = 요청·질문 말투(#244). 조사를 떼기 전 원래 낱말로도 검사한다 —
  // '다른가'·'무엇인가'는 조사 '가'가 먼저 떨어져 '다른'·'무엇인'이 되므로 뗀 뒤에만 보면 걸리지 않는다.
  const KW_STOPWORDS = ['이','가','은','는','을','를','의','에','에서','으로','로','과','와','도',
    '만','그','이것','저것','그것','있다','없다','하다','되다','이다','어떻게','어떤',
    '무엇','언제','어디','왜','누가','대해','관해','통해','위해','따라','대한','관한',
    '통한','위한','있는','없는','하는','되는','인','이란','이라는','라는','라고',
    '이고','이며','하고','이나','또는','그리고','하지만','그러나','따라서',
    '알려줘','찾아줘','보여줘','설명해줘','다른가','무엇인가'];
  // 조사 어미 제거 (예: "면허세에" → "면허세") — 잘린 어간도 ilike 부분일치로 검색됨
  const KW_JOSA = /(에서는|으로는|에서의|이라는|에서도|에서|에는|으로|로는|보다|부터|까지|처럼|마다|조차|밖에|은|는|이|가|을|를|의|에|와|과|도|만)$/;
  // 순서: ① 원래 낱말이 제외어면 버림 ② 용언 어미가 붙어 있으면 어미부터 뗀다(#244) — 조사를 먼저 떼면 '운영하는'이 '는'만
  // 떨어진 '운영하', '취소하는'이 '취소하'로 남아 「자율심의기구등을 운영하는 자」 같은 무관 조문을 끌어왔다(A/B 실측)
  // ③ 어미가 없으면 조사를 뗀다 ④ 남은 어미를 한 번 더 떼고, 낱말 전체가 어미였으면('해야'·'한다') 버린다.
  // ⚠️ '관련'·'절차'·'경우' 같은 상투어를 여기서 버리지 말 것(#244 A/B 기각) — 버린 자리만큼 대응표·확장어가 키워드 10칸 안으로
  // 들어와 조문 정밀검색 5칸 경쟁을 바꾼다(「3G종료 관련 법 조항」에서 전파법 제25조의2가 빠졌다). 상투어는 isTitleStop이 막는다.
  function extractKeywords(text) {
    const words = String(text || '').split(/[\s,.·()[\]「」『』<>:;!?]+/)
      .map(function (w) { return w.replace(/[^가-힣a-zA-Z0-9.]/g, '').trim(); })
      .filter(function (w) { return !KW_STOPWORDS.includes(w); })
      .map(function (w) {
        const t = w.replace(VERB_TAIL, '');
        if (t !== w && t.length >= 2) return t;
        const s = w.replace(KW_JOSA, ''); return s.length >= 2 ? s : w;
      })
      .map(function (w) { const s = w.replace(VERB_TAIL, ''); if (s.length === 0) return ''; return s.length >= 2 ? s : w; })
      .filter(function (w) { return w.length >= 2 && !KW_STOPWORDS.includes(w); });
    const pri = words.filter(function (w) { return PRIORITY_KW_RE.test(w); });
    const all = pri.concat(words.filter(function (w) { return !pri.includes(w); }));
    return all.filter(function (v, i, a) { return a.indexOf(v) === i; }).slice(0, 5);
  }

  // ── 정책 어휘 → 법령 조문 표제어 대응표 ─────────────────────────────────
  // LLM 확장만으로는 이 간극을 못 넘는다(실측: Haiku·Sonnet 모두 "3G 종료"에서 '휴업·폐업'을 못 냄).
  // 법은 '서비스 종료'라 쓰지 않는다 — 전기통신사업법은 '휴업·폐업', 전파법은 '폐지·운용휴지'다.
  const LAW_SYNONYMS = {
    '종료': ['휴업', '폐업', '폐지', '휴지', '운용휴지'],
    '중단': ['휴업', '휴지', '정지', '중지'],
    '폐지': ['폐업', '폐지', '휴지'],
    '개시': ['개설', '허가', '등록', '신고'],
    '시작': ['개설', '허가', '등록'],
    '변경': ['변경허가', '변경등록', '변경신고'],
    '취소': ['취소', '정지', '철회'],
    '반납': ['반납', '회수', '재할당'],
    // #244: 조문 제목은 '사업의 휴업ㆍ폐업'처럼 둘을 함께 쓴다 — 한쪽만 물어도 양쪽 제목에 걸리게(사전 출신 가중 7).
    // A/B: 「기간통신사업 폐업」에 전기통신사업법 시행령 제24조(휴업 등의 승인 신청)가 새로 들어왔다.
    '폐업': ['휴업', '폐업'],
    '휴업': ['휴업', '폐업'],
  };
  // ── 실무 용어 → 법령 용어 (#83) ───────────────────────────────────────────
  //  임베딩 모델은 한국어 법령으로 학습돼 업계에서만 쓰는 외래어를 조문에 연결하지 못한다.
  //  실측: 「리파밍」을 원문 그대로 임베딩하면 1위가 약관규제법(0.441)이고, 법령 용어로 보강하면 전파법 제6조의2(0.541).
  //  확신하는 대응만 넣을 것 — 틀린 대응은 엉뚱한 조문을 1위로 올려 없느니만 못하다.
  const PRACTICE_TERMS = [
    [/리파밍|리파-밍|re-?farming/i, ['주파수회수', '주파수재배치', '주파수 회수', '주파수 재배치']],
    [/커버리지|coverage/i,          ['이용가능 지역', '서비스 제공 지역']],
    [/주파수\s*경매|경매/,           ['대가에 의한 주파수할당', '주파수할당']],
    [/알뜰폰|MVNO/i,                ['도매제공', '도매제공의무사업자']],
    [/재할당/,                      ['주파수할당', '이용기간']],
    // 세대 서비스 종료(2G·3G…) → 주파수 처리 조문 보강 (2026-08-07)
    [/(2G|3G|4G|5G|LTE|WCDMA|세대)\s*(이동통신|서비스)?\s*종료/i, ['주파수회수', '주파수할당의 취소', '이용기간']],
    // 기관명 별칭 (#154): 방송통신위원회 → 방송미디어통신위원회 개편. 옛 고시·보도자료·회의록 본문은 옛 이름,
    // 2026년 고시·법령명은 새 이름이라 어느 쪽으로 물어도 양쪽이 잡혀야 한다. 다음 개편 때는 여기 한 줄만 더한다.
    [/방송미디어통신위원회|방송통신위원회|방미통위|방통위/, ['방송통신위원회', '방통위', '방송미디어통신위원회', '방미통위']],
    // 유통·이용자보호 어휘(#173): 질문은 '차별·다르게'라 쓰고 법은 '금지행위·부당한 이용자 차별'이라 쓴다.
    // 한 단어가 아니라 조합으로 발동(설비 제공 차별 질문에 이용자 차별 조문이 끌려오지 않도록).
    [/지원금.{0,12}(차별|다르게|차등)|(차별|다르게|차등).{0,12}지원금/, ['지원금의 차별 지급 금지', '금지행위', '부당한 이용자 차별']],
    [/이용자.{0,12}(차별|다르게|차등)|(차별|차등).{0,12}이용자/, ['금지행위', '부당한 이용자 차별', '이용자의 이익']],
    [/장려금|인건비|임대료|판촉비|인센티브|실적수당|리베이트/, ['공정한 유통 환경 조성', '장려금', '금지행위']],
    [/대리점|판매점|유통점|직영/, ['대리점', '판매점', '판매점 선임에 대한 승낙', '공정한 유통 환경 조성']],
    [/추가지원금|공시지원금|공통지원금|보조금/, ['지원금', '지원금의 차별 지급 금지']],
  ];
  // 질문에 정책 동사·실무 용어가 있으면 대응하는 법령 표제어를 돌려준다 (검색 키워드에 추가 투입용)
  function lawSynonymKeywords(query) {
    const q = String(query || '');
    const out = [];
    Object.keys(LAW_SYNONYMS).forEach(function (k) {
      if (q.indexOf(k) >= 0) LAW_SYNONYMS[k].forEach(function (s) { if (out.indexOf(s) === -1) out.push(s); });
    });
    PRACTICE_TERMS.forEach(function (pair) {
      if (pair[0].test(q)) pair[1].forEach(function (t) { if (out.indexOf(t) === -1) out.push(t); });
    });
    return out;
  }
  // 시맨틱 검색용 질의 보강 — 원 질의는 지우지 않고 뒤에 덧붙인다(원 표현이 맞는 경우를 잃지 않도록)
  function expandQueryForSemantic(query) {
    const q = String(query || '');
    const add = [];
    PRACTICE_TERMS.forEach(function (pair) {
      if (pair[0].test(q)) pair[1].forEach(function (t) { if (add.indexOf(t) === -1) add.push(t); });
    });
    return add.length ? (q + ' ' + add.join(' ')) : q;
  }

  // ── 제외어·위계·도메인 ───────────────────────────────────────────────────
  // 질문 상투어 — 조문 제목 가점·주제 매칭에서 제외 ('절차'가 「규제심사 절차」 같은 무관 조문 제목에 걸려 상위를 차지하는 것 방지)
  // 뒤 7개(#244): '다른'이 「다른 법령과의 관계」 제목 가점을 받는 등. 키워드 추출에서는 버리지 않는다(extractKeywords 주석).
  const GENERIC_QUERY_WORDS = ['방법', '방안', '절차', '하는', '관련', '대한', '다른', '같은', '이런', '그런', '경우', '내용', '사항'];
  // 제목 가점·키워드 조회 제외어(#173) — 두 글자 일반어('직접'·'실적'·'시스템')가 조문 제목에 우연히 있으면 행위어 가중을 받아
  // 무관 법령이 정밀검색 상위를 차지했다. 글자 수 규칙이 아니라 목록이다 — 검사·할당·면허 같은 두 글자 법령 행위어는
  // 계속 가점을 받아야 한다. 표제어 사전(LAW_SYNONYMS·PRACTICE_TERMS) 출신 단어는 예외(isTitleStop).
  const QUERY_TITLE_STOP = GENERIC_QUERY_WORDS.concat(['직접', '운영', '지급', '지원', '공식', '주체', '제공', '이용', '사용', '관리', '기준', '대상', '내용', '경우', '필요', '가능', '여부', '포함', '위반', '규정', '조항', '법령', '법률', '사항', '업무', '기관', '정부', '회사', '사업', '서비스', '시스템', '개선', '요구', '의무', '비용', '추가', '현재', '기존', '정책', '제도', '문제', '질문', '분석', '검토', '해당', '적용', '가입', '조건', '실적', '목표', '개인', '차원', '역할', '직원', '정규', '소속', '통신사', '이통사', '기반', '기본', '체계', '구조', '방식', '형태', '단계', '수준', '범위', '주요', '전체', '일부', '최대', '최소', '이상', '이하', '이후', '이전', '별도', '자체', '본인', '상대', '타인']);
  function isTitleStop(kw, query) {
    if (QUERY_TITLE_STOP.indexOf(kw) === -1) return false;
    const norm = kw.replace(/\s+/g, '').toLowerCase();
    return !lawSynonymKeywords(query).some(function (s) { return s.replace(/\s+/g, '').toLowerCase() === norm; });
  }
  // 법령 위계 (동점 정렬용): 법률 > 대통령령 > 부령·총리령 > 고시·훈령 등
  function lawRank(docName) {
    const d = docName || '';
    if (/\(법률\)/.test(d)) return 4;
    if (/\(대통령령\)/.test(d)) return 3;
    if (/(부령|총리령)\)/.test(d)) return 2;
    return 1;
  }
  // 도메인 사전확률: 이 KB는 전파·통신 정책용이라, 행위·주제 점수가 같으면 전파·통신 계열 법령이
  // 국가재정법·위치정보법 같은 부수 수록 문서보다 근거일 확률이 높다 (질문과 무관한 상수 가점)
  const DOMAIN_DOC_RE = /전파|통신|무선|주파수/;

  // ── 뉴스 전용 키워드 추출 — 위 extractKeywords(법령 검색용)와 반드시 분리 ──────
  // 여기 불용어('통신사','영향','분석' 등)를 extractKeywords에 넣으면 법령 RAG 검색 품질이 함께 망가진다.
  // (사고: "같은 지하철인데 통신사 와이파이 속도…" 질문에서 키워드가 '같은/지하철인데/통신사'로 뽑혀 정작 질문이
  //  인용한 기사 본문이 프롬프트에 못 들어갔음 — '인데'가 조사 목록에 없어 0건)
  // 2026-09-25 통일(운영자 결정): 불용어·분야어는 대시보드판(2026-07-30)과 봇판(2026-08-01)의 합집합, 분야어 밖 단어는
  // 대시보드판대로 긴 단어 먼저(더 구체적인 낱말이 6개 상한 안에 남도록).
  const NEWS_STOPWORDS = ['같은','같이','최대','최소','정도','이유','영향','분석','분석해','분석해줘','차이',
    '통신사','통신','관련','현황','상황','내용','문제','방법','방안','대응','전망','의미','비교','평가','수준','규모',
    '최근','요즘','지금','현재','올해','작년','국내','해외','업계','우리','회사','부분','경우','전체',
    '해줘','알려줘','설명','설명해줘','정리','정리해줘','작성','검토','어떻게','어떤','무엇','언제','어디','왜',
    '있다','없다','하다','되다','이다','대해','관해','통해','위해','따라','대한','관한','그리고','하지만'];
  // 조사·어미 (extractKeywords보다 넓게 — 뉴스 질문 말투를 벗긴다: "지하철인데" → "지하철")
  const NEWS_TAIL = /(이라는데|이라는|이라며|이라고|인데도|에서는|으로는|에서의|에서도|라는데|인데|인가|인지|라며|라고|는데|에서|에는|으로|로는|보다|부터|까지|처럼|마다|조차|밖에|이나|나는|은|는|이|가|을|를|의|에|와|과|도|만)$/;
  // 통신·전파 도메인어 — 우선순위 부여 + 조사 절단 보호에 함께 쓴다
  const NEWS_DOMAIN_RE = /주파수|대역|백홀|기지국|중계기|와이파이|WiFi|5G|6G|3G|2G|LTE|위성|전파|간섭|품질평가|재할당|할당|요금|보조금|단말|로밍|알뜰폰|MVNO|망중립|해킹|유출|과징금|지하철|철도|국회|고시|시행령|입법예고|종료|폐지|휴지|IoT/i;
  function extractNewsKeywords(text) {
    const words = String(text || '').split(/[\s,.·()[\]「」『』<>:;!?"']+/)
      .map(function (w) { return w.replace(/[^가-힣a-zA-Z0-9]/g, '').trim(); })
      .map(function (w) {
        const s = w.replace(NEWS_TAIL, '');
        if (NEWS_DOMAIN_RE.test(s)) return s;     // "지하철인데"→"지하철", "와이파이에서는"→"와이파이"
        if (NEWS_DOMAIN_RE.test(w)) return w;     // "와이파이"의 끝 '이'를 조사로 오인해 자르는 것 방지
        return s.length >= 2 ? s : w;
      })
      .filter(function (w) { return w.length >= 2 && NEWS_STOPWORDS.indexOf(w) === -1; });
    const uniq = words.filter(function (v, i, a) { return a.indexOf(v) === i; });
    const pri = uniq.filter(function (w) { return NEWS_DOMAIN_RE.test(w); });
    const rest = uniq.filter(function (w) { return !NEWS_DOMAIN_RE.test(w); })
      .sort(function (a, b) { return b.length - a.length; });
    return pri.concat(rest).slice(0, 6);
  }

  // ── 상한 상수 ───────────────────────────────────────────────────────────
  // 문서당 청크 상한 (doc_category별 차등): '추가지식' = 운영자가 일부러 넣은 논문·근거메모 → 8청크까지 깊게 참고
  // (일괄 3에서는 표지·방법론만 잡히고 핵심 결론이 컷 밖으로 밀리는 실측). 그 외 = 3 (한 문서 독식 방지).
  const PERDOC_LIMIT = { '추가지식': 8, 'default': 3 };
  // 전체 상위 컷 12→15: 추가지식 1편이 8을 차지해도 다른 문서 몫이 7 남게.
  const TOTAL_CHUNK_CUT = 15;
  // 자문 스트림 무수신 한도(ms) — '전체 시간'이 아니라 '한 조각도 안 오는 시간'. 3분(#205, B-7).
  const STREAM_IDLE_MS = 180000;
  // 인용 조문 통째 보강(#155) / 역참조 발췌(#155-보론4) 상한 — cite_verify.js expandArticles·buildCitingExcerpts에 넘긴다
  const EXPAND_OPTS = { maxArticles: 10, maxChunksPerArticle: 4, maxAddedChunks: 14 };
  const CITING_OPTS = { maxPerArticle: 4, maxTotal: 8, maxLen: 300 };
  // 별표 동반 인출(#90): 질문당 별표 개수 / 별표당 청크 (별표 하나가 최대 812청크라 상한 필수)
  const ANNEX_MAX_UNITS = 2;
  const ANNEX_MAX_CHUNKS = 6;
  // 국회 발언 희소어 상한 — assembly_speeches 약 1,100건 기준(≈4%)
  const ASM_RARE_MAX = 40;

  // ── 3중 하이브리드 융합 순위 (RRF) ────────────────────────────────────────
  // 종전(배경역사 #23)에는 키워드 정규화(0~1)+trgm(0.12~0.5)+시맨틱×2(0.9~1.5)를 그대로 합산해 척도가 다른 점수끼리
  // 싸웠다(시맨틱 상위=논문이어도 합산 우승). 각 검색을 '순위'로 환산해 1/(K+순위) 합으로 융합하면 척도 문제가
  // 사라진다(K=60 관례) — 점수 크기가 아니라 "몇 개의 검색에서 얼마나 상위였나"가 결정한다.
  // 입력: results = 키워드·trgm·시맨틱 결과를 id로 합친 청크 배열(_trgm_score·_semantic_score는 호출측이 채움),
  //       keywords = 최종 키워드(앞 10개만 씀), baseKeywords = 질문에서 직접 뽑은 키워드(가중 2), query = 원 질문.
  // 출력: 문서당 상한(PERDOC_LIMIT)·전체 상한(TOTAL_CHUNK_CUT)을 적용한 채택 청크 배열(순위순). results의 _score·_hybrid_score를 채운다.
  const RRF_K = 60;
  const RRF_UNIT = 0.5 / (RRF_K + 1);
  const FILE_DOC_RE = /\.(pdf|md|docx|hwp)$/i;
  // article_no는 종류별 등급이다(#90): 실DB에서 article_no 보유 18,349개 중 조문은 41%(7,587)뿐이고 별표 5,538·부칙 1,704·
  // 별지 1,421·붙임 1,191·서식 908이 동급이었다. 별표·붙임은 배제가 아니라 가점만 뗀다(#88과 같은 원칙).
  function articleBonus(art) {
    if (!art) return 0;                                 // 보도자료·회의록 — 가점 없음(감점도 없음)
    if (/^\d+조/.test(art)) return RRF_UNIT;            // 조문
    if (/^(별표|붙임)/.test(art)) return 0;              // 표·부속 — 중립
    if (/^(부칙|서식|별지)/.test(art)) return -RRF_UNIT; // 개정 이력·서식
    return 0;
  }
  function rankChunks(results, keywords, baseKeywords, query) {
    const kws = (keywords || []).slice(0, 10);
    const base = baseKeywords || [];
    const synNormSet = new Set(lawSynonymKeywords(query).map(function (s) { return s.toLowerCase(); }));
    results.forEach(function (r) {
      let score = 0;
      kws.forEach(function (kwRaw) {
        const kw = kwRaw.toLowerCase();
        const w = base.includes(kwRaw) ? 2 : 1;
        if ((r.content || '').toLowerCase().includes(kw)) score += w;
        if ((r.doc_name || '').toLowerCase().includes(kw)) score += w;
        // 조문 표제어 일치는 결정적 신호. 단 '절차' 같은 질문 상투어는 제외 — 「규제심사 절차」 같은 무관 조문이 올라온다(실측).
        // 표제어 대응표(LAW_SYNONYMS) 출신 행위어는 더 크게: 법령이 실제 쓰는 어휘로 번역된 말이라 원어 그대로의
        // 우연 일치('조난통신 종료')보다 신뢰도가 높다.
        if ((r.article_no || '').toLowerCase().includes(kw) && !isTitleStop(kwRaw, query)) {
          score += synNormSet.has(kw) ? 4 : w * 2;
        }
      });
      r._score = score;          // RRF 순위 산출용 (절대값은 융합에 안 쓴다)
      r._hybrid_score = 0;
    });
    const addRrf = function (list) {
      list.forEach(function (r, idx) { r._hybrid_score += 1 / (RRF_K + idx + 1); });
    };
    addRrf(results.filter(function (r) { return (r._score || 0) > 0; })
      .slice().sort(function (a, b) { return b._score - a._score; }));
    addRrf(results.filter(function (r) { return (r._trgm_score || 0) > 0; })
      .slice().sort(function (a, b) { return b._trgm_score - a._trgm_score; }));
    addRrf(results.filter(function (r) { return (r._semantic_score || 0) > 0; })
      .slice().sort(function (a, b) { return b._semantic_score - a._semantic_score; }));
    // 일반 가점·감점: 조문번호 있는 청크 = 법령·고시 원문 → 가점 / 파일 확장자 문서(.pdf/.md 등) → 감점
    // (doc_category '기타'에 고시와 박사논문이 섞여 카테고리로는 못 거른다). 크기 0.5/(K+1) = 목록 1개 1위 기여의 절반.
    // 파일 감점은 분류를 가리지 않는다 — 도입(08-02) 때 겨냥한 것은 '기타'의 논문·계획서류였지만 이슈사례·회의록·보도자료·
    // ITU-R·해외동향 .md/.pdf에도 걸린다. '기타'만으로 좁히는 안은 A/B로 기각(#244): 상위 15칸의 조문이 15~21% 줄고
    // 회의록·보도자료가 그 자리를 차지했다(나빠짐 5·좋아짐 0). 이슈사례만 빼는 안도 나빠짐 2. 감점을 받고도 이슈사례는 들어온다.
    results.forEach(function (r) {
      r._hybrid_score += articleBonus(r.article_no);
      if (FILE_DOC_RE.test(r.doc_name || '')) r._hybrid_score -= RRF_UNIT;
    });
    results.sort(function (a, b) { return b._hybrid_score - a._hybrid_score; });
    const perDocCount = {};
    const picked = [];
    for (let pi = 0; pi < results.length && picked.length < TOTAL_CHUNK_CUT; pi++) {
      const dn = results[pi].doc_name || '';
      const cap = PERDOC_LIMIT[results[pi].doc_category || ''] || PERDOC_LIMIT['default'];
      perDocCount[dn] = (perDocCount[dn] || 0) + 1;
      if (perDocCount[dn] <= cap) picked.push(results[pi]);
    }
    return picked;
  }

  // ── 조문 정밀검색의 순수 부분 ────────────────────────────────────────────
  // 점수는 '행위'와 '주제'를 분리해 매긴다(실측으로 도달한 구조). 행위 = 폐업·휴지 같은 조문 표제어 → 조문 제목에 걸리면
  // 결정적. 주제 = 기간통신사업·무선국 같은 대상 → 문서명·조문제목에 걸리면 가산. 둘을 합치지 않는 이유: 주제만 맞는
  // 문서(기간통신사업 양수·합병 고시)가 행위가 맞는 조문(전기통신사업법 19조 사업의 휴업·폐업)을 밀어내는 일이 있었다.
  // titleActWeights: 조회에 쓸 키워드(제외어 뺌)와 각 키워드의 행위 가중 — LAW_SYNONYMS 출신(정책어→법령표제어로 '번역'된
  // 말, 예: 종료→휴업·폐업)은 7, 그 외(질문 원어·LLM 확장)는 5. 원어가 조문 제목에 우연히 있는 경우('조난통신 종료 통보')는
  // 대개 다른 제도라 번역된 표제어보다 낮게 본다. (실측: 이 차등이 없으면 "3G 종료"에서 선박국 운용종료·조난통신 조문이
  // 전기통신사업법 19조·전파법 25조의2를 밀어낸다)
  function titleActWeights(keywords, query) {
    const synNorms = new Set(lawSynonymKeywords(query).map(function (s) { return s.replace(/\s+/g, '').toLowerCase(); }));
    const kwActive = [], actOf = [];
    (keywords || []).slice(0, 10).forEach(function (kw) {
      if (isTitleStop(kw, query)) return;   // 제외어(#173)는 제목·본문 조회 모두 생략 — 행위 가중 0이면 주제 점수만 남아 순위에 못 든다
      kwActive.push(kw);
      actOf.push(synNorms.has(kw.replace(/\s+/g, '').toLowerCase()) ? 7 : 5);
    });
    return { kwActive: kwActive, actOf: actOf };
  }
  // rankLawHits: 후보 조문(_act = 행위 가중, 호출측이 RPC 결과로 채움)에 주제 점수를 더해 정렬·대표 1건·상한.
  // 주제 일치는 부분문자열로 본다 — '기간통신사업'과 '전기통신사업법'은 앞글자가 달라 접두 비교로는 안 잡히고
  // '통신사업'이라는 공통 조각으로만 이어진다. 정렬: 점수 → 법령 위계 → 문서명·조문번호(결정적 순서).
  function rankLawHits(hits, query, limit) {
    const topics = (String(query || '').match(/[가-힣A-Za-z0-9]{2,}/g) || [])
      .filter(function (t) { return GENERIC_QUERY_WORDS.indexOf(t) === -1; });
    const arr = Array.from(hits);
    arr.forEach(function (h) {
      const hay = h.doc_name + ' ' + (h.article_no || '');
      let best = 0;
      topics.forEach(function (t) {
        if (t.length <= 3) { if (hay.indexOf(t) >= 0 && t.length > best) best = t.length; return; }
        for (let i = 0; i < t.length; i++) {
          for (let j = t.length; j - i >= 4; j--) {
            if (hay.indexOf(t.slice(i, j)) >= 0) { if (j - i > best) best = j - i; break; }
          }
        }
      });
      h._top = best;
      // 행위를 우선하되 주제로 갈래를 좁히고, 동점은 도메인(전파·통신 계열) 문서를 앞세운다
      h._hits = h._act * 2 + best + (DOMAIN_DOC_RE.test(h.doc_name) ? 1 : 0);
    });
    arr.sort(function (a, b) {
      if (b._hits !== a._hits) return b._hits - a._hits;
      const lr = lawRank(b.doc_name) - lawRank(a.doc_name);
      if (lr !== 0) return lr;
      if (a.doc_name !== b.doc_name) return a.doc_name < b.doc_name ? -1 : 1;
      return (a.article_no || '') < (b.article_no || '') ? -1 : 1;
    });
    // 같은 조문이 여러 청크로 쪼개져 있으면 대표 1건만 — 목록이 중복으로 채워지는 것 방지
    const byArticle = new Map();
    arr.forEach(function (h) {
      const key = h.doc_name + '|' + (h.article_no || '');
      if (!byArticle.has(key)) byArticle.set(key, h);
    });
    return Array.from(byArticle.values()).slice(0, limit || 5);
  }

  // ── 번호로 지목한 조문 직접 인출 (#245, 2026-09-27) ─────────────────────────
  // 「전파법 제16조」처럼 법령명과 조 번호를 적은 질문이 그 조문을 못 가져왔다(#244 곁가지 — 확장어 있음·없음 두 조건 모두).
  // DB 조문 제목은 '16조(재할당)'처럼 '제'가 없어(#92) 키워드 '제16조'가 목표 조문 제목에 걸리지 않고, 다른 법령 별표의
  // '별표 3 (제16조 관련)'에 걸려 정밀검색 5칸을 별표가 차지했다. 본문 검색에서는 「전파법」 제16조를 **인용하는** 다른 문서가
  // '전파법'·'제16조'를 둘 다 담아 이긴다 — 조문 자신은 본문에 제 법령 이름을 쓰지 않는다. 점수를 고쳐 이기게 하는 대신
  // 봇 /law 조문 즉답처럼 이름과 번호로 직접 가져온다. 법령명 읽기(lawNameBefore)·동법/시행령 이어받기·이름 맞추기(lawScope)는
  // 인용 검증기(cite_verify.js, #240)와 같은 함수를 쓴다 — 질문 속 인용과 답변 속 인용을 같은 규칙으로 읽는다.
  // 법령 이름이 앞에 전혀 없는 '제16조'는 고르지 않는다(현행 문서 130여 개에 16조가 있다).
  const NAMED_ARTICLE_MAX = 4;
  // '제'는 생략 가능('전기통신사업법 37조'). 금액('3조 원'·'2조5천억')은 뒤 낱말로 거른다 — 앞에 법령명이 없으면 어차피 버린다.
  const NAMED_ART_RE = /(?:제\s?)?(\d+)\s?조(?:\s?의\s?(\d+))?(?!\s?(?:\d+\s?(?:천|백|억|만)|원|억|천|만|달러))/g;
  // 질문에서 조 언급을 등장 순서대로 — {key:'16조'|'16조의2', info: 바로 앞 법령명(lawNameBefore), ctx: 앞서 이름이 나온 법령}.
  // 법령명도 앞선 법령도 없는 언급은 뺀다. CiteVerify가 없는 환경(사내 콘솔 등)에서는 빈 배열.
  function namedArticleRefs(query) {
    const CV = root.CiteVerify;
    if (!CV) return [];
    const s = String(query || '');
    const refs = [];
    let lastNamed = null, m;
    NAMED_ART_RE.lastIndex = 0;
    while ((m = NAMED_ART_RE.exec(s))) {
      const info = CV.lawNameBefore(s.slice(0, m.index));
      if (info || lastNamed) refs.push({ key: m[1] + '조' + (m[2] ? '의' + m[2] : ''), info: info, ctx: lastNamed });
      if (info && info.candidates) lastNamed = info;
    }
    return refs;
  }
  // 언급마다 문서 하나를 고른다. rowsByKey = {key: [{doc_name, article_no}]} — 그 번호의 조문을 가진 현행 문서(호출측 조회).
  // 이름 맞추기 대상(문서군)은 '요청한 번호의 조문을 가진 문서'로 한정한다 — 조문이 없는 법령에 붙을 일이 없다.
  // '시행령 제18조'·'동법 제17조'는 앞서 이름이 나온 법령이 있을 때만(없으면 아무 시행령에나 붙는다).
  function pickNamedArticles(refs, rowsByKey) {
    const CV = root.CiteVerify;
    if (!CV) return [];
    const famsOf = {}, docOf = {}, all = [];
    Object.keys(rowsByKey || {}).forEach(function (key) {
      const fams = famsOf[key] = [];
      (rowsByKey[key] || []).forEach(function (r) {
        if (!r || FILE_DOC_RE.test(r.doc_name || '') || CV.articleKey(r.article_no) !== key) return;
        const f = CV.docFamily(r.doc_name);
        if (!f) return;
        if (fams.indexOf(f) === -1) fams.push(f);
        if (all.indexOf(f) === -1) all.push(f);
        if (!docOf[f] || r.doc_name > docOf[f]) docOf[f] = r.doc_name;   // 같은 이름이 여럿이면 문서명 끝 시행일이 늦은 쪽
      });
    });
    const out = [], seen = {};
    (refs || []).forEach(function (ref) {
      if (out.length >= NAMED_ARTICLE_MAX || !famsOf[ref.key] || !famsOf[ref.key].length) return;
      if (!ref.info && !ref.ctx) return;
      if (ref.info && (ref.info.subord || ref.info.inherit) && !(ref.ctx && ref.ctx.candidates)) return;
      const scope = CV.lawScope(ref.info, ref.ctx, all);
      if (!scope) return;   // null = 법령 미상(어느 문서든) — 번호만으로는 고르지 않는다
      const fam = scope.find(function (f) { return famsOf[ref.key].indexOf(f) !== -1; });
      if (!fam) return;
      const k = docOf[fam] + '|' + ref.key;
      if (seen[k]) return;
      seen[k] = 1;
      out.push({ doc_name: docOf[fam], key: ref.key });
    });
    return out;
  }
  // 조회까지 — fetchKeyRows(key) → [{doc_name, article_no}], fetchArticle(doc_name, key) → 그 조의 조각들(expandArticles와 같은 함수).
  // 반환: 고른 조문마다 **첫 조각 하나**(조문 머리 '제16조(재할당) ①…'), 질문의 언급 순. 나머지 조각은 호출측의 통째 보강
  // (CiteVerify.expandArticles)이 이 조각에 합친다 — 조각을 전부 넣으면 보강이 '이미 다 있다'며 건너뛰어 한 조문이 여러 칸으로
  // 갈라진다(첫 A/B 실측: [조문 1]·[조문 2]가 같은 제16조). 조회 실패는 빈 배열(검색은 그대로 진행).
  async function fetchNamedArticles(query, fetchKeyRows, fetchArticle) {
    const CV = root.CiteVerify;
    const refs = namedArticleRefs(query);
    if (!CV || !refs.length) return [];
    const keys = [];
    refs.forEach(function (r) { if (keys.indexOf(r.key) === -1 && keys.length < NAMED_ARTICLE_MAX) keys.push(r.key); });
    const soft = function (fn) { return Promise.resolve().then(fn).then(function (r) { return r || []; }, function () { return []; }); };
    const rows = await Promise.all(keys.map(function (k) { return soft(function () { return fetchKeyRows(k); }); }));
    const rowsByKey = {};
    keys.forEach(function (k, i) { rowsByKey[k] = rows[i]; });
    const picks = pickNamedArticles(refs, rowsByKey);
    const got = await Promise.all(picks.map(function (p) { return soft(function () { return fetchArticle(p.doc_name, p.key); }); }));
    const out = [];
    picks.forEach(function (p, i) {
      const rows = got[i].filter(function (r) { return r && r.doc_name === p.doc_name && CV.articleKey(r.article_no) === p.key; })
        .sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
      if (rows.length) out.push(Object.assign({}, rows[0], { _named: true }));
    });
    return out;
  }

  // ── 프롬프트 컨텍스트 문구 ─────────────────────────────────────────────
  // 조문 참조 블록. 2026-09-25 통일(운영자 결정): 대시보드가 6월부터 붙이던 "(시맨틱: NN%)" 점수 표기는 뺀다 —
  // 참조 순서 자체가 융합 점수순이고, 점수는 trgm·시맨틱으로 잡힌 조각에만 붙어 키워드로 잡힌 조각이 약해 보이는 편향이 있었다.
  function buildRagContext(chunks) {
    if (!chunks || chunks.length === 0) return '';
    const items = chunks.map(function (c, i) {
      const meta = [];
      if (c.article_no) meta.push('조항: ' + c.article_no);
      if (c.notice_no) meta.push('고시번호: ' + c.notice_no);
      // 보도자료는 effective_date가 '발표일'이다(#155-보론2) — 시행일이라 적으면 모델이 제도 시행일로 오독한다
      if (c.effective_date) meta.push((/보도자료/.test(c.doc_category || '') ? '발표일: ' : '시행일: ') + c.effective_date);
      const metaStr = meta.length ? ' [' + meta.join(' | ') + ']' : '';
      return '[참조 ' + (i + 1) + '] 출처: ' + c.doc_name + ' (' + (c.doc_category || '') + ')' + metaStr + '\n' + c.content;
    });
    return '\n\n---\n\n[RAG 검색 결과 — 질문과 관련된 실제 법령·고시 원문]\n아래 내용은 질문과 의미적으로 유사한 문서 청크를 검색한 결과입니다. 반드시 아래 원문을 최우선으로 인용하고, 조항 번호와 내용이 일치하는지 확인하여 답변하세요:\n\n' + items.join('\n\n---\n\n');
  }
  // 법령요약(kb_chunks) 블록. 2026-09-25 통일: 대시보드판 지시문(3문장)으로 — 봇판은 1문장으로 줄여 적혀 있었다.
  function buildKbContext(rows) {
    if (!rows || rows.length === 0) return '';
    const items = rows.map(function (r, i) {
      const meta = [];
      if (r.law_type) meta.push(r.law_type);
      if (r.law_number) meta.push('법령번호: ' + r.law_number);
      if (r.enforcement_date) meta.push('시행일: ' + r.enforcement_date);
      const metaStr = meta.length ? ' [' + meta.join(' | ') + ']' : '';
      return '[법령요약 ' + (i + 1) + '] ' + (r.title || '') + metaStr + '\n' + (r.content || '');
    });
    return '\n\n---\n\n[법령·규제 요약 지식베이스 — 현행 법령·고시·훈령 요약/실무]\n' +
      '아래는 우리 팀이 정리한 법령·고시·훈령의 요약·적용범위·실무 체크리스트·소관부처 문서(현행본)입니다. ' +
      '법의 취지·실무 대응·담당부처를 물을 때 활용하세요. ' +
      '단, 정확한 조문 번호·문구 인용은 위 RAG 조문 원문을 최우선으로 하고, 이 요약은 실무 맥락 보강용으로 쓰세요:\n\n' +
      items.join('\n\n---\n\n');
  }

  const RagCore = {
    PRIORITY_KW_RE: PRIORITY_KW_RE, VERB_TAIL: VERB_TAIL, extractKeywords: extractKeywords,
    LAW_SYNONYMS: LAW_SYNONYMS, PRACTICE_TERMS: PRACTICE_TERMS,
    lawSynonymKeywords: lawSynonymKeywords, expandQueryForSemantic: expandQueryForSemantic,
    GENERIC_QUERY_WORDS: GENERIC_QUERY_WORDS, QUERY_TITLE_STOP: QUERY_TITLE_STOP, isTitleStop: isTitleStop,
    lawRank: lawRank, DOMAIN_DOC_RE: DOMAIN_DOC_RE,
    extractNewsKeywords: extractNewsKeywords,
    PERDOC_LIMIT: PERDOC_LIMIT, TOTAL_CHUNK_CUT: TOTAL_CHUNK_CUT, STREAM_IDLE_MS: STREAM_IDLE_MS,
    EXPAND_OPTS: EXPAND_OPTS, CITING_OPTS: CITING_OPTS, ANNEX_MAX_UNITS: ANNEX_MAX_UNITS, ANNEX_MAX_CHUNKS: ANNEX_MAX_CHUNKS,
    ASM_RARE_MAX: ASM_RARE_MAX,
    RRF_K: RRF_K, articleBonus: articleBonus, rankChunks: rankChunks,
    titleActWeights: titleActWeights, rankLawHits: rankLawHits,
    NAMED_ARTICLE_MAX: NAMED_ARTICLE_MAX, namedArticleRefs: namedArticleRefs, pickNamedArticles: pickNamedArticles,
    fetchNamedArticles: fetchNamedArticles,
    buildRagContext: buildRagContext, buildKbContext: buildKbContext,
  };
  root.RagCore = RagCore;
  if (typeof module !== 'undefined' && module.exports) module.exports = RagCore;
})(typeof globalThis !== 'undefined' ? globalThis : this);
