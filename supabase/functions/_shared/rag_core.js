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
  // ── 법령 용어 동의어 (L5′, #289, 2026-10-07) ──────────────────────────────
  //  질문의 통용어 → 법령 원문 용어. 「재난대비 IDC 관련 규정은?」에서 Haiku 확장도 「집적정보통신시설」을 내지 못해
  //  집적정보 통신시설 보호지침·정보통신망법 제46조가 참조 자료에 하나도 안 들어왔다(자문 세 문제 준비자료 §2).
  //  위 두 표와 달리 **넣는 규칙이 있다**(Fable 판정 `local_docs/자문세문제_판정_261007.md` §12-3) — 쌍 a → b는 검증 세트 밖에서
  //  다음 중 하나로 증명될 때만: ① b가 법령·고시의 조문 제목·정의 조문에 있고 a가 b의 부분 문자열 ② 법령·고시 본문·별표가
  //  「b(a)」로 나란히 적음 ③ KB에 적재된 보도자료·정책문서가 「a(b)」·「b(a)」로 나란히 적음 — 이어서 두 단계까지.
  //  질문 글귀만 있는 쌍(「장비 세금 → 등록면허세」·「특수목적 예산 → 특별회계」·「차별 → 공평」)은 넣지 않는다(질문 해석은
  //  Haiku 확장 몫). 낱말 → 낱말만(조 번호·문서명 금지), 증명 조각을 줄마다 적는다.
  //  이 표 출신은 질문당 LAW_TERM_MAX개까지(위 두 표는 상한 없음 — 「3G 서비스 종료」는 8개, 그 기준선은 그대로 둔다).
  //  표제어는 공백을 지운 질문에서 찾고(「데이터 센터」), 두 글자 표제어는 질문 낱말(조사 뗀 것)과 완전히 같을 때만
  //  (「보관」⊂「정보관리」 같은 오발동). 출력은 lawSynonymKeywords 끝에 붙어 확장어보다 앞에 선다(아래 slice(0,10)에서
  //  잘리지 않게 — 개발 20문항엔 이 표가 걸리는 질문이 없어 앞·뒤 자리가 결과를 바꾸지 않는다, 측정 `local_docs/L5동의어_261007/`).
  //  ✗ 「보관 → 보관기간」: 판정 문서는 통신비밀보호법 시행령 제41조 제목이라 했으나 실제 제목은 「전기통신사업자의 협조의무 등」
  //    (보관기간은 ②항 본문)이고 「보관기간」을 제목·정의에 가진 조문이 KB에 없어 ①을 못 넘는다(10-07 실DB).
  const LAW_TERM_SYNONYMS = [
    // ③ 과기정통부_보도자료_2024·2025·2026.md(부가통신 실태조사 표) 「인터넷 데이터센터(IDC)」 → ② 아래 줄 — 두 단계
    ['IDC', ['집적정보통신시설']],
    // ② 주요통신사업자의 통신시설 등급 지정 및 관리 기준(과학기술정보통신부고시 제2026-12호) 별표 1 「4. 집적정보통신시설(데이터센터)」
    ['데이터센터', ['집적정보통신시설']],
    // ① 지방세법 제37조(이미 납부한 등록면허세에 대한 조치)·같은 법 시행령 제49조(등록면허세 납부 확인 등)·시행령 별표 1 제목
    ['면허세', ['등록면허세']],
  ];
  const LAW_TERM_MAX = 4;
  function termHeadHit(query, head) {
    if (head.length <= 2) {
      return String(query || '').split(/[\s,.·()[\]「」『』<>:;!?/]+/).some(function (w) {
        const t = w.replace(/[^가-힣a-zA-Z0-9]/g, '');
        return t === head || t.replace(KW_JOSA, '') === head;
      });
    }
    return String(query || '').replace(/\s+/g, '').toUpperCase().indexOf(head.toUpperCase()) >= 0;
  }
  // 법령 용어 동의어 표 출신만(상한 적용) — exclude(위 두 표가 낸 말)와 **질문에 이미 든 말**은 빼고 센다.
  // 질문에 든 말을 내면 그 말이 사전 출신 가중(rankChunks 4·titleActWeights 7)을 받아 조문 정밀검색만 흔든다
  // (「등록면허세는 연간 얼마」에서 면허세 → 등록면허세가 그랬다 — 세제 미니 세트 t01·t02 구성 변화, 10-07 측정). 이 표는 질문에 없는 법령 용어를 더하는 일만 한다.
  function lawTermKeywords(query, exclude) {
    const ex = exclude || [];
    const qn = String(query || '').replace(/\s+/g, '').toUpperCase();
    const out = [];
    LAW_TERM_SYNONYMS.forEach(function (pair) {
      if (termHeadHit(query, pair[0])) pair[1].forEach(function (t) {
        if (out.length < LAW_TERM_MAX && ex.indexOf(t) === -1 && out.indexOf(t) === -1 &&
            qn.indexOf(t.replace(/\s+/g, '').toUpperCase()) === -1) out.push(t);
      });
    });
    return out;
  }
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
    return out.concat(lawTermKeywords(q, out));
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
  // 금액 거르기는 '제'가 **없는** 번호에만 건다(#246-보론, 2026-09-27 사내 회신): 금액에는 '제'가 붙지 않는데, 종전에는 '제'가 있어도
  // 뒤의 '원'·'만'을 금액으로 봐서 「전파법 제16조 원문 보여줘」「제3조 원칙」「제50조 원인」「제16조만 보면」이 빈 배열이었다.
  // '제' 없는 번호도 원문·원칙·원인·원래·원본·원안은 금액이 아니다. '제' 없는 'N조만'은 금액('3조만 투자')과 못 가르므로 그대로 뺀다.
  const NAMED_ART_RE = /제\s?(\d+)\s?조(?:\s?의\s?(\d+))?|(\d+)\s?조(?:\s?의\s?(\d+))?(?!\s?(?:\d+\s?(?:천|백|억|만)|원(?![문칙인래본안])|억|천|만|달러))/g;
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
      const no = m[1] || m[3], sub = m[2] || m[4];   // 앞 둘 = '제'가 붙은 꼴, 뒤 둘 = '제' 없는 꼴
      // '제' 없는 꼴은 법령명이 **바로 앞**에 있을 때만(「전기통신사업법 37조」) — 앞서 나온 법령을 이어받지 않는다(Fable 재검토 #246, 2026-09-27):
      // 「전파법 제11조 … 할당대가 3조 규모」「…제50조 위반 과징금 2조를 넘는다」의 금액이 뒤 낱말 거르기(원·억·천·만)에 안 걸려
      // 전파법 제3조·전기통신사업법 제2조(정의)를 끌어왔다. 「전파법 16조와 17조」의 17조는 잃지만 표준 표기 '제17조'는 그대로 된다.
      // 약한 이름(「…세부사항」·앞 낱말이 이름이 아닌 것 — cite_verify lawNameBefore weak)은 '제'가 붙은 번호에만 후보로 둔다.
      const strong = info && !info.weak;
      if (strong || (m[1] && (info || lastNamed))) refs.push({ key: no + '조' + (sub ? '의' + sub : ''), info: info, ctx: lastNamed });
      if (info && info.candidates && !info.weak) lastNamed = info;   // 약한 이름(「…세부사항」)은 이어받을 법령로 치지 않는다(cite_verify와 같음)
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

  // ── 자문 빠뜨림 1차: 덧붙이기 세 갈래 (#283, 2026-10-06 — 설계 local_docs/자문누락_설계_261005.md, Fable 재검토 대상) ──
  // 10-05 측정: 회귀 20문항의 필수 조문 68개 중 원문이 참조 자료에 든 것 34개(50%). 든 조문은 14%만 빠뜨리고 안 든 조문은 65%를
  // 빠뜨렸다 — 빠뜨림의 주원인은 검색이다. 빠진 조문의 꼴은 ① 위임 사슬 아래(시행령·고시)와 그 위 근거 ② 같은 고시의 이웃 조
  // ③ 문서당 3개 상한에 걸린 조(전파법 시행령 제96조는 키워드 후보 1위인데 같은 시행령 3칸이 차서 빠졌다).
  // 세 갈래 모두 **덧붙이기만** 한다 — 상위 15·조문 정밀검색·통째 보강·역참조·별표의 내용과 순서는 그대로다(15칸 안에서 자리를
  // 바꾸는 조정은 #244에서 나빠짐 5·좋아짐 0). 그래서 회귀 대조는 「기존 조각 id가 그대로인가 + 무엇이 더 붙었나」로 끝난다.
  // 조회가 실패하거나 비면 지금과 똑같이 답한다(사내판에 위임 표가 없어도 같은 코드가 돈다).
  // L7 위임 따라가기: 근거 조문 하나당 방향별 perBase개, 아래(위임한 하위 조) down개·위(위임 근거 상위 조) up개, 조마다 앞 조각
  // chunksPerArticle개, L7 전체 maxChars자. spare = 조회 실패·현행 문서에 없음에 대비해 더 조회해 두는 후보 수.
  // 값은 회귀 20문항 무료 측정(10-06)으로 골랐다 — perBase 2→1이 핵심 정답 40→41(q11 시행령 제24조)·항목 241→231로 둘 다 낫고,
  // up 4→2는 41→37(위 근거 조문이 정답 6개를 데려온다), down·up 5·5(+perBase 3)는 재현율이 같고 최대 참조 자료가 48K 토큰을 넘었다.
  // 같은 근거의 형제 순서(2차 후보 — 융합 전체 후보에 든 조 먼저)는 무료 측정에서 개발 합의 필수 +0(켜든 끄든 같은 결과)이라 미리 정한
  // 채택 조건(+1 이상)을 못 채워 버렸다(10-06). q12 전파법 시행령 제45조는 융합 후보에도 없어 순서로는 닿지 않는다.
  const DELEG_OPTS = { perBase: 1, down: 4, up: 4, chunksPerArticle: 2, maxChars: 9000, spare: 2 };
  // L4 같은 고시 이웃 조: 남은 조문 합이 wholeChars자 이하면 전부, 넘으면 이미 든 조의 앞뒤 조와 준용 조만 max개
  // (같은 측정: 4,000이면 정답 1개를 잃고 8,000은 얻는 것 없이 글만 는다)
  const NEIGHBOR_OPTS = { wholeChars: 6000, max: 4 };
  // L3′ 공통 인용(2차, 10-06 — Fable 재검토 §4①): 본래 근거 조문(정밀검색·상한 구제·RAG) 가운데 서로 다른 minBases곳 이상이 번호로
  // 가리킨 같은 법령의 조. 질문당 max개(+spare 예비 조회), 조마다 앞 chunksPerArticle조각.
  const XREF_OPTS = { max: 3, minBases: 2, chunksPerArticle: 2, spare: 2 };
  // spillMax = L1′ 상한 구제 칸, budgetChars = 상한 구제분을 먼저 세고 fillOrder 순(down = L7 아래, up = L7 위, xref = L3′, neighbor = L4,
  // annex = 덧붙인 조문이 가리킨 별표 따로 1칸)으로 채워 이 글자 수에서 끊는다(≈ +11K 토큰), maxTotalChars = 참조 자료 전체 상한(설계 §6
  // 「최대 48K 토큰」 × 실측 1.094자/토큰 ≈ 52,500자) — 넘으면 trimAddOns가 덧붙인 것만 덜어 낸다. annex = 별표 칸을 쓰나(2차 — 1차는
  // 종전 별표 2칸의 빈자리에 예산 밖으로 붙어 문항별 최대 +9.8K자였다).
  // fillOrder는 개발 20문항 무료 측정(10-06)으로 골랐다 — 별표를 위임 바로 뒤에 둬야 q03 시행령 별표 4(5,083자)·q08 시행령 별표 13(4,287자)이
  // 예산에 들어온다(맨 뒤면 같은 고시·공통 인용이 예산을 먼저 써 37/51, 이 순서 39/51). 대가로 참조 자료 평균이 1차보다 +1.8K자(재검토 한도
  // +1.1K자 초과 — 운영자 채택 10-06, 희석은 유료 재측정으로 확인). 예산 11,000·10,000자는 q01 고시 제17조를 잃었다.
  // dashboardExtraChars = 대시보드(app.js)만 전체 상한에 더하는 몫(운영자 결정 10-06) — 대시보드에는 봇에 없는 세 구역(시행예정 개정본·
  // 팀 추가 지식·최근 법령 개정 동향, 개발 20문항 중앙 7,855자·최대 12,826자)이 더 들어가 52,500자에 먼저 닿아 20문항 중 11개에서
  // 덧붙인 것이 덜렸다(합의 핵심 봇 39 → 대시보드 37). 그 중앙값만큼 올린다.
  const ADDON_OPTS = { spillMax: 2, budgetChars: 12000, maxTotalChars: 52500, dashboardExtraChars: 8000, annex: true,
    fillOrder: ['down', 'up', 'annex', 'xref', 'neighbor'] };
  // 고시·훈령·예규·공고 문서 — 문서명의 종류 괄호로 판별(「…세부사항(과학기술정보통신부고시)(제2026-23호)(20260416)」)
  const NOTICE_DOC_RE = /^[^(]+\([^()]*(?:고시|훈령|예규|공고)\)/;
  // 위임 표의 조 제목(괄호 없음, 예: '정의')이 정의·목적이면 따라가지 않는다 — 거의 모든 조가 정의 조와 이어져 칸만 먹는다(#230과 같은 이유)
  const DELEG_SKIP_TITLE_RE = /^\s*(?:정의|목적|용어의\s*정의|용어정의|용어의\s*뜻)\s*$/;
  const ANNEX_IN_TEXT_RE = /(「[^」]{2,40}」[^\n]{0,20}?)?별표\s*제?\s*(\d+(?:의\d+)?)/g;   // 별표 동반(#90)과 같은 인용 꼴
  // 가져온 조문의 article_no 제목이 정의·목적이면 버린다(위임 표에 제목이 비어 있는 행 — cite_verify.js CITING_SKIP_TITLE_RE와 같은 꼴)
  const ADDON_SKIP_ARTNO_RE = /\((?:정의|목적|용어의\s*정의|용어정의|용어의\s*뜻)\)/;

  // 단위 열쇠 — 조('16조'·'16조의2') 또는 별표('별표13'). 그 밖(부칙·서식·별지·보도자료)은 null.
  function unitKey(articleNo) {
    const a = String(articleNo || '');
    let m = a.match(/^(\d+조(?:의\d+)?)/);
    if (m) return m[1];
    m = a.match(/^별표\s*(\d+(?:의\d+)?)/);
    return m ? '별표' + m[1] : null;
  }
  function famOf(docName) { return String(docName || '').split('(')[0].trim(); }   // CiteVerify.docFamily와 같은 규칙
  function artNum(key) {
    const m = String(key || '').match(/^(\d+)조(?:의(\d+))?/);
    return m ? [Number(m[1]), Number(m[2] || 0)] : [1e9, 0];
  }
  function cmpArt(a, b) { const x = artNum(a), y = artNum(b); return x[0] - y[0] || x[1] - y[1]; }
  // 문서명 끝 시행일(8자리) — 같은 법령군 현행본이 둘이면 시행일이 늦은 쪽. 문자열 비교는 공포 번호 자릿수가 다르면(제9999호 대
  // 제10000호) 옛 판을 고른다(Fable 재검토 §3⑤). 날짜가 같으면 문자열이 뒤인 쪽.
  function docDate(name) {
    const all = String(name || '').match(/\((\d{8})\)/g);
    return all ? Number(all[all.length - 1].slice(1, 9)) : 0;
  }
  function laterDoc(a, b) { const x = docDate(a), y = docDate(b); return (y > x || (y === x && b > a)) ? b : a; }

  // L1′ 상한 구제 후보 — rankChunks와 같은 순서로 훑으며, 15칸이 아직 안 찼는데 **문서당 상한 때문에만** 건너뛴 조각을 순위순으로.
  // 파일 문서는 빼고 조문·별표만. rankChunks의 계약(사내 사본·테스트)은 건드리지 않는다 — 같은 정렬을 다시 해 본다.
  // 입력은 rankChunks에 넘긴 results(_hybrid_score가 채워진 뒤). 고르기(이미 든 조 빼고 ADDON_OPTS.spillMax개)는 pickSpill.
  function capSpill(results) {
    const sorted = (results || []).slice().sort(function (a, b) { return (b._hybrid_score || 0) - (a._hybrid_score || 0); });
    const perDoc = {}, out = [];
    let picked = 0;
    for (let i = 0; i < sorted.length && picked < TOTAL_CHUNK_CUT; i++) {
      const r = sorted[i];
      const dn = r.doc_name || '';
      const cap = PERDOC_LIMIT[r.doc_category || ''] || PERDOC_LIMIT['default'];
      perDoc[dn] = (perDoc[dn] || 0) + 1;
      if (perDoc[dn] <= cap) { picked++; continue; }
      if (FILE_DOC_RE.test(dn) || !/^(\d+조|별표)/.test(r.article_no || '')) continue;
      out.push(r);
    }
    return out;
  }
  // 이미 참조 자료에 있는 조각·같은 단위(문서+조/별표)는 빼고, 자기끼리도 한 단위 한 번, max개.
  function pickSpill(cands, present, max) {
    const ids = new Set(), units = new Set(), out = [];
    (present || []).forEach(function (c) {
      if (!c) return;
      ids.add(c.id);
      const u = unitKey(c.article_no);
      if (u) units.add(c.doc_name + '|' + u);
    });
    for (const c of cands || []) {
      if (out.length >= (max != null ? max : ADDON_OPTS.spillMax)) break;
      const u = unitKey(c.article_no);
      if (!u || ids.has(c.id) || units.has(c.doc_name + '|' + u)) continue;
      units.add(c.doc_name + '|' + u);
      out.push(c);
    }
    return out;
  }

  // 근거 조문 — 넘겨준 목록 순(정밀검색분 → 상한 구제분 → RAG), 파일 문서 제외, 조만. (법령군, 조) 첫 자리만.
  function delegationBases(lists) {
    const out = [], seen = {};
    (lists || []).forEach(function (list) {
      (list || []).forEach(function (c) {
        if (!c || FILE_DOC_RE.test(c.doc_name || '')) return;
        const m = String(c.article_no || '').match(/^(\d+조(?:의\d+)?)/);
        const fam = famOf(c.doc_name);
        if (!m || !fam) return;
        const k = fam + '|' + m[1];
        if (seen[k]) return;
        seen[k] = 1;
        out.push({ fam: fam, key: m[1], doc_name: c.doc_name, notice: NOTICE_DOC_RE.test(c.doc_name || '') });
      });
    });
    return out;
  }
  // 위임 표 행(law_delegations: parent_law·parent_article → child_law·child_article, 자식이 고시면 child_article '전체')에서
  // 근거 조문마다 아래·위 후보를 고른다. present = 이미 참조 자료에 있는 '법령군|조' 집합.
  //  아래 = 이 조가 위임한 하위 조(자식 「전체」 = 고시 통째 지목은 L4 몫이라 버린다)
  //  위   = 이 조에 위임한 상위 조. 근거가 고시·훈령의 조면 그 고시 「전체」 행의 부모도 위로 본다(재난문자 기준 → 재난법 제38조의2).
  // 근거 순서대로 방향별 perBase개, 방향 전체 limit개(+spare). 같은 근거 안에서는 시행령 → 시행규칙 → 그 밖, 조 번호 순(위는 법률부터).
  function pickDelegations(bases, rows, present, opts) {
    opts = Object.assign({}, DELEG_OPTS, opts || {});
    const pres = present || new Set();
    const kindRank = function (k) { return k === '시행령' ? 0 : k === '시행규칙' ? 1 : 2; };
    const lawTier = function (fam) { return /시행규칙$/.test(fam) ? 2 : /시행령$/.test(fam) ? 1 : 0; };
    const down = [], up = [], taken = {};
    const lim = function (n) { return n + (opts.spare || 0); };
    (bases || []).forEach(function (b) {
      if (down.length < lim(opts.down)) {
        const kids = (rows || []).filter(function (r) {
          return r.parent_law === b.fam && r.parent_article === b.key && r.child_article !== '전체';
        }).sort(function (x, y) { return kindRank(x.child_kind) - kindRank(y.child_kind) || cmpArt(x.child_article, y.child_article) || (x.child_law < y.child_law ? -1 : x.child_law > y.child_law ? 1 : 0); });
        let n = 0;
        for (const r of kids) {
          if (n >= opts.perBase || down.length >= lim(opts.down)) break;
          const k = r.child_law + '|' + r.child_article;
          if (pres.has(k) || taken[k] || DELEG_SKIP_TITLE_RE.test(r.child_title || '')) continue;
          taken[k] = 1; n++;
          down.push({ dir: 'down', fam: r.child_law, key: r.child_article, title: r.child_title || '', base: b });
        }
      }
      if (up.length < lim(opts.up)) {
        const pars = (rows || []).filter(function (r) {
          return r.child_law === b.fam && (r.child_article === b.key || (b.notice && r.child_article === '전체'));
        }).sort(function (x, y) { return lawTier(x.parent_law) - lawTier(y.parent_law) || (x.parent_law < y.parent_law ? -1 : x.parent_law > y.parent_law ? 1 : 0) || cmpArt(x.parent_article, y.parent_article); });
        let n = 0;
        for (const r of pars) {
          if (n >= opts.perBase || up.length >= lim(opts.up)) break;
          const k = r.parent_law + '|' + r.parent_article;
          if (pres.has(k) || taken[k] || DELEG_SKIP_TITLE_RE.test(r.parent_title || '')) continue;
          taken[k] = 1; n++;
          up.push({ dir: 'up', fam: r.parent_law, key: r.parent_article, title: r.parent_title || '', base: b, whole: r.child_article === '전체' });
        }
      }
    });
    return { down: down, up: up };
  }
  // L4 대상 — 고시·훈령·예규·공고 문서 중 서로 다른 조가 2개 이상 든 것 하나(조가 많은 것, 동수면 먼저 나온 것).
  function neighborTarget(lists) {
    const per = {}, order = [];
    (lists || []).forEach(function (list) {
      (list || []).forEach(function (c) {
        if (!c || !NOTICE_DOC_RE.test(c.doc_name || '') || FILE_DOC_RE.test(c.doc_name || '')) return;
        const m = String(c.article_no || '').match(/^(\d+조(?:의\d+)?)/);
        if (!m) return;
        if (!per[c.doc_name]) { per[c.doc_name] = []; order.push(c.doc_name); }
        if (per[c.doc_name].indexOf(m[1]) === -1) per[c.doc_name].push(m[1]);
      });
    });
    let best = null;
    order.forEach(function (d) { if (per[d].length >= 2 && (!best || per[d].length > per[best].length)) best = d; });
    return best ? { doc_name: best, keys: per[best] } : null;
  }
  // 그 문서의 조문 조각(docRows)에서 이미 든 조(keys)를 빼고 조 단위로 묶어 고른다(별표·서식·부칙은 조 열쇠가 없어 자연히 빠진다).
  // 남은 합이 wholeChars 이하면 전부, 넘으면 문서 안 순서로 이미 든 조 바로 앞·뒤 조와 제목에 「준용」이 든 조만 max개. 조 번호 순.
  function pickNeighbors(docRows, keys, opts) {
    opts = Object.assign({}, NEIGHBOR_OPTS, opts || {});
    const CV = root.CiteVerify;
    const merge = CV ? CV.mergeChunkTexts : function (p) { return p.join('\n'); };
    const groups = {}, order = [];
    (docRows || []).slice().sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); }).forEach(function (r) {
      const m = String(r.article_no || '').match(/^(\d+조(?:의\d+)?)/);
      if (!m) return;
      if (!groups[m[1]]) { groups[m[1]] = { key: m[1], doc_name: r.doc_name, article_no: r.article_no, rows: [] }; order.push(m[1]); }
      groups[m[1]].rows.push(r);
    });
    const all = order.slice().sort(cmpArt);
    const have = new Set(keys || []);
    const rest = all.filter(function (k) { return !have.has(k); }).map(function (k) {
      const g = groups[k];
      return { key: k, doc_name: g.doc_name, article_no: g.article_no, ids: g.rows.map(function (r) { return r.id; }),
        content: merge(g.rows.map(function (r) { return r.content || ''; })) };
    });
    const total = rest.reduce(function (a, x) { return a + x.content.length; }, 0);
    if (total <= opts.wholeChars) return rest;
    const near = new Set();
    all.forEach(function (k, i) {
      if (!have.has(k)) return;
      if (i > 0) near.add(all[i - 1]);
      if (i < all.length - 1) near.add(all[i + 1]);
    });
    return rest.filter(function (x) { return near.has(x.key) || /준용/.test(x.article_no || ''); }).slice(0, opts.max);
  }

  // ── L3′ 공통 인용(2차, 10-06 — Fable 재검토 §4①) ──
  // 근거 조문 본문의 「제N조」를 같은 법령의 조로 읽는다. 다른 법령 인용 거르기는 cite_verify.js isOtherLawRef 그대로(#230 — 「…」 제N조·
  // 같은 법·낫표 없는 법령명). 시행령·시행규칙 안의 「법 제N조」(시행규칙의 「영 제N조」)는 isOtherLawRef가 '다른 법령'으로 보는 꼴인데
  // 여기서는 모법(시행령)으로 옮긴다. 판별 규칙을 새로 만들지 않으려고, 홀로 쓴 '법'('영')을 「이 법」(「이 영」)으로 바꿔 isOtherLawRef가
  // 자기 법령으로 뒤집히는지로 가린다(「같은 법」·「동법」·「전파법」은 바꾸지 않으므로 안 뒤집힌다).
  const XREF_RE = /제\s?(\d+)\s?조(?:\s?의\s?(\d+))?/g;
  function bareWordRef(before, word) {
    const CV = root.CiteVerify;
    const re = new RegExp('(^|[^가-힣])' + word + '(?![가-힣])', 'g');
    const swapped = before.replace(re, function (m0, p1, off) {
      return /같은\s*$/.test(before.slice(0, off + p1.length)) ? m0 : p1 + '이 ' + word;
    });
    return swapped !== before && !CV.isOtherLawRef(swapped);
  }
  // 조각 하나가 가리키는 (법령군, 조) 목록 — fam = 그 조각의 법령군
  function xrefTargets(c, fam) {
    const CV = root.CiteVerify;
    if (!CV || !CV.isOtherLawRef) return [];
    const s = String(c.content || ''), out = [];
    const sub = /(시행령|시행규칙)$/.test(fam), parent = fam.replace(/\s*(시행령|시행규칙)$/, '');
    const re = new RegExp(XREF_RE.source, 'g');
    let m;
    while ((m = re.exec(s))) {
      const key = m[1] + '조' + (m[2] ? '의' + m[2] : '');
      const before = s.slice(Math.max(0, m.index - 80), m.index);
      let tf = null;
      if (!CV.isOtherLawRef(before)) tf = fam;
      else if (sub && bareWordRef(before, '법')) tf = parent;
      else if (/시행규칙$/.test(fam) && bareWordRef(before, '영')) tf = parent + ' 시행령';
      if (tf) out.push({ fam: tf, key: key });
    }
    return out;
  }
  // 근거(lists = [정밀검색, 상한 구제, RAG] — 덧붙인 조문은 근거로 세지 않는다: 세면 후보 74개·쓸모 14%로 떨어지고 얻는 것은 1개, 사슬이
  // 한 걸음 더 불어나는 꼴 H5)마다 가리킨 조를 모아, 서로 다른 근거 minBases곳 이상이 가리킨 것만 가리킨 곳 수 ↓ → 가장 앞선 근거 순으로
  // max(+spare)개. 이미 든 조(present)·위임으로 고른 조(taken)·근거 자신은 뺀다. 정의·목적 조에서 나가는 인용은 세지 않는다.
  function pickXrefs(lists, present, taken, opts) {
    opts = Object.assign({}, XREF_OPTS, opts || {});
    const pres = present || new Set(), tk = taken || {};
    const by = {}, order = [], rankOf = {};
    let rank = 0;
    (lists || []).forEach(function (list) {
      (list || []).forEach(function (c) {
        if (!c || FILE_DOC_RE.test(c.doc_name || '')) return;
        const mk = String(c.article_no || '').match(/^(\d+조(?:의\d+)?)/);
        const fam = famOf(c.doc_name);
        if (!mk || !fam) return;
        const bk = fam + '|' + mk[1];
        if (rankOf[bk] === undefined) rankOf[bk] = rank++;
        if (ADDON_SKIP_ARTNO_RE.test(c.article_no || '')) return;
        xrefTargets(c, fam).forEach(function (t) {
          const k = t.fam + '|' + t.key;
          if (k === bk || pres.has(k) || tk[k]) return;
          let e = by[k];
          if (!e) { e = by[k] = { fam: t.fam, key: t.key, bases: [], first: rankOf[bk], doc: null }; order.push(k); }
          if (e.bases.indexOf(bk) === -1) e.bases.push(bk);
          if (rankOf[bk] < e.first) e.first = rankOf[bk];
          if (!e.doc && t.fam === fam) e.doc = c.doc_name;   // 같은 법령 안 인용이면 근거 문서가 곧 대상 문서
        });
      });
    });
    return order.map(function (k) { return by[k]; }).filter(function (e) { return e.bases.length >= opts.minBases; })
      .sort(function (a, b) { return b.bases.length - a.bases.length || a.first - b.first; })
      .slice(0, opts.max + (opts.spare || 0));
  }

  // ── 덧붙인 조문이 가리킨 별표 따로 1칸(2차, 10-06 — Fable 재검토 §4③) ──
  // 조문이 「별표 N에 따른다」고 가리킨 같은 문서의 별표 — 별표 동반(#90, 각 파일의 buildAnnexContext 1단계)과 같은 규칙: 별표·별지 조각은
  // 빼고, 「다른 법령」 별표 N은 건너뛰고, 문서|번호 첫 자리만. 반환 [{doc_name, no}] 입력 순.
  function annexWanted(chunks) {
    const out = [], seen = {};
    (chunks || []).forEach(function (c) {
      if (!c || /^(별표|별지)/.test(c.article_no || '')) return;
      const re = new RegExp(ANNEX_IN_TEXT_RE.source, 'g');
      let m;
      while ((m = re.exec(String(c.content || '')))) {
        if (m[1]) continue;
        const k = c.doc_name + '|' + m[2];
        if (seen[k]) continue;
        seen[k] = 1;
        out.push({ doc_name: c.doc_name, no: m[2] });
      }
    });
    return out;
  }
  // 별표 한 개의 블록 — 별표 동반(#90)과 같은 꼴: 첫 조각(열 이름)은 무조건, 나머지는 질문 낱말이 많이 든 조각 ANNEX_MAX_CHUNKS-1개, 문서 순.
  function annexBlock(docName, no, rows, question) {
    const all = (rows || []).slice().sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
    if (!all.length) return null;
    const qWords = extractKeywords(question || '');
    const picked = [all[0]];
    all.slice(1).map(function (c) {
      const t = String(c.content || '');
      return { c: c, hit: qWords.reduce(function (a, kw) { return a + (t.indexOf(kw) >= 0 ? 1 : 0); }, 0) };
    }).sort(function (a, b) { return b.hit !== a.hit ? b.hit - a.hit : (a.c.chunk_index || 0) - (b.c.chunk_index || 0); })
      .slice(0, ANNEX_MAX_CHUNKS - 1).forEach(function (x) { picked.push(x.c); });
    picked.sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
    const title = all[0].article_no || ('별표 ' + no);
    const omitted = all.length - picked.length;
    const content = picked.map(function (c) { return c.content || ''; }).join('\n');
    return { doc_name: docName, no: no, key: '별표' + no, article_no: title, content: content,
      ids: picked.map(function (c) { return c.id; }), source: famOf(docName) + ' ' + title.split('(')[0].trim(),
      text: '[' + docName + ' ' + title + ']' +
        (omitted > 0 ? '\n※ 이 별표는 전체 ' + all.length + '개 조각 중 질문과 가까운 ' + picked.length + '개만 실었습니다. 표의 일부만 보이면 그렇게 밝히세요.' : '') +
        '\n' + content };
  }

  // 덧붙이기 구역 문구 — 두 판(봇·대시보드)이 같은 글을 쓰게 여기 한 곳에.
  // 「직접 이어진 조문 — 해당하면 함께 제시」로 약하게 쓴다(관련 없는 하위 조를 억지로 인용하지 않게, 설계 H11). 판정 기준문이 아니라 잠그지 않는다.
  function delegTail(it) {
    const b = it.base;
    if (it.dir === 'down') return ' — ' + b.fam + ' 제' + b.key + '의 위임을 받은 조문';
    return ' — ' + b.fam + (it.whole ? '' : ' 제' + b.key) + '에 위임한 상위 조문';
  }
  function xrefTail(it) {
    const names = it.bases.slice(0, 3).map(function (bk) { const p = bk.split('|'); return p[0] + ' 제' + p[1]; });
    return ' — 위 ' + names.join('·') + (it.bases.length > 3 ? ' 등 ' + it.bases.length + '곳' : '') + '에서 가리킨 조문';
  }
  // deleg(L7) → xref(L3′) → neighbor(L4) → annex(덧붙인 조문의 별표) 순. 넷째·셋째 인자는 2차에서 더한 것(없으면 1차와 같은 글).
  function buildAddOnContext(deleg, neighbor, xref, annex) {
    let text = '';
    if (deleg && deleg.length) {
      text += '\n\n---\n\n[위임 관계로 이어진 조문 — 위 조문이 위임한 하위 조문과, 그 근거가 되는 상위 조문]\n' +
        '위 조문과 위임으로 직접 이어진 조문입니다. 질문이 묻는 기한·금액·요건·절차가 여기 있으면 상위 조문과 함께 제시하세요(관련 없으면 쓰지 않아도 됩니다):\n\n' +
        deleg.map(function (x, i) { return '[위임 ' + (i + 1) + '] ' + x.doc_name + ' ' + x.article_no + delegTail(x) + '\n' + x.content; }).join('\n\n---\n\n');
    }
    if (xref && xref.length) {
      text += '\n\n---\n\n[위 조문 여러 곳이 함께 가리키는 조문 — 검색된 조문 둘 이상이 번호로 인용한 같은 법령의 조문]\n' +
        '위에 실린 조문 여러 개가 「제N조」로 함께 가리키는 조문입니다. 요건·절차·기한·기준이 여기 있으면 함께 제시하세요(관련 없으면 쓰지 않아도 됩니다):\n\n' +
        xref.map(function (x, i) { return '[공통 인용 ' + (i + 1) + '] ' + x.doc_name + ' ' + x.article_no + xrefTail(x) + '\n' + x.content; }).join('\n\n---\n\n');
    }
    if (neighbor && neighbor.length) {
      text += '\n\n---\n\n[같은 고시의 다른 조문 — 위에 조문 여러 개가 실린 「' + famOf(neighbor[0].doc_name) + '」의 나머지 조문]\n' +
        '위에 실린 조문과 같은 고시·훈령의 조문입니다. 절차·기한·서류·기준이 여기 있으면 함께 제시하세요(관련 없으면 쓰지 않아도 됩니다):\n\n' +
        neighbor.map(function (x, i) { return '[같은 고시 ' + (i + 1) + '] ' + x.doc_name + ' ' + x.article_no + '\n' + x.content; }).join('\n\n---\n\n');
    }
    if (annex) {
      text += '\n\n---\n\n[위에 덧붙인 조문이 가리키는 별표 원문]\n' +
        '위에 덧붙인 조문이 「별표 N에 따른다」고 한 별표입니다. 금액·기준·요율은 조문이 아니라 별표가 정본이니, ' +
        '질문이 묻는 항목이 여기 있으면 이 표에서 인용하세요(관련 없으면 쓰지 않아도 됩니다):\n\n' + annex.text;
    }
    return text;
  }

  // 조회까지 — lists = { extra, spill, rag }(통째 보강이 끝난 것), fetchers = {
  //   delegations(fams, keys) → law_delegations 행(부모 또는 자식이 그 법령군·조인 것, 자식 '전체' 포함),
  //   familyDocs(fams) → [{law_name, doc_name}] 법령군의 현행 문서명(선택 — 없거나 실패하면 문서명 없이 조회),
  //   familyArticle(fam, key, docName) → 그 법령군 현행 문서의 그 조 조각들(docName을 알면 그 문서만), docArticles(doc_name) → 그 문서의 조문 조각들,
  //   annexRows(doc_name, no) → 그 문서 별표 N의 조각들(선택 — 없으면 별표 칸 없음) }.
  // opts = { question(별표 조각 고르기), deleg, xref, neighborOpts, budget, fillOrder, neighbor:false, annex:false }.
  // 반환 { text, chunks(검증용 — 조·별표마다 한 덩어리, id = 첫 조각), ids(실린 조각 id 전부), deleg(L7 덩어리), items(측정용
  //        [{sec, dir, fam, key}] — spill 포함), chars(구역 글자 수), annexCites, annexSources, parts(trimAddOns 재료) }.
  //        조회 하나가 실패해도 그 갈래만 비고 나머지는 간다.
  // 예산(budget)은 상한 구제분(이미 조문 정밀검색 구역에 실림)을 먼저 세고 ADDON_OPTS.fillOrder(opts.fillOrder) 순으로 넣을 수 있는 것만 넣는다.
  async function fetchAddOns(lists, fetchers, opts) {
    opts = opts || {};
    const dOpts = Object.assign({}, DELEG_OPTS, opts.deleg || {});
    const xOpts = Object.assign({}, XREF_OPTS, opts.xref || {});
    const budget = opts.budget != null ? opts.budget : ADDON_OPTS.budgetChars;
    const CV = root.CiteVerify;
    const merge = CV ? CV.mergeChunkTexts : function (p) { return p.join('\n'); };
    const soft = function (fn) { return Promise.resolve().then(fn).then(function (r) { return r || []; }, function () { return []; }); };
    const extra = lists.extra || [], spill = lists.spill || [], rag = lists.rag || [];
    const bases = delegationBases([extra, spill, rag]);
    const present = new Set(bases.map(function (b) { return b.fam + '|' + b.key; }));
    const nt = opts.neighbor === false ? null : neighborTarget([extra, spill, rag]);
    const docP = nt ? soft(function () { return fetchers.docArticles(nt.doc_name); }) : Promise.resolve([]);
    let rows = [];
    if (bases.length && opts.deleg !== false) {
      const fams = [], keys = [];
      bases.forEach(function (b) { if (fams.indexOf(b.fam) === -1) fams.push(b.fam); if (keys.indexOf(b.key) === -1) keys.push(b.key); });
      rows = await soft(function () { return fetchers.delegations(fams, keys); });
    }
    const cand = pickDelegations(bases, rows, present, dOpts);
    const taken = {};
    cand.down.concat(cand.up).forEach(function (it) { taken[it.fam + '|' + it.key] = 1; });
    const xc = opts.xref === false ? [] : pickXrefs([extra, spill, rag], present, taken, xOpts);
    const want = cand.down.concat(cand.up).concat(xc.map(function (x) { return Object.assign({ sec: 'xref' }, x); }));
    // 문서명을 모르는 법령군은 한 번에 현행 문서명을 받아 그 문서만 조회한다 — 「'법령군(%' + 조」 조회는 현행 조각 4만여 행을 훑었다
    // (실행 계획 버퍼 9,124·40~115ms, 문항당 최대 12개 동시 → 문서명 지정 시 버퍼 212·1.2ms, Fable 재검토 §3④)
    const docOf = {};
    const needFams = [];
    want.forEach(function (it) { if (!it.doc && needFams.indexOf(it.fam) === -1) needFams.push(it.fam); });
    if (needFams.length && fetchers.familyDocs) {
      (await soft(function () { return fetchers.familyDocs(needFams); })).forEach(function (r) {
        if (r && r.law_name && r.doc_name) docOf[r.law_name] = docOf[r.law_name] ? laterDoc(docOf[r.law_name], r.doc_name) : r.doc_name;
      });
    }
    const got = await Promise.all(want.map(function (it) {
      return soft(function () { return fetchers.familyArticle(it.fam, it.key, it.doc || docOf[it.fam] || null); });
    }));
    const ready = { down: [], up: [], xref: [] };
    want.forEach(function (it, i) {
      const rs = got[i].filter(function (r) {
        return r && famOf(r.doc_name) === it.fam && !FILE_DOC_RE.test(r.doc_name || '') && (String(r.article_no || '').match(/^(\d+조(?:의\d+)?)/) || [])[1] === it.key;
      });
      if (!rs.length) return;                                   // 현행 문서에 그 조가 없다(위임 표가 낡음) — 조용히 건너뜀
      let doc = rs[0].doc_name;
      rs.forEach(function (r) { doc = laterDoc(doc, r.doc_name); });   // 같은 법령군이 여럿이면 문서명 끝 시행일이 늦은 쪽
      const mine = rs.filter(function (r) { return r.doc_name === doc; }).sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
      if (ADDON_SKIP_ARTNO_RE.test(mine[0].article_no || '')) return;
      const isX = it.sec === 'xref';
      const use = mine.slice(0, isX ? xOpts.chunksPerArticle : dOpts.chunksPerArticle);
      let content = merge(use.map(function (r) { return r.content || ''; }));
      if (mine.length > use.length) content += '\n(※ 이 조문은 전체 ' + mine.length + '조각 중 앞 ' + use.length + '조각만 실었습니다. 보이지 않는 항·호가 있을 수 있습니다.)';
      const slot = isX ? 'xref' : it.dir;
      const lim = isX ? xOpts.max : it.dir === 'down' ? dOpts.down : dOpts.up;
      if (ready[slot].length >= lim) return;
      ready[slot].push(Object.assign({}, it, { doc_name: doc, article_no: mine[0].article_no, content: content, ids: use.map(function (r) { return r.id; }) }));
    });
    let used = spill.reduce(function (a, c) { return a + String(c.content || '').length; }, 0);
    let delegUsed = 0;
    const items = spill.map(function (c) { return { sec: 'spill', fam: famOf(c.doc_name), key: unitKey(c.article_no) || '' }; });
    const dPick = { down: [], up: [] }, xref = [], neighbor = [];
    const chosen = new Set();   // 문서|조 — 한 조가 두 칸으로 갈리지 않게(설계 H13): 위임·공통 인용·같은 고시끼리도 한 번만
    const fits = function (len) { if (used + len > budget) return false; used += len; return true; };
    const putDeleg = function (dir) {
      ready[dir].forEach(function (x) {
        const len = x.doc_name.length + x.article_no.length + delegTail(x).length + x.content.length + 20;
        if (chosen.has(x.doc_name + '|' + x.key) || delegUsed + len > dOpts.maxChars || !fits(len)) return;
        delegUsed += len; chosen.add(x.doc_name + '|' + x.key);
        dPick[dir].push(x);
      });
    };
    const putXref = function () {
      ready.xref.forEach(function (x) {
        const len = x.doc_name.length + x.article_no.length + xrefTail(x).length + x.content.length + 20;
        if (chosen.has(x.doc_name + '|' + x.key) || !fits(len)) return;
        chosen.add(x.doc_name + '|' + x.key);
        xref.push(x);
      });
    };
    // 별표 칸 — 이미 고른 덧붙인 조문(상한 구제 → 위임 아래·위 → 공통 인용)의 첫 별표 인용. 종전 별표 2칸(RAG → 정밀검색 순 인용 앞 두 개,
    // 각 파일의 buildAnnexContext)에 이미 든 것은 뺀다. 종전 2칸은 덧붙이기와 무관하게 1차 이전과 같은 입력으로 돈다.
    // 고르기 전 후보(조회해 둔 조문 전부)의 첫 별표를 미리 받아 두고, 실제로 고른 조문의 첫 별표가 그것과 다를 때만 다시 받는다.
    const useAnnex = ADDON_OPTS.annex && opts.annex !== false && !!fetchers.annexRows;
    const baseAnnex = new Set(annexWanted(rag.concat(extra)).slice(0, ANNEX_MAX_UNITS).map(function (w) { return w.doc_name + '|' + w.no; }));
    const firstAnnex = function (list) { return annexWanted(list).filter(function (w) { return !baseAnnex.has(w.doc_name + '|' + w.no); })[0] || null; };
    const loadAnnex = function (w) {
      return soft(function () { return fetchers.annexRows(w.doc_name, w.no); }).then(function (rs) { return annexBlock(w.doc_name, w.no, rs, opts.question); });
    };
    const guess = useAnnex ? firstAnnex(spill.concat(ready.down).concat(ready.up).concat(ready.xref)) : null;
    const guessP = guess ? loadAnnex(guess) : Promise.resolve(null);
    const neighborCands = nt ? pickNeighbors(await docP, nt.keys, opts.neighborOpts) : [];
    let annex = null;
    const fillOrder = opts.fillOrder || ADDON_OPTS.fillOrder;
    for (const step of fillOrder) {
      if (step === 'down' || step === 'up') putDeleg(step);
      else if (step === 'xref') putXref();
      else if (step === 'neighbor') {
        neighborCands.forEach(function (x) {
          const len = x.doc_name.length + x.article_no.length + x.content.length + 20;
          if (chosen.has(x.doc_name + '|' + x.key) || !fits(len)) return;
          chosen.add(x.doc_name + '|' + x.key);
          neighbor.push(x);
        });
        neighbor.sort(function (a, b) { return cmpArt(a.key, b.key); });
      } else if (step === 'annex' && useAnnex) {
        const w = firstAnnex(spill.concat(dPick.down).concat(dPick.up).concat(xref));
        if (!w) continue;
        const blk = guess && w.doc_name === guess.doc_name && w.no === guess.no ? await guessP : await loadAnnex(w);
        if (blk && fits(blk.text.length + 20)) annex = blk;
      }
    }
    const deleg = dPick.down.concat(dPick.up);
    return packAddOns({ deleg: deleg, xref: xref, neighbor: neighbor, annex: annex, spillItems: items });
  }
  // 덧붙인 것 → 결과 꼴. parts는 trimAddOns가 다시 묶을 재료(호출측은 쓰지 않는다).
  function packAddOns(p) {
    const deleg = p.deleg || [], xref = p.xref || [], neighbor = p.neighbor || [], annex = p.annex || null;
    const items = (p.spillItems || []).slice();
    deleg.forEach(function (x) { items.push({ sec: 'deleg', dir: x.dir, fam: x.fam, key: x.key }); });
    xref.forEach(function (x) { items.push({ sec: 'xref', fam: x.fam, key: x.key }); });
    neighbor.forEach(function (x) { items.push({ sec: 'neighbor', fam: famOf(x.doc_name), key: x.key }); });
    if (annex) items.push({ sec: 'annex', fam: famOf(annex.doc_name), key: annex.key });
    const parts = { deleg: deleg, xref: xref, neighbor: neighbor, annex: annex, spillItems: p.spillItems || [] };
    if (!deleg.length && !xref.length && !neighbor.length && !annex) {
      return { text: '', chunks: [], ids: [], deleg: [], items: items, chars: 0, annexCites: [], annexSources: [], parts: parts };
    }
    const text = buildAddOnContext(deleg, neighbor, xref, annex);
    const chunks = [], ids = [];
    deleg.concat(xref).concat(neighbor).concat(annex ? [annex] : []).forEach(function (x) {
      chunks.push({ id: x.ids[0], doc_name: x.doc_name, article_no: x.article_no, content: x.content,
        _addon: x === annex ? 'annex' : x.sec === 'xref' ? 'xref' : x.dir ? 'deleg' : 'neighbor' });
      x.ids.forEach(function (id) { if (typeof id === 'number' && ids.indexOf(id) === -1) ids.push(id); });
    });
    // L7 조문이 가리키는 별표(타 법령 인용 제외) — 측정용(설계 H6)
    const annexCites = [];
    deleg.forEach(function (x) {
      annexWanted([x]).forEach(function (w) { const t = famOf(w.doc_name) + ' 별표 ' + w.no; if (annexCites.indexOf(t) === -1) annexCites.push(t); });
    });
    return { text: text, chunks: chunks, ids: ids, deleg: chunks.filter(function (c) { return c._addon === 'deleg'; }),
      items: items, chars: text.length, annexCites: annexCites, annexSources: annex ? [annex.source] : [], parts: parts };
  }
  // 참조 자료 전체 상한 — otherChars(덧붙이기 구역을 뺀 나머지 참조 자료 글자 수) + 덧붙이기 구역이 maxTotalChars를 넘으면
  // 비싼 것·우선순위가 낮은 것부터(덧붙인 조문의 별표 → 같은 고시 → 공통 인용 → 위 → 아래, 각각 뒤에서) 덜어 다시 묶는다. 설계의
  // 「최대 48K 토큰」을 문항마다 지키는 장치. 2차에서 별표를 맨 앞에 — 1차는 넘친 원인(별표 9.8K자)은 두고 조문을 덜어 냈다(재검토 §1-6 i30).
  // 덧붙이기 구역 앞의 글(상위 15·정밀검색·역참조·별표 등)은 건드리지 않는다. 덜어낼 것이 없으면 그대로 둔다. trimmed = 덜어 낸 개수.
  function trimAddOns(ao, otherChars, maxTotal) {
    const cap = maxTotal != null ? maxTotal : ADDON_OPTS.maxTotalChars;
    if (!ao || !ao.text || !ao.parts || (otherChars || 0) + ao.text.length <= cap) return ao;
    const p = ao.parts;
    let annex = p.annex || null;
    const deleg = (p.deleg || []).slice(), xref = (p.xref || []).slice(), neighbor = (p.neighbor || []).slice();
    const count = function () { return deleg.length + xref.length + neighbor.length + (annex ? 1 : 0); };
    const before = count();
    let cur = ao;
    while (count() && (otherChars || 0) + cur.text.length > cap) {
      if (annex) annex = null; else if (neighbor.length) neighbor.pop(); else if (xref.length) xref.pop(); else deleg.pop();
      cur = packAddOns({ deleg: deleg, xref: xref, neighbor: neighbor, annex: annex, spillItems: p.spillItems });
    }
    cur.trimmed = before - count();
    return cur;
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
    LAW_TERM_SYNONYMS: LAW_TERM_SYNONYMS, LAW_TERM_MAX: LAW_TERM_MAX, lawTermKeywords: lawTermKeywords,   // L5′(#289)
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
    ADDON_OPTS: ADDON_OPTS, DELEG_OPTS: DELEG_OPTS, NEIGHBOR_OPTS: NEIGHBOR_OPTS,
    NOTICE_DOC_RE: NOTICE_DOC_RE, unitKey: unitKey, capSpill: capSpill, pickSpill: pickSpill,
    delegationBases: delegationBases, pickDelegations: pickDelegations, neighborTarget: neighborTarget, pickNeighbors: pickNeighbors,
    buildAddOnContext: buildAddOnContext, fetchAddOns: fetchAddOns, trimAddOns: trimAddOns,
    // 자문 빠뜨림 2차(#283-보론2) — 형제 순서·공통 인용·덧붙인 조문의 별표 1칸
    XREF_OPTS: XREF_OPTS, pickXrefs: pickXrefs, xrefTargets: xrefTargets,
    annexWanted: annexWanted, annexBlock: annexBlock, docDate: docDate,
    buildRagContext: buildRagContext, buildKbContext: buildKbContext,
  };
  root.RagCore = RagCore;
  if (typeof module !== 'undefined' && module.exports) module.exports = RagCore;
})(typeof globalThis !== 'undefined' ? globalThis : this);
