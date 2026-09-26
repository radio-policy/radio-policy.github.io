// ============================================================================
//  cite_verify.js — 자문 답변의 「[원문 확인됨]」 표시를 기계가 검증한다 (#155, 2026-09-11)
//
//  배경: 이 표시는 프롬프트 지시로 모델이 스스로 붙이는 자기 신고였다. 9/10 텔레그램 자문이
//  전기통신사업법 제50조①5호·5호의2를 "차별적 지원금"으로 설명하며 표시를 붙였는데, 실제로
//  검색돼 모델 앞에 놓인 것은 제50조 뒷조각(8호~③)뿐이었고 5호·5호의2 본문은 없었다.
//  "표시가 붙었다 = 내가 따로 검증할 필요 없다"가 사용자에게 내건 약속이므로 코드가 보증해야 한다.
//
//  세 단계 (운영자 결정 2026-09-11):
//   1) expandArticles   — 검색된 조문이 여러 조각이면 나머지 조각을 붙여 조문을 통째로 모델에 준다
//                         (잘린 채 들어간 것이 이번 사고의 직접 원인).
//   2) checkCitation    — 답변의 각 표시 앞 인용(법령명·조·항·호·별표)을 파싱해, 그 원문이 실제로
//                         검색 결과(+시스템 프롬프트 핵심 조문)에 있었는지 대조. 없으면 표시를
//                         「[⚠️ 원문 미확인 — 검색 결과에 해당 조문 없음]」으로 바꾼다.
//   3) judge(Haiku)     — 원문이 있었던 인용은 원문과 답변 문장을 나란히 Haiku에 보내 "다르게 옮겼는가"를
//                         판정. 불일치면 「[⚠️ 원문과 다르게 설명됨 — 확인 필요]」로 바꾼다.
//                         판단불가·호출 실패는 표시를 그대로 둔다(fail-open).
//
//  #230(2026-09-26, 운영자 결정) — ① 역참조 발췌가 다른 법령 조문(「…」·같은 법·(시행령의) 법 제N조)을 가리킨 줄을 인용으로
//   치지 않고, 정의·목적·목록 조문을 빼고, 제재 조문(벌칙·과태료·과징금 등)은 별도 칸으로 먼저 싣는다(금액이 적힌 항 머리 포함)
//   ② 표시 없는 인용 문단·따옴표 인용도 같은 경로로 대조한다(tagUntaggedQuotes — 판정 기준은 그대로).
//
//  한 파일을 세 곳이 그대로 쓴다 — Deno Edge(rag.ts, verify-citations), 브라우저(index.html <script>),
//  node 테스트(tests/cite_verify.test.js). 그래서 TS 문법·export 없이 globalThis.CiteVerify 에 붙인다.
//  GitLab Pages는 나열된 파일만 싣는다 — .gitlab-ci.yml의 cp 목록에 이 경로가 있어야 한다.
//  DB·API 호출은 전부 호출측이 콜백(fetchArticle, callHaiku)으로 넘긴다 — 이 파일은 순수 로직만.
// ============================================================================
(function (root) {
  'use strict';

  const TAG_RE = /\[원문\s*확인됨[^\]]*\]/g;
  const CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';
  // 표시는 세 상태(2026-09-20 운영자 결정, #176). 읽는 사람이 표시만 보고 "믿어라 / 직접 확인해라 / 틀렸을 수 있다"
  // 셋 중 하나로 읽어야 한다. (#169-보론5의 '[원문 확인 안 됨]' 단일 표시는 '못 찾음'과 '틀림'을 구분 못 해 폐기)
  //   ok       → [원문 확인됨: …]                         (그대로)
  //   missing  → [원문 없음 — 검색 자료에 해당 조문 없음 (대상)]   AI 기억으로 쓴 것일 수 있으니 직접 확인
  //   mismatch → [원문과 다름 — 판정기 메모: … (대상)]        틀렸을 가능성 높음, 무엇이 다른지 한 줄
  //   그 밖(판정 보류·호출 실패·호 구조 못 찾음·대조할 문장 없음)은 드물고 읽는 사람이 할 일이 같아 '원문 없음' 머리에
  //   꼬리만 달리 적는다: [원문 없음 — 자동 대조 못 함, 직접 확인 (대상)]
  const TAG_MISSING = '[원문 없음 — 검색 자료에 해당 조문 없음]';
  const TAG_UNCHECKED = '[원문 없음 — 자동 대조 못 함, 직접 확인]';
  const TAG_MISMATCH_HEAD = '[원문과 다름 — 판정기 메모: ';
  const TAG_UNVERIFIED = TAG_MISSING;    // 옛 이름 유지(외부 참조 호환)
  const TAG_MISMATCH = TAG_MISMATCH_HEAD + '…]';
  function buildTag(status, reason, target) {
    const tail = target ? ' (' + target + ')]' : ']';
    if (status === 'mismatch') {
      const memo = String(reason || '').replace(/\s+/g, ' ').replace(/[\[\]]/g, '').trim().slice(0, 80) || '원문과 다르게 설명됨';
      return TAG_MISMATCH_HEAD + memo + tail;
    }
    if (status === 'missing') return TAG_MISSING.slice(0, -1) + tail;
    return TAG_UNCHECKED.slice(0, -1) + tail;
  }
  // 인용문 본문 길이(정규화) — 조 번호·괄호 제목·법령명을 뺀 나머지. 24자 미만이면 "번호·제목뿐"으로 본다.
  function stripCiteBody(s) {
    return normQ(String(s || '').replace(/제\s?\d+\s?조(?:\s?의\s?\d+)?(?:\s?\([^)]*\))?/g, '')
      .replace(/[가-힣A-Za-z0-9·ㆍ\s]{0,40}?(법률|법|시행령|시행규칙|규칙|고시|규정|기준|세칙|지침)(?=\s|$|[,:.)])/g, ''));
  }
  const LAW_SUFFIX_RE = /(법|법률|시행령|시행규칙|규칙|고시|규정|기준|세칙|지침|요령|훈령|예규|협정)$/;
  // 약칭 → 정식 문서명에 들어 있는 문자열 (family가 이 문자열을 포함하면 같은 법령으로 본다)
  const LAW_ALIASES = {
    '정보통신망법': '정보통신망 이용촉진', '망법': '정보통신망 이용촉진',
    '단통법': '이동통신단말장치 유통', '방발기금법': '방송통신발전 기본법', '방송통신발전기본법': '방송통신발전 기본법',
    '사업법': '전기통신사업법', '위치정보법': '위치정보의 보호', '개인정보법': '개인정보 보호법',
    '공정거래법': '독점규제 및 공정거래', '전자상거래법': '전자상거래 등에서의 소비자보호',
  };

  function articleKey(articleNo) {
    const m = String(articleNo || '').match(/^(\d+조(?:의\d+)?)/);
    return m ? m[1] : null;
  }
  function docFamily(docName) { return String(docName || '').split('(')[0].trim(); }
  function norm(s) { return String(s || '').replace(/[\s·ㆍ‧•]/g, ''); }

  // 조각 이어붙이기 — 청크는 앞뒤가 겹치게 잘려 있어(실측 제50조 136→137 조각이 ~90자 겹침)
  // 겹친 부분을 찾아 한 번만 남긴다. 겹침을 못 찾으면 줄바꿈으로 잇는다.
  function mergeChunkTexts(parts) {
    let out = '';
    for (const p of parts) {
      const t = String(p || '');
      if (!t) continue;
      if (!out) { out = t; continue; }
      const max = Math.min(400, out.length, t.length);
      let k = 0;
      for (let n = max; n >= 20; n--) {
        if (out.slice(out.length - n) === t.slice(0, n)) { k = n; break; }
      }
      out += k ? t.slice(k) : '\n' + t;
    }
    return out;
  }

  // 1) 인용 조문 통째 보강.
  //   chunks: [{id, doc_name, article_no, chunk_index, content, ...}] (순위순 — 앞쪽이 먼저 보강된다)
  //   fetchArticle(doc_name, key) → 같은 문서·같은 조의 모든 조각 [{id, article_no, chunk_index, content}]
  //   반환: chunks — 같은 조의 첫 원소가 병합 전문을 담고(_full=true) 나머지 원소는 제거됨,
  //         addedIds — 새로 들어온 조각 id(근거 기록용), expanded — 보강된 조 수
  async function expandArticles(chunks, fetchArticle, opts) {
    opts = opts || {};
    const maxArticles = opts.maxArticles != null ? opts.maxArticles : 10;
    const maxPer = opts.maxChunksPerArticle != null ? opts.maxChunksPerArticle : 4;
    let budget = opts.maxAddedChunks != null ? opts.maxAddedChunks : 14;   // 추가 조각 총량(토큰 상한)
    const groups = new Map();
    const order = [];
    (chunks || []).forEach(function (c) {
      const key = articleKey(c && c.article_no);
      if (!key || !c.doc_name) return;
      const gk = c.doc_name + '|' + key;
      if (!groups.has(gk)) { groups.set(gk, { doc: c.doc_name, key: key, members: [] }); order.push(gk); }
      groups.get(gk).members.push(c);
    });
    const full = new Map();
    // 조각 조회는 묶음(wave)으로 동시에 보내고 처리는 순위순으로 한다(B-2, #201, 2026-09-24). 종전에는 조문마다 한 번씩
    // await라 왕복이 줄줄이 더해졌다. 예산·선택 규칙이 순위순으로 그대로 적용되므로 결과는 동일하고, 상한에 걸려
    // 처리하지 않은 묶음 뒤쪽 조회 결과는 버린다(낭비 ≤ wave−1건).
    const wave = opts.fetchConcurrency != null ? opts.fetchConcurrency : 6;
    for (let w0 = 0; w0 < order.length && full.size < maxArticles && budget > 0; w0 += wave) {
      const batch = order.slice(w0, w0 + wave);
      const fetched = await Promise.all(batch.map(function (bk) {
        const bg = groups.get(bk);
        return Promise.resolve().then(function () { return fetchArticle(bg.doc, bg.key); })
          .then(function (r) { return r || []; }, function () { return []; });
      }));
      for (let bi = 0; bi < batch.length; bi++) {
      if (full.size >= maxArticles || budget <= 0) break;
      const gk = batch[bi];
      const g = groups.get(gk);
      let rows = fetched[bi];
      rows = rows.filter(function (r) { return articleKey(r.article_no) === g.key; })
        .sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
      if (rows.length <= 1) continue;                     // 한 조각짜리 조문 — 보강할 것이 없다
      const memberIds = new Set(g.members.map(function (m) { return m.id; }));
      let picked = rows.slice(0, maxPer);
      const have = new Set(picked.map(function (r) { return r.id; }));
      // 검색이 실제로 집은 조각은 상한과 무관하게 반드시 포함 (그 조각을 빼면 검색 결과가 사라진다)
      for (const m of g.members) {
        if (typeof m.id === 'number' && !have.has(m.id)) {
          const r = rows.find(function (x) { return x.id === m.id; });
          if (r) { picked.push(r); have.add(r.id); }
        }
      }
      picked.sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
      const added = picked.filter(function (r) { return !memberIds.has(r.id); }).length;
      if (added === 0) continue;                          // 이미 전부 검색돼 있었다
      if (added > budget) picked = picked.filter(function (r) { return memberIds.has(r.id); }).concat(
        picked.filter(function (r) { return !memberIds.has(r.id); }).slice(0, budget));
      picked.sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
      budget -= picked.filter(function (r) { return !memberIds.has(r.id); }).length;
      // 연속 조각은 겹침 병합, 끊긴 자리는 (중략) 표시
      const runs = [];
      let cur = [], prev = null;
      for (const r of picked) {
        if (prev !== null && (r.chunk_index || 0) !== prev + 1) { runs.push(cur); cur = []; }
        cur.push(r.content || ''); prev = r.chunk_index || 0;
      }
      if (cur.length) runs.push(cur);
      let text = runs.map(mergeChunkTexts).join('\n…(중략)…\n');
      const omitted = rows.length - picked.length;
      if (omitted > 0) text += '\n(※ 이 조문은 전체 ' + rows.length + '조각 중 ' + picked.length + '조각만 실었습니다. 보이지 않는 항·호가 있을 수 있습니다.)';
      full.set(gk, { content: text, ids: picked.map(function (r) { return r.id; }), parts: picked.length, whole: omitted === 0 });
      }
    }
    const out = [], addedIds = [], done = new Set();
    const knownIds = new Set((chunks || []).map(function (c) { return c && c.id; }));
    for (const c of chunks || []) {
      const key = articleKey(c && c.article_no);
      const gk = key && c.doc_name ? c.doc_name + '|' + key : null;
      if (gk && full.has(gk)) {
        if (done.has(gk)) continue;                       // 같은 조의 다른 조각 — 첫 원소에 합쳐졌다
        done.add(gk);
        const f = full.get(gk);
        out.push(Object.assign({}, c, { content: f.content, _full: f.whole, _parts: f.parts }));
        for (const id of f.ids) if (typeof id === 'number' && !knownIds.has(id) && addedIds.indexOf(id) === -1) addedIds.push(id);
      } else out.push(c);
    }
    return { chunks: out, addedIds: addedIds, expanded: full.size };
  }

  // 역참조 발췌(#155-보론4, 운영자 결정 2026-09-11): 검색된 조문 X를 **인용하는** 같은 법령의 다른 조문에서
  // 인용 문장(그 줄)만 잘라 온다 — 제재(제20조 등록취소)·조사(제51조)·준용 조항은 질문 어휘로는 검색되지 않지만
  // "제32조의4제5항에 따른 …"처럼 검색된 조문을 가리키므로 이 경로로 닿는다. AI 요약이 아니라 원문 발췌라 비용 0·오류 0.
  //   chunks: 순위순 조문 청크(정밀검색분 먼저)
  //   fetchCiting(doc_name, key) → 같은 문서에서 content에 '제'+key가 든 조각 [{id, doc_name, article_no, chunk_index, content}]
  //   opts.fetchArticle(doc_name, key) → 그 조문의 모든 조각(제재 조문의 항 머리 문장을 찾는 데 쓴다, 없으면 인용 조각 안에서만 찾는다)
  //   반환 { text: 프롬프트 블록, chunks: 검증용 의사 청크(_excerpt=true), ids: 발췌 원본 조각 id, sanctions: 제재 조문 수 }
  //
  // #230(2026-09-26) 보강 — 96760b6b 자문(대리점·판매점 사이 개인사업자) 재현에서 8칸이 이렇게 쓰였다:
  //  ① 6칸이 **다른 법령** 조문을 가리킨 줄이었다 — 「정보통신망법」…같은 법 제52조, 「벤처투자 촉진에 관한 법률」 제2조를
  //     '제52조·제2조 인용'으로 잡았다(citeRegex는 앞의 법령명을 보지 않는다).
  //  ② 4칸이 정의 조문(제2조) 인용 — 법령 거의 모든 조문이 정의 조문을 가리켜 칸만 먹는다.
  //  ③ 제재 조문은 법령 끝(벌칙 장)에 있어 chunk_index 오름차순·조문당 4칸에서 늘 잘린다 — 제32조의14를 인용하는 조문 6개 중
  //     제104조(과태료)가 6번째, 제50조는 제53조(과징금)·제99조(벌칙)·제104조가 5~9번째. 같은 질문 세 번 모두 제104조 0건.
  //  그래서: 다른 법령 참조 줄은 인용으로 치지 않고, 정의·목적 조문은 대상에서 빼고, 제재 조문(벌칙·과태료·과징금·이행강제금·
  //  양벌·몰수·추징)은 별도 칸(maxSanction)으로 먼저 뽑아 그 호가 속한 항의 머리 문장(금액·형량)까지 붙인다.
  function citeRegex(key) {
    // '32조의4'는 '제32조의40'과, '32조'는 '제32조의4'와 구분한다
    const esc = key.replace(/조의(\d+)$/, '조의$1').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp('제' + esc + (/조의\d+$/.test(key) ? '(?!\\d)' : '(?!의\\d)(?!\\d)'));
  }
  const CITING_SKIP_TITLE_RE = /\((?:정의|목적|용어의\s*정의|용어정의|용어의\s*뜻)\)/;
  // 발췌하지 않는 인용 조문 — 조문 번호만 늘어놓은 목록 조문(규제 재검토 기한·고유식별정보 처리 사무)과 목적 조문.
  // 20문항 재현에서 이런 줄('제29조제9항 … 등록 요건: 2022년 1월 1일')이 칸을 차지했다(#230).
  const CITER_SKIP_TITLE_RE = /\((?:목적|규제의\s*재검토|(?:민감정보\s*및\s*)?고유식별정보의\s*처리)\)/;
  function isSanctionTitle(articleNo) {
    const t = String(articleNo || '');
    return /(벌칙|과태료|과징금|양벌|이행강제금|몰수|추징)/.test(t) && !/벌칙\s*적용/.test(t);   // '벌칙 적용에서 공무원 의제'는 제재가 아니다
  }
  // 같은 대상 안에서 먼저 뽑는 순서 — 위반 자체의 제재(벌칙·과태료·과징금·양벌)가 명령 불이행 강제(이행강제금)·몰수보다 앞.
  // 96760b6b 재현: 제50조를 인용하는 제재 조문은 문서 순서로 제51조의2(자료제출 이행강제금)가 제53조(금지행위 과징금)보다 앞이다.
  function sanctionTier(articleNo) { return /(벌칙|과태료|과징금|양벌)/.test(String(articleNo || '')) ? 0 : 1; }
  // 조문 번호 바로 앞(before)이 다른 법령을 가리키는가 — 「…」 제N조 / 같은 법·동법 제N조 / (시행령·고시 안의) 법·영 제N조 /
  // 「」 없이 적은 법령명(전파법 제10조). 자기 법령은 법령명 없이 '제N조' 또는 '이 법 제N조'로 적는다.
  function isOtherLawRef(before) {
    let b = String(before || '').replace(/\s+$/, '');
    // 나열의 뒷 조문은 나열 머리의 법령을 따른다 — 「법 제89조의2, 제89조의3 및 제90조부터」의 제90조는 법(상위 법률) 조문.
    // 앞의 조·항·호와 이음말(,ㆍ 및 또는 부터 까지)만으로 된 꼬리를 걷어 내고(그 안에 '제N조'가 있을 때만) 나열 머리 앞을 본다.
    const run = b.match(/(?:제\s?\d+\s?(?:조(?:의\s?\d+)?|항|호(?:의\s?\d+)?)|[가-하]목|각\s?호|본문|단서|전단|후단|[,ㆍ·]|및|또는|부터|까지|이나|와|과|\s)+$/);
    if (run && /제\s?\d+\s?조/.test(run[0])) b = b.slice(0, run.index).replace(/\s+$/, '');
    if (/[」』]$/.test(b)) return true;
    // 「위치정보의 보호 및 이용 등에 관한 법률 시행령」(이하 "영"이라 한다) 제3조 — 괄호 하나를 건너 다시 본다
    const pb = b.replace(/\([^()]*\)$/, '').replace(/\s+$/, '');
    if (pb !== b && /[」』]$/.test(pb)) return true;
    const m = b.match(/([가-힣A-Za-z0-9·ㆍ]+)$/);
    if (!m) return false;
    const w = m[1];
    if (/^(법|영|령|규칙|시행령|시행규칙|고시|규정|동법|동령)$/.test(w))
      return !/(^|[^가-힣])이$/.test(b.slice(0, b.length - w.length).replace(/\s+$/, ''));
    return w.length >= 3 && /(법|법률|시행령|시행규칙|고시|규정|기준|지침)$/.test(w);
  }
  // content에서 key를 **자기 법령으로** 인용한 위치들
  function selfCiteIndexes(content, key) {
    const s = String(content || '');
    const re = new RegExp(citeRegex(key).source, 'g');
    const out = [];
    let m;
    while ((m = re.exec(s)) !== null) if (!isOtherLawRef(s.slice(Math.max(0, m.index - 80), m.index))) out.push(m.index);
    return out;
  }
  function excerptAt(content, at, maxLen) {
    const s = String(content || '');
    let start = s.lastIndexOf('\n', at);
    start = start === -1 ? 0 : start + 1;
    let end = s.indexOf('\n', at);
    if (end === -1) end = s.length;
    let unit = s.slice(start, end).trim();
    if (unit.length > maxLen) {
      const rel = at - start;
      const from = Math.max(0, rel - Math.floor(maxLen / 2));
      unit = (from > 0 ? '…' : '') + unit.slice(from, from + maxLen) + (from + maxLen < unit.length ? '…' : '');
    }
    return unit;
  }
  function excerptAround(content, re, maxLen) {
    const s = String(content || '');
    const m = s.match(re);
    return m ? excerptAt(s, m.index, maxLen) : '';
  }
  // 제재 조문 발췌 — 인용 줄(호)마다 그 줄이 속한 항의 머리 문장을 앞에 둔다. 금액·형량은 머리 문장에 있다
  // (예: 제104조⑤ "다음 각 호의 어느 하나에 해당하는 자에게는 1천만원 이하의 과태료를 부과하고, …" + 4의11. 제32조의14제1항…).
  // 머리 = 인용 줄에서 위로 올라가 처음 만나는 '①~⑳' 줄 또는 '제N조(…) 본문' 줄. 인용 줄 자체가 항이면(제53조① …) 머리는 없다.
  // 길이 상한(maxLen) 안에서 고르는 순서: 순위가 높은 대상(keys 앞쪽)을 인용한 줄 → 그 조문을 '위반'한 자를 적은 줄 → 문서 순서.
  // 제104조처럼 호가 수십 개인 조문에서 질문과 무관한 줄(제50조를 곁가지로 언급한 ①5호)이 칸을 먹지 않게 한다. 표시는 문서 순서.
  function sanctionExcerpt(fullText, keys, maxLen) {
    const lines = String(fullText || '').split('\n');
    const hits = [];
    for (let i = 0; i < lines.length; i++) {
      const L = lines[i];
      let at = -1, rank = -1;
      for (let k = 0; k < keys.length && at < 0; k++) { const ix = selfCiteIndexes(L, keys[k]); if (ix.length) { at = ix[0]; rank = k; } }
      if (at < 0) continue;
      let h = -1;
      for (let j = i; j >= 0; j--) {
        if (/^\s*[①-⑳]/.test(lines[j]) || /^\s*제\d+조(?:의\d+)?\s*\([^)]*\)\s*\S/.test(lines[j])) { h = j; break; }
      }
      hits.push({ i: i, h: h !== i ? h : -1, rank: rank, viol: /위반|하지\s*아니한|거부|금지행위를\s*한/.test(L.slice(at)) ? 0 : 1,
        item: excerptAt(L, at, 220), head: h >= 0 && h !== i ? excerptAt(lines[h], 0, 260) : '' });
    }
    const order = hits.slice().sort(function (a, b) { return a.rank - b.rank || a.viol - b.viol || a.i - b.i; });
    const pickedHeads = new Set(), picked = [];
    let total = 0;
    for (const x of order) {
      const add = (x.head && !pickedHeads.has(x.h) ? x.head.length + 1 : 0) + x.item.length + 1;
      if (total + add > maxLen && picked.length) continue;
      picked.push(x); total += add;
      if (x.head) pickedHeads.add(x.h);
    }
    picked.sort(function (a, b) { return a.i - b.i; });
    const outLines = [];
    let lastHead = null;
    for (const x of picked) {
      if (x.head && x.h !== lastHead) { outLines.push(x.head); lastHead = x.h; }
      outLines.push(x.item);
    }
    const dropped = hits.length - picked.length;
    return outLines.join('\n') + (dropped ? '\n…(이 조문에서 같은 조문을 인용하는 줄 ' + dropped + '개 더 있음)' : '');
  }
  async function buildCitingExcerpts(chunks, fetchCiting, opts) {
    opts = opts || {};
    const maxPer = opts.maxPerArticle != null ? opts.maxPerArticle : 4;
    const maxTotal = opts.maxTotal != null ? opts.maxTotal : 8;
    const maxLen = opts.maxLen != null ? opts.maxLen : 300;
    const maxSanction = opts.maxSanction != null ? opts.maxSanction : 6;
    const maxSanctionPer = opts.maxSanctionPerArticle != null ? opts.maxSanctionPerArticle : 2;
    const sanctionLen = opts.sanctionMaxLen != null ? opts.sanctionMaxLen : 900;
    const fetchArticle = typeof opts.fetchArticle === 'function' ? opts.fetchArticle : null;
    const have = new Set();          // 이미 컨텍스트에 있는 doc|key — 발췌 불필요
    const targets = [];
    for (const c of chunks || []) {
      const k = articleKey(c && c.article_no);
      if (!k || !c.doc_name) continue;
      const gk = c.doc_name + '|' + k;
      if (have.has(gk)) continue;
      have.add(gk);
      if (CITING_SKIP_TITLE_RE.test(String(c.article_no || ''))) continue;   // 정의·목적 조문은 대상에서 뺀다(#230)
      targets.push({ doc: c.doc_name, key: k });
    }
    // 조회는 expandArticles와 같은 묶음(B-2, #201) — 필요한 묶음까지만 받는다(뒤 대상은 상한에 닿으면 조회하지 않는다).
    const wave = opts.fetchConcurrency != null ? opts.fetchConcurrency : 6;
    const fetched = new Array(targets.length);
    async function rowsOf(i) {
      if (fetched[i] === undefined) {
        const w0 = i - (i % wave);
        const batch = targets.slice(w0, w0 + wave);
        const res = await Promise.all(batch.map(function (bt) {
          return Promise.resolve().then(function () { return fetchCiting(bt.doc, bt.key); })
            .then(function (r) { return r || []; }, function () { return []; });
        }));
        res.forEach(function (r, j) {
          fetched[w0 + j] = r.slice().sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
        });
      }
      return fetched[i];
    }
    const citerOk = function (r, t) {
      const rk = articleKey(r.article_no);
      if (!rk || rk === t.key) return null;                                    // 자기 자신
      if (/^(부칙|별표|서식|별지|붙임)/.test(String(r.article_no || '')) || CITER_SKIP_TITLE_RE.test(String(r.article_no || ''))) return null;
      const gk = r.doc_name + '|' + rk;
      if (have.has(gk)) return null;                                           // 이미 실린 조문
      const at = selfCiteIndexes(r.content, t.key);
      return at.length ? { gk: gk, at: at[0] } : null;                         // 다른 법령 조문만 가리키면 인용 아님(#230)
    };
    // ① 제재 조문 — 대상 순위순, 대상당 새 조문 maxSanctionPer개, 전체 maxSanction개. 이미 뽑힌 제재 조문이 다음 대상도
    //    인용하면 칸을 더 쓰지 않고 인용 줄만 합친다(제104조가 제32조의13·제32조의14·제50조를 모두 인용).
    //    대상당 2개: 96760b6b 재현에서 3개면 제52조(시정조치) 하나가 이행강제금·과징금(사업정지 갈음)·벌칙으로 칸을 채워
    //    정작 제50조 위반 과징금(제53조)이 밀려났다.
    const sanc = new Map();           // gk → {doc_name, article_no, key, keys:[], rows:[]}
    for (let i = 0; i < targets.length; i++) {
      if (sanc.size >= maxSanction && fetched[i] === undefined) break;        // 칸이 찼으면 받은 결과 안에서만 합친다
      const t = targets[i];
      const rows = (await rowsOf(i)).filter(function (r) { return isSanctionTitle(r.article_no); })
        .sort(function (a, b) { return sanctionTier(a.article_no) - sanctionTier(b.article_no) || (a.chunk_index || 0) - (b.chunk_index || 0); });
      let n = 0;
      for (const r of rows) {
        const ok = citerOk(r, t);
        if (!ok) continue;
        let e = sanc.get(ok.gk);
        if (!e) {
          if (sanc.size >= maxSanction || n >= maxSanctionPer) continue;
          e = { doc_name: r.doc_name, article_no: r.article_no, key: articleKey(r.article_no), keys: [], rows: [] };
          sanc.set(ok.gk, e); n++;
        }
        if (e.keys.indexOf(t.key) === -1) e.keys.push(t.key);
        if (!e.rows.some(function (x) { return x.id === r.id; })) e.rows.push(r);
      }
    }
    const sList = Array.from(sanc.values());
    const fulls = await Promise.all(sList.map(function (e) {
      if (!fetchArticle) return Promise.resolve(null);
      return Promise.resolve().then(function () { return fetchArticle(e.doc_name, e.key); })
        .then(function (r) { return (r || []).filter(function (x) { return articleKey(x.article_no) === e.key; }); }, function () { return null; });
    }));
    const sOut = [], ids = [];
    sList.forEach(function (e, si) {
      const all = (fulls[si] && fulls[si].length ? fulls[si] : e.rows).slice().sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
      const ex = sanctionExcerpt(mergeChunkTexts(all.map(function (x) { return x.content || ''; })), e.keys, sanctionLen);
      if (!ex) return;
      sOut.push({ doc_name: e.doc_name, article_no: e.article_no, cites: e.keys, excerpt: ex });
      // 원본 조각 id — 발췌에 들어간 줄(머리·인용 줄)이 있는 조각만(대시보드 검증이 이 조각들로 원문을 다시 읽는다)
      const exLines = ex.split('\n').map(function (l) { return l.replace(/^…|…$/g, '').slice(0, 40); }).filter(function (l) { return l.length >= 8; });
      for (const x of all) {
        if (typeof x.id !== 'number' || ids.indexOf(x.id) !== -1) continue;
        if (exLines.some(function (l) { return String(x.content || '').indexOf(l) !== -1; })) ids.push(x.id);
      }
    });
    // ② 그 밖의 역참조(조사·준용·시정명령 등) — 종전 규칙 그대로(대상당 maxPer, 전체 maxTotal), 제재 칸에 든 조문은 뺀다
    const out = [], seen = new Set(sanc.keys());
    for (let i = 0; i < targets.length && out.length < maxTotal; i++) {
      const t = targets[i];
      const rows = await rowsOf(i);
      const re = citeRegex(t.key);
      let n = 0;
      for (const r of rows) {
        if (n >= maxPer || out.length >= maxTotal) break;
        const ok = citerOk(r, t);
        if (!ok || seen.has(ok.gk)) continue;                                  // 중복
        const ex = excerptAt(r.content, ok.at, maxLen);
        if (!ex) continue;
        seen.add(ok.gk); n++;
        out.push({ doc_name: r.doc_name, article_no: r.article_no, cites: t.key, excerpt: ex });
        if (typeof r.id === 'number' && ids.indexOf(r.id) === -1) ids.push(r.id);
      }
    }
    if (!out.length && !sOut.length) return { text: '', chunks: [], ids: [], sanctions: 0 };
    let text = '';
    if (sOut.length) text += '\n\n---\n\n[검색된 조문을 위반했을 때의 제재 조문 — 발췌]\n' +
      '아래는 위 조문을 인용하는 같은 법령의 벌칙·과태료·과징금 등 제재 조문에서 **그 조문을 인용한 호와 그 호가 속한 항의 머리 문장(금액·형량)**만 ' +
      '잘라 온 것입니다. 위반 시 제재를 설명할 때는 이 발췌를 근거로 「법령명 제N조제M항제K호」까지 적고, 발췌에 없는 제재·금액을 기억으로 채우지 마세요.\n\n' +
      sOut.map(function (x, i) { return '[제재 ' + (i + 1) + '] ' + x.doc_name + ' 제' + x.article_no + ' — 제' + x.cites.join('·제') + ' 인용\n' + x.excerpt; }).join('\n\n');
    if (out.length) text += '\n\n---\n\n[검색된 조문을 인용하는 다른 조문 — 발췌]\n' +
      '아래는 위 조문을 가리키는 같은 법령의 다른 조문(조사·준용·시정명령 등)에서 **인용 문장만** 잘라 온 것입니다. 전문이 아니므로 ' +
      '이 발췌에 없는 항·호의 내용을 추정하지 마세요. 인용할 때는 「법령명 제N조」와 발췌에 보이는 항·호까지만 적으세요.\n\n' +
      out.map(function (x, i) { return '[역참조 ' + (i + 1) + '] ' + x.doc_name + ' 제' + x.article_no + ' — 제' + x.cites + ' 인용\n' + x.excerpt; }).join('\n\n');
    const pseudo = sOut.concat(out).map(function (x) { return { id: null, doc_name: x.doc_name, article_no: x.article_no, chunk_index: 0, content: x.excerpt, _excerpt: true }; });
    return { text: text, chunks: pseudo, ids: ids, sanctions: sOut.length };
  }

  // 시스템 프롬프트의 「■ 전파법 제16조(재할당) [원문 확인됨] …」 블록 → 의사 청크.
  // 이 조문들은 검색과 무관하게 매 자문에 실리므로, 대조 대상에 넣지 않으면 정당한 인용이 '미확인'이 된다.
  function pseudoChunksFromPrompt(prompt) {
    const out = [];
    const re = /■\s*(.+?)\s+제(\d+)조(?:의(\d+))?[^\n]*\n([\s\S]*?)(?=\n\s*■|$)/g;
    let m;
    const s = String(prompt || '');
    while ((m = re.exec(s))) {
      const head = s.slice(m.index, s.indexOf('\n', m.index));
      out.push({ id: null, doc_name: m[1].trim() + '(시스템 프롬프트 핵심 조문)', article_no: m[2] + '조' + (m[3] ? '의' + m[3] : ''),
        chunk_index: 0, content: head.replace(/^■\s*/, '') + '\n' + m[4].trim() });
    }
    return out;
  }

  // 인용 직전의 법령명 후보 — "실제로 판례에서 전기통신사업법 제32조의14"에서 뒤에서부터
  // ["전기통신사업법", "판례에서 전기통신사업법", ...] 순으로 돌려주고, 호출측이 문서명과 맞춰 본다.
  // "동법·같은 법·이 법·법 제N조"는 직전 인용의 법령을 이어받는다(inherit).
  function lawNameBefore(before) {
    // 「전기통신사업법」 제50조 — 낫표는 떼고 본다(#240: 종전에는 이름을 못 읽어 '법령 미상'이 되었다)
    let b = String(before || '').replace(/[「」『』]/g, ' ').replace(/\s+$/, '');
    while (/\)$/.test(b)) { const i = b.lastIndexOf('('); if (i < 0) break; b = b.slice(0, i).replace(/\s+$/, ''); }
    const m = b.match(/([가-힣A-Za-z0-9·ㆍ‧\s]{1,80})$/);
    if (!m) return null;
    const words = m[1].trim().split(/\s+/).filter(Boolean);
    if (!words.length) return null;
    const last = words[words.length - 1];
    const nl = norm(last);
    // level: '법 제N조'는 앞 법령이 시행령이어도 그 모법, '영 제N조'는 시행령(#240 — 종전엔 앞 법령 그 자체였다)
    if (/^(동법|같은법|이법|법)$/.test(nl)) return { inherit: true, level: '법' };
    if (/^(동령|같은영|이영|영)$/.test(nl)) return { inherit: true, level: '시행령' };
    if (/^(동규정|이규정|같은규정|이고시|동고시)$/.test(nl)) return { inherit: true };
    if (!LAW_SUFFIX_RE.test(last)) return null;
    // 「시행령 제42조」「같은 법 시행령 제5조」「및 시행령」 — 앞 낱말이 법령 이름이 아니면 이어받은 법령의 시행령·시행규칙(#240).
    // 종전에는 '시행령'·'법 시행령'이 이름 끝 일치로 검색 자료의 아무 '…법 시행령'에 붙었다.
    if (/^(시행령|시행규칙)$/.test(nl)) {
      const prev = words.length >= 2 ? words[words.length - 2] : '';
      const pn = norm(prev);
      if (!prev || !LAW_SUFFIX_RE.test(prev) || /^(동법|같은법|이법|법|동|같은|이)$/.test(pn) || /^(같은법|이법)$/.test(norm(words.slice(-3, -1).join(''))))
        return { subord: nl };
    }
    const cands = [];
    for (let k = Math.min(6, words.length); k >= 1; k--) cands.push(words.slice(-k).join(' '));
    return { candidates: cands, text: last };
  }
  function familyMatches(family, name) {
    const f = norm(family), n = norm(name);
    if (!f || !n) return false;
    if (f === n) return true;
    // "전기통신사업법" ≠ "전기통신사업법 시행령": 이름에 없는 하위법령 표지가 문서에 있으면 다른 문서
    if (/(시행령|시행규칙)$/.test(f) && !/(시행령|시행규칙)$/.test(n)) return false;
    if (f.endsWith(n)) return true;
    const alias = LAW_ALIASES[n];
    if (alias && f.indexOf(norm(alias)) !== -1) return true;
    return false;
  }
  // 낱말 하나짜리 일반어는 법령 이름으로 치지 않는다(#240) — 이름 끝 일치로 검색 자료의 아무 '…고시'·'…규정'에 붙었다.
  // 시행령·시행규칙만 적은 것은 lawNameBefore가 {subord}로 따로 돌려준다(앞에 나온 법령의 것, lawScope).
  const GENERIC_LAW_RE = /^(시행령|시행규칙|고시|규정|규칙|기준|지침|세칙|요령|훈령|예규|법률|협정|법령)$/;
  // 후보 목록을 문서군(family 목록)과 맞춰 하나로 확정. 못 맞추면 null — 그 뜻은 lawScope가 정한다.
  // #240에서 '이름을 못 맞추면 원문 없음'이 되었으므로 모델이 이름을 조금 달리 쓴 경우까지 맞춘다:
  //  1) 이름 그대로(끝 일치·약칭)  2) 끝에 덧붙인 종류 낱말을 뗀 이름 — 「…세부사항 고시」 → 문서명 「…세부사항」(dd26eb98 실측)
  //  3) 줄여 쓴 이름 — 낱말 2개 이상이 문서명에 순서대로 다 있고 그런 문서가 하나뿐일 때만(둘 이상이면 못 맞춘 것으로)
  const TYPE_TAIL_RE = /^(고시|규정|규칙|기준|지침|세칙|요령|훈령|예규|협정)$/;   // 시행령·시행규칙은 떼지 않는다(다른 문서다)
  function stripTypeTail(cand) {
    const w = String(cand || '').trim().split(/\s+/);
    return (w.length >= 2 && TYPE_TAIL_RE.test(norm(w[w.length - 1]))) ? w.slice(0, -1).join(' ') : null;
  }
  const isSubDoc = function (s) { return /(시행령|시행규칙)$/.test(norm(s)); };
  function resolveLaw(nameInfo, families) {
    if (!nameInfo || !nameInfo.candidates) return null;
    for (const cand of nameInfo.candidates) {
      if (GENERIC_LAW_RE.test(norm(cand))) continue;
      // 끝 일치가 여러 문서에 걸리면(「기술기준」 → 기술기준으로 끝나는 고시 여럿) 같은 이름이 있을 때만 — 아니면 더 긴/다른 후보로
      const hits = families.filter(function (f) { return familyMatches(f, cand); });
      if (hits.length === 1) return hits[0];
      const exact = hits.find(function (f) { return norm(f) === norm(cand); });
      if (exact) return exact;
    }
    for (const cand of nameInfo.candidates) {
      const s = stripTypeTail(cand);
      if (!s || GENERIC_LAW_RE.test(norm(s))) continue;
      const hit = families.find(function (f) { return familyMatches(f, s); });
      if (hit) return hit;
    }
    for (const cand of nameInfo.candidates) {
      // 가운뎃점도 낱말 경계 — 「통신시설 등급 지정·관리 기준」 ↔ 문서명 「주요통신사업자의 통신시설 등급 지정 및 관리 기준」(992c7fb8)
      const words = (stripTypeTail(cand) || cand).split(/[\s·ㆍ‧•]+/).map(norm).filter(Boolean);
      if (words.length < 2) continue;
      const hits = families.filter(function (f) {
        if (isSubDoc(f) && !isSubDoc(cand)) return false;
        const nf = norm(f);
        let pos = 0;
        for (const w of words) { const i = nf.indexOf(w, pos); if (i < 0) return false; pos = i + w.length; }
        return true;
      });
      if (hits.length === 1) return hits[0];
    }
    return null;
  }
  function baseOf(s) { return String(s || '').replace(/\s*(시행령|시행규칙)\s*$/, '').trim(); }
  // 이름 적힌 법령과 같은 계열(법·시행령·시행규칙)의 문서군
  function groupFor(nameInfo, families) {
    if (!nameInfo || !nameInfo.candidates) return [];
    const own = resolveLaw(nameInfo, families);
    if (own) {
      const b = norm(baseOf(own));
      return families.filter(function (f) { return norm(baseOf(f)) === b; });
    }
    for (const cand of nameInfo.candidates) {
      const cb = baseOf(cand);
      if (!cb || GENERIC_LAW_RE.test(norm(cb))) continue;
      const hits = families.filter(function (f) { return familyMatches(baseOf(f), cb); });
      if (hits.length) return hits;
    }
    return [];
  }
  // 인용 하나를 대조할 수 있는 문서군 목록(앞이 우선). null = 법령 미상(어느 문서든, 종전), [] = 대조할 문서 없음(→ 원문 없음).
  // 번호만 같은 다른 법령 조문과 대조하던 오판(#240 — 전기통신사업법 제53조① 표시가 재난안전법 시행령 제50조와 대조돼
  // 맞는 인용이 '원문과 다름'이 되고, 다음 답이 그 표시를 보고 유효 근거를 버렸다)을 막는 규칙:
  //  ① 법령 이름을 적었으면 그 법령만 — 검색 자료에 없으면 원문 없음
  //  ② '동법·같은 법·법'은 이어받은 법령(ctx), '시행령·시행규칙'만 적었으면 이어받은 법령 계열의 시행령·시행규칙
  //  ③ 이름 없이 '제N조'만 있으면 이어받은 법령 → 같은 계열 순. 이어받을 법령이 없을 때만 어느 문서든
  function lawScope(info, ctx, families) {
    if (info && info.inherit) {
      const level = info.level;
      info = ctx; ctx = null;
      if (level && info && info.candidates) {
        const grp = groupFor(info, families);
        const own = resolveLaw(info, families);
        if (level === '법') {
          const acts = grp.filter(function (f) { return !isSubDoc(f); });
          if (acts.length) return acts;
          if (own && isSubDoc(own)) return [];   // 앞 법령은 시행령인데 그 모법은 검색 자료에 없다
        } else {
          return grp.filter(function (f) { return /시행령$/.test(norm(f)); });
        }
      }
    }
    if (info && info.subord) {   // '시행령 제N조'·'같은 법 시행령' — 이어받은 법령 계열의 시행령·시행규칙
      const pool = ctx && ctx.candidates ? groupFor(ctx, families) : families;
      return pool.filter(function (f) { return norm(f).endsWith(info.subord); });
    }
    if (info && info.candidates) {
      const hit = resolveLaw(info, families);
      return hit ? [hit] : [];   // 못 맞추면 원문 없음 — '관련 고시 제5조'처럼 막연한 이름도 아무 고시에 붙이지 않는다
    }
    if (!ctx || !ctx.candidates) return null;
    const own = resolveLaw(ctx, families);
    const out = own ? [own] : [];
    for (const f of groupFor(ctx, families)) if (out.indexOf(f) === -1) out.push(f);
    return out;
  }

  // 표시 하나의 앞 문단에서 인용 대상을 읽는다.
  // 반환 mentions = 등장 순서의 조 언급 목록(조마다 항·호·앞 법령명). key/paras/items/lawInfo는 첫 언급(primary) —
  // 실제 대상 선택은 checkCitation이 "컨텍스트에 있고 인용문과 가장 많이 겹치는 후보"로 한다(#155-보론3: 조문을 통째로
  // 인용하면 그 안의 교차참조(제52조·제53조)가 먼저 잡혀 정작 인용 대상(앞 줄 제목의 제50조)을 놓쳤다).
  function parseSegment(segment) {
    const s = String(segment || '').replace(/\*\*/g, '');
    const artRe = /제\s?(\d+)\s?조(?:\s?의\s?(\d+))?/g;
    const raw = [];
    let a;
    while ((a = artRe.exec(s))) raw.push({ idx: a.index, end: a.index + a[0].length, key: a[1] + '조' + (a[2] ? '의' + a[2] : '') });
    if (!raw.length) {
      // 별표·별지(서식) — 앞의 법령 이름도 읽는다(#240: 존재 확인을 그 법령의 별표로 좁힌다). 「시행령 [별표 4]」의 '['는 떼고 본다
      const bm = s.match(/별표\s*제?\s*(\d+(?:\s*의\s*\d+)?)|별지\s*(?:제\s*)?(\d+)\s*(?:호)?(?:\s*의\s*(\d+))?/);
      if (!bm) return { kind: 'none' };
      const lawInfo = lawNameBefore(s.slice(0, bm.index).replace(/[\s\[【「『<(]+$/, ' '));
      if (bm[1]) return { kind: 'annex', annexType: '별표', annex: bm[1].replace(/\s+/g, ''), lawInfo: lawInfo };
      return { kind: 'annex', annexType: '별지', annex: bm[2] + (bm[3] ? '의' + bm[3] : ''), lawInfo: lawInfo };
    }
    const byKey = new Map();
    const mentions = [];
    let lastNamed = null;   // 이 글에서 앞서 이름이 나온 법령 — 이름 없는 '제N조'·'동법'·'시행령'이 이어받는다(#240)
    for (let i = 0; i < raw.length; i++) {
      const m = raw[i];
      let rec = byKey.get(m.key);
      if (!rec) {
        rec = { key: m.key, idx: m.idx, paras: [], items: [], lawInfo: lawNameBefore(s.slice(0, m.idx)), ctxLaw: lastNamed };
        byKey.set(m.key, rec); mentions.push(rec);
        if (rec.lawInfo && rec.lawInfo.candidates) lastNamed = rec.lawInfo;
      }
      const stop = i + 1 < raw.length ? raw[i + 1].idx : s.length;
      const tail = s.slice(m.end, stop);
      let pm;
      const pRe = /제\s?(\d+)\s?항/g;
      while ((pm = pRe.exec(tail))) if (rec.paras.indexOf(+pm[1]) === -1) rec.paras.push(+pm[1]);
      // 원문자 항 표기(제5조①)는 조 바로 뒤에 붙은 것만 — 답변 본문의 ①②③ 나열과 섞이지 않게
      const cm = tail.match(/^\s*(?:\([^)]*\))?\s*([①-⑳])/);
      if (cm) { const n = CIRCLED.indexOf(cm[1]) + 1; if (rec.paras.indexOf(n) === -1) rec.paras.push(n); }
      const iRe = /(?:제\s?)?(\d+)\s?호(?:\s?의\s?(\d+))?/g;
      while ((pm = iRe.exec(tail))) { const it = pm[1] + (pm[2] ? '의' + pm[2] : ''); if (rec.items.indexOf(it) === -1) rec.items.push(it); }
    }
    const p = mentions[0];
    return { kind: 'article', key: p.key, paras: p.paras, items: p.items, lawInfo: p.lawInfo, mentions: mentions };
  }

  // 인용문(답변 문장)이 원문 텍스트와 얼마나 그대로 겹치는가 — 0~1. 공백·가운뎃점·따옴표·괄호를 뗀 뒤
  // 18자 창을 8자씩 밀며 원문에 있는지 센다. 통째 인용은 ≈1, 바꿔 쓴 설명은 ≈0.
  function normQ(s) {
    return String(s || '').replace(/\*\*/g, '').replace(/\[[^\]]*\]/g, '')
      .replace(/[\s·ㆍ‧•'"“”‘’「」『』()（）\[\],.:;、。…\-—–]/g, '');
  }
  function quoteOverlap(claim, text) {
    const a = normQ(claim), b = normQ(text);
    if (a.length < 12 || !b) return 0;
    const W = 18, S = 8;
    let hits = 0, n = 0;
    if (a.length <= W) return b.indexOf(a) !== -1 ? 1 : 0;
    for (let i = 0; i + W <= a.length; i += S) { n++; if (b.indexOf(a.slice(i, i + W)) !== -1) hits++; }
    return n ? hits / n : 0;
  }
  // 0.85 (2026-09-14, #169-보론5). 종전 0.6은 18자 조각의 40%가 원문에 없어도 '원문 그대로'로
  // 보고 Haiku 판정을 건너뛰었다 — 실측: '1년 이내'→'2년 이내', 주체 '장관'→'방미통위'가 0.75다.
  // 그 구간(0.6~0.85)이 가장 위험하다: 뼈대는 원문인데 수치·주체 한 곳이 바뀐 문장이 여기 떨어진다.
  const VERBATIM_MIN = 0.85;
  // 1등과 2등 겹침이 이만큼도 차이 나지 않으면 어느 조문인지 단정하지 않는다.
  // 같은 문언이 두 조문에 있을 때 겹침 최대값은 동전 던지기가 된다(#169-보론4 실측).
  const AMBIG_MARGIN = 0.08;   // 이 이상 겹치면 "원문 그대로 인용" — 번호 파싱 없이 확인됨, Haiku 판정 생략

  // 답변에서 표시를 전부 찾아 각 표시의 인용 대상을 붙인다
  function findCitations(answer) {
    const text = String(answer || '');
    const cites = [];
    let m, prevEnd = 0, lastLaw = null;
    TAG_RE.lastIndex = 0;
    while ((m = TAG_RE.exec(text))) {
      const tagStart = m.index, tagEnd = m.index + m[0].length;
      // 범위는 좁은 것부터: 같은 줄(불릿 한 항목) → 같은 문단 → 직전 표시 이후 1,200자.
      // 불릿 목록은 줄마다 다른 조문이라, 문단 전체로 잡으면 앞 불릿의 조문이 '첫 인용'으로 잡힌다
      // (실측: 「- 제52조의3제2항: …」 다음 줄의 업무처리규정 제11조 표시가 제52조의3로 읽혔다).
      const li = text.lastIndexOf('\n', tagStart - 1);
      const lineStart = li === -1 ? 0 : li + 1;
      const pi = text.lastIndexOf('\n\n', tagStart);
      const paraStart = pi === -1 ? 0 : pi + 2;
      const floor = Math.max(prevEnd, tagStart - 1200);
      const starts = [Math.max(prevEnd, lineStart), Math.max(prevEnd, paraStart), floor]
        .filter(function (v, i, a) { return a.indexOf(v) === i; });
      let segStart = starts[0], parsed = parseSegment(text.slice(segStart, tagStart));
      for (let k = 1; k < starts.length && parsed.kind === 'none'; k++) {
        segStart = starts[k]; parsed = parseSegment(text.slice(segStart, tagStart));
      }
      // 후보 조문은 **앞의 비어 있지 않은 줄 2개**까지 더 본다(직전 표시 이후로 한정) — 「## 금지행위(제50조)」 제목이나
      // 「업무처리규정 제11조는 다음과 같이 규정합니다.」 다음 줄에 조문을 통째로 옮기는 답변 형식 때문. 인용문(segment)은 넓히지 않는다.
      let extStart = segStart, linesBack = 0;
      while (linesBack < 2 && extStart > prevEnd) {
        const j = text.lastIndexOf('\n', extStart - 2);        // 직전 줄의 시작(-1이면 문서 첫 줄)
        const start = Math.max(prevEnd, j === -1 ? 0 : j + 1);
        if (text.slice(start, extStart).trim()) linesBack++;    // 빈 줄은 세지 않는다
        extStart = start;
      }
      extStart = Math.max(prevEnd, extStart, tagStart - 1600);
      // 표시 뒤 문단(다음 표시·빈 줄·900자까지) — 꼬리표를 제목 줄에 붙이고 내용은 그 아래에 쓰는 답변 형식
      // (「**② 전기통신사업법 제32조의14(…) [원문 확인됨]**\n① 대리점은 …」)에서 인용문은 뒤에 있다(#155-보론5).
      const nextTag = (function () { TAG_RE.lastIndex = tagEnd; const nm = TAG_RE.exec(text); TAG_RE.lastIndex = tagEnd; return nm ? nm.index : text.length; })();
      const blank = text.indexOf('\n\n', tagEnd + 1);
      const after = text.slice(tagEnd, Math.min(nextTag, blank === -1 ? text.length : blank + 1, tagEnd + 900));
      // line = 표시가 있는 줄만(조 번호가 없어 segment가 앞 문단으로 넓어졌어도 겹침 판정은 이 줄로도 본다)
      const c = Object.assign({ tagStart: tagStart, tagEnd: tagEnd, tag: m[0], segment: text.slice(segStart, tagStart), line: text.slice(starts[0], tagStart), after: after }, parsed);
      // 꼬리표 안에 대상이 적힌 형식(#155-보론6, 2026-09-11 운영자 결정): 「[원문 확인됨: 전기통신사업법 제32조의14제1항]」
      // 「[원문 확인됨: 전파법 시행령 별표 3]」 — 있으면 앞뒤 문장 추측 없이 이것이 1순위 후보. 옛 형식(「[원문 확인됨]」,
      // 「[원문 확인됨, 참조4]」)은 종전대로 앞뒤에서 추측한다.
      const inner = m[0].slice(1, -1).replace(/^원문\s*확인됨/, '').replace(/^[\s:：—\-–,]+/, '').trim();
      // 인용문(과 앞 줄)에서 마지막으로 이름이 나온 법령 — 표시 대상이 이름 없이 '제N조'·'별표 N'만 적혔을 때 이어받는다
      const segNamed = (parsed.mentions || []).filter(function (x) { return x.lawInfo && x.lawInfo.candidates; });
      const segLaw = segNamed.length ? segNamed[segNamed.length - 1].lawInfo : (parsed.kind === 'annex' && parsed.lawInfo && parsed.lawInfo.candidates ? parsed.lawInfo : null);
      const tp = (inner && /제\s?\d+\s?조|별표\s*제?\s*\d+|별지\s*(?:제\s*)?\d+/.test(inner)) ? parseSegment(inner + ' ') : null;
      if (tp && tp.kind === 'annex') {
        // 표시에 별표·별지가 적혀 있으면 그것이 대상 — 앞 문장의 조 번호(「법 제50조제1항제5호 및 시행령 [별표 4]」의 제50조)로
        // 넘어가지 않는다(#240: 「[원문 확인됨: 전기통신사업법 시행령 별표 4]」가 법 제50조와 대조돼 맞는 인용이 '원문과 다름')
        c.tagTarget = { key: null, annex: tp.annex, fromTag: true };
        Object.assign(c, { kind: 'annex', annexType: tp.annexType, annex: tp.annex, lawInfo: tp.lawInfo, key: null, paras: [], items: [], mentions: [], candidates: null });
        c.ctxLaw = segLaw || lastLaw;
      } else if (tp && tp.kind === 'article') {
        c.tagTarget = Object.assign({}, tp.mentions[0], { fromTag: true });
        c.tagTargets = tp.mentions.map(function (x) { return Object.assign({}, x, { fromTag: true }); });
        if (c.kind !== 'article') Object.assign(c, { kind: 'article', key: tp.key, paras: tp.paras, items: tp.items, lawInfo: tp.lawInfo, mentions: [] });
      } else if (c.kind === 'annex') {
        c.ctxLaw = lastLaw;
      }
      if (c.kind === 'article') {
        if (c.lawInfo && c.lawInfo.candidates) c.lawText = c.lawInfo.text;
        // 후보 = 인용문 안의 조 + 앞 줄에만 있는 조(뒤에 붙임 — 겹침이 같으면 인용문 안의 조가 우선)
        const inSeg = new Set(c.mentions.map(function (x) { return x.key; }));
        const ext = extStart < segStart ? parseSegment(text.slice(extStart, tagStart)) : null;
        c.candidates = c.mentions.slice();
        if (ext && ext.kind === 'article') {
          for (const x of ext.mentions) if (!inSeg.has(x.key)) c.candidates.push(Object.assign({}, x, { extOnly: true }));
        }
        // 이름 없는 조·'동법'은 같은 글에서 앞서 이름이 나온 법령, 없으면 직전 인용의 법령을 이어받는다(lawScope)
        for (const x of c.candidates) x.ctxLaw = x.ctxLaw || lastLaw;
        if (c.tagTarget) {
          // 표시에 대상이 적혀 있으면 **그 대상만** 대조한다(#240). 종전에는 인용문 속 조 번호도 후보로 두어, 적힌 대상
          // (전기통신사업법 제53조)이 검색 자료에 없으면 인용한 조문 안의 교차참조(「제50조제1항을 위반한…」)로 넘어가
          // 번호만 같은 다른 법령 조문과 대조했다 — 있어야 할 결과는 '원문 없음'이다.
          const byKey = new Map(c.candidates.map(function (x) { return [x.key, x]; }));
          c.candidates = c.tagTargets.map(function (t) {
            if (!t.ctxLaw) {
              const s = byKey.get(t.key);
              t.ctxLaw = s ? ((s.lawInfo && s.lawInfo.candidates) ? s.lawInfo : s.ctxLaw) : (segLaw || lastLaw);
            }
            return t;
          });
          c.key = c.tagTarget.key; c.paras = c.tagTarget.paras; c.items = c.tagTarget.items;
          if (c.tagTarget.lawInfo && c.tagTarget.lawInfo.candidates) { c.lawInfo = c.tagTarget.lawInfo; c.lawText = c.tagTarget.lawInfo.text; }
        }
      } else if (c.kind === 'none' && extStart < segStart) {
        // 인용문에 조 번호가 없어도 앞 줄에 있으면 그것이 대상 (「제11조는 다음과 같이 규정합니다.」 + 원문 줄)
        const ext = parseSegment(text.slice(extStart, tagStart));
        if (ext.kind === 'article') {
          Object.assign(c, ext, { kind: 'article' });
          c.candidates = ext.mentions.map(function (x) { return Object.assign({}, x, { extOnly: true }); });
          for (const x of c.candidates) x.ctxLaw = x.ctxLaw || lastLaw;
        }
      }
      // 토막 문단 표시(#176, 2026-09-20): 모델이 인용문을 한 문단에 쓰고 표시는 다음 문단의 토막("고 하면서,"·
      // "을 열거하고 있습니다.")에 붙이는 습관이 있다. 9/17 대시보드 답변의 '확인 안 됨' 5건이 전부 이 오탐이었다 —
      // 토막을 인용문으로 잡거나(내용 없음) 표시 뒤 문단(다음 절)을 인용문으로 잡았다(엉뚱한 불일치).
      // 규칙: 꼬리표에만 대상이 있고(줄 자체에 조 번호 없음) 그 줄의 본문이 24자 미만이면, **앞으로** 거슬러 올라가
      // 본문이 있는 첫 문단(최대 3개, 직전 표시 경계를 넘어도 됨)을 인용문으로 쓴다. 그 문단에 같은 조의 표시가
      // 이미 있으면(직전 인용문의 자동 확인 등) 이 표시는 중복이라 지운다. 제목 줄 표시(#155-보론5)는 줄에 조 번호가
      // 있어 여기 걸리지 않고 종전대로 뒤 문단을 본다.
      if (c.tagTarget && !(parsed.mentions && parsed.mentions.length) && stripCiteBody(c.line).length < 24) {
        let pEnd = text.lastIndexOf('\n\n', tagStart), looked = 0;
        while (pEnd > 0 && looked < 3) {
          const pStart = text.lastIndexOf('\n\n', pEnd - 1);
          const para = text.slice(pStart === -1 ? 0 : pStart + 2, pEnd);
          // ⚠️ TAG_RE(전역 정규식)를 여기서 쓰면 lastIndex가 0으로 초기화돼 바깥 while이 처음부터 다시 돌며 무한 루프가 된다
          const body = para.replace(/\[원문\s*확인됨[^\]]*\]/g, '');
          if (stripCiteBody(body).length >= 24) {
            c.claimOverride = body;
            const prevKeys = [];
            const kre = /\[원문\s*확인됨[^\]]*?제\s*(\d+조(?:의\d+)?)/g;
            let km;
            while ((km = kre.exec(para)) !== null) prevKeys.push(km[1]);
            if (prevKeys.indexOf(c.tagTarget.key) !== -1) c.dupOfPrev = true;
            break;
          }
          if (para.trim()) looked++;
          pEnd = pStart;
        }
      }
      // 기계가 붙인 인용 대조 표시(#230)는 그 인용 문단(문장 안 따옴표 인용이면 따옴표 속)만 인용문으로 본다 — 인용 줄에 조 번호가 없으면
      // segment가 앞 문단들로 넓어져 모델의 해설까지 판정기에 넘어갔다(96760b6b 모의: 제50조 인용문에 앞 절의 장려금 해설이 섞임)
      if (m[0].indexOf(QUOTE_MARK) !== -1) {
        const pre = text.slice(Math.max(prevEnd, paraStart), tagStart).replace(/\s+$/, '');
        const qm = pre.match(/["“]([^"”\n]{25,})["”]$/);   // 문장 안 따옴표 인용이면 따옴표 속만
        c.claimOverride = qm ? qm[1] : pre;
      }
      cites.push(c);
      prevEnd = tagEnd;
      if (c.kind === 'article' && c.lawInfo && c.lawInfo.candidates) lastLaw = c.lawInfo;
    }
    return cites;
  }

  // 2) 인용 하나를 검색 원문과 대조
  function checkCitation(cite, chunks, annexSources) {
    if (cite.kind === 'none') return { status: 'unparsed', reason: '인용 조문을 읽지 못함' };
    const families = [];
    for (const c of chunks || []) { const f = docFamily(c.doc_name); if (f && families.indexOf(f) === -1) families.push(f); }
    if (cite.kind === 'annex') {
      // 별표·별지는 있는지만 본다(판정기에 보내지 않음). 법령 이름이 있으면 그 법령의 것만(#240 — 종전엔 아무 법령의
      // 같은 번호 별표가 있어도 확인됨이었다). 별표 출처 문자열은 「<법령> 별표 4」「<법령> 별표 4 머리」 꼴
      const label = cite.annexType || '별표';
      const want = norm(label + cite.annex);
      const pool = [];
      for (const s of annexSources || []) {
        const t = String(s), i = t.search(/별표|별지/);
        if (i >= 0) pool.push({ fam: t.slice(0, i).trim(), key: norm(t.slice(i)).replace(/머리$/, '') });
      }
      for (const c of chunks || []) pool.push({ fam: docFamily(c.doc_name), key: norm(String(c.article_no || '').split('(')[0]) });
      const fams = families.slice();
      for (const p of pool) if (p.fam && fams.indexOf(p.fam) === -1) fams.push(p.fam);
      const scope = lawScope(cite.lawInfo, cite.ctxLaw, fams);
      const hit = pool.find(function (p) { return p.key === want && (!scope || scope.indexOf(p.fam) !== -1); });
      const lawLabel = (scope && scope[0]) || (cite.lawInfo && cite.lawInfo.text) || '';
      return hit ? { status: 'ok', kind: 'annex', lawDoc: hit.fam || null }
        : { status: 'missing', reason: (lawLabel ? lawLabel + ' ' : '') + label + ' ' + cite.annex + ' 원문 없음', lawDoc: (scope && scope[0]) || null };
    }
    // 문서·조별 정본 텍스트 (같은 조가 현행·시행예정 두 판으로 있을 수 있어 문서별로 묶는다)
    const articleText = new Map();   // doc_name|key → merged text
    for (const c of chunks || []) {
      const k = articleKey(c.article_no);
      if (!k) continue;
      const gk = c.doc_name + '|' + k;
      if (!articleText.has(gk)) articleText.set(gk, []);
      articleText.get(gk).push(c);
    }
    const mergedOf = function (gk) {
      const list = articleText.get(gk).slice().sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
      return mergeChunkTexts(list.map(function (c) { return c.content || ''; }));
    };
    // 인용문: 표시 앞 문장. 앞이 제목·조 번호뿐(내용 40자 미만)이면 표시 뒤 문단이 인용문이다(#155-보론5).
    // 토막 문단 표시면 앞 문단(claimOverride, #176)이 인용문이다
    const before = cite.claimOverride || cite.segment || '';
    // 내용 길이 = 조 번호·괄호 제목·법령명을 뺀 나머지(정규화 24자 미만이면 "제목·번호뿐")
    const stripCite = stripCiteBody;
    const beforeBody = stripCite(before);
    const headingOnly = beforeBody.length < 24 && normQ(cite.after || '').length >= 24;
    const claim = headingOnly ? cite.after : before;

    // 후보 조문과 각 후보가 대조될 수 있는 문서군(lawScope — 이름 적은 법령만 / 이어받은 법령 계열만, #240)
    const candidates = (cite.candidates && cite.candidates.length) ? cite.candidates : [{ key: cite.key, paras: cite.paras || [], items: cite.items || [], lawInfo: cite.lawInfo, ctxLaw: cite.ctxLaw }];
    const scopes = candidates.map(function (cand) { return lawScope(cand.lawInfo, cand.ctxLaw, families); });

    // ① 원문 그대로 인용이면 번호 파싱과 무관하게 확인됨 — 어느 조문(별표 포함)의 텍스트와 겹치는지 본다.
    //    (통째 인용 안의 교차참조가 엉뚱한 조를 가리켜 '미확인'이 되던 오판 방지, #155-보론3). 앞·뒤 중 큰 쪽.
    //    표시에 적힌 대상과 다른 조문이어도 확인됨(#155-보론6 '꼬리표 오기 교정') — 글자 그대로 일치는 거짓 '원문과 다름'을
    //    만들지 않으므로 #240의 대상 제한은 ②(번호로 고르는 경로)에만 건다.
    let vbBest = null, vbRatio = 0;
    for (const gk of articleText.keys()) {
      const t = mergedOf(gk);
      const r = Math.max(quoteOverlap(before, t), cite.line ? quoteOverlap(cite.line, t) : 0, cite.after ? quoteOverlap(cite.after, t) : 0);
      if (r > vbRatio) { vbRatio = r; vbBest = gk; }
    }
    if (vbBest && vbRatio >= VERBATIM_MIN) {
      const [doc, key] = [vbBest.slice(0, vbBest.lastIndexOf('|')), vbBest.slice(vbBest.lastIndexOf('|') + 1)];
      return { status: 'ok', kind: 'article', lawDoc: docFamily(doc), doc: doc, key: key, text: mergedOf(vbBest), verbatim: true, overlap: vbRatio, claim: claim, reason: '원문 그대로 인용(' + Math.round(vbRatio * 100) + '%)' };
    }

    // ② 후보 조문(표시에 적힌 대상, 없으면 인용문 안 → 앞 줄) 중 컨텍스트에 있는 것을 고른다 — 여럿이면 인용문과 가장 많이
    //    겹치는 것, 같으면 앞의 것. 문서는 lawScope 순서(이름 적은 법령 → 이어받은 법령 → 같은 계열)로 처음 있는 문서군
    let chosen = null, chosenRatio = -1, chosenDoc = null, chosenText = '', chosenLaw = null;
    const misses = [];
    for (let ci = 0; ci < candidates.length; ci++) {
      const cand = candidates[ci], scope = scopes[ci];
      let lawDoc = null;
      let cands = (chunks || []).filter(function (c) { return articleKey(c.article_no) === cand.key; });
      if (scope) {
        let picked = [];
        for (const f of scope) {
          const x = cands.filter(function (c) { return docFamily(c.doc_name) === f; });
          if (x.length) { picked = x; lawDoc = f; break; }
        }
        cands = picked;
      }
      if (!cands.length) {
        const ctxText = cand.ctxLaw && cand.ctxLaw.text;
        misses.push(((scope && scope[0]) || (cand.lawInfo && cand.lawInfo.text) || ctxText || '') + ' ' + cand.key);
        continue;
      }
      let best = null, bestText = '';
      const docs = new Set(cands.map(function (c) { return c.doc_name; }));
      for (const doc of docs) { const t = mergedOf(doc + '|' + cand.key); if (t.length > bestText.length) { best = doc; bestText = t; } }
      const r = quoteOverlap(claim, bestText);
      if (r > chosenRatio) { chosen = cand; chosenRatio = r; chosenDoc = best; chosenText = bestText; chosenLaw = lawDoc; }
    }
    if (!chosen) return { status: 'missing', reason: misses.map(function (s) { return s.trim(); }).join('·') + ' 원문 없음', lawDoc: null };
    // 항·호는 원문에 그 구조가 있을 때만 검사 (단항 조문에 "제1항"이라고 쓴 것까지 잡지 않는다)
    const paras = chosen.paras || [], items = chosen.items || [];
    if (paras.length && /[①-⑳]/.test(chosenText)) {
      for (const n of paras) {
        if (n >= 1 && n <= 20 && chosenText.indexOf(CIRCLED[n - 1]) === -1)
          return { status: 'missing', reason: chosen.key + ' 제' + n + '항 원문 없음(조문 일부만 검색됨)', lawDoc: chosenLaw, doc: chosenDoc, key: chosen.key };
      }
    }
    if (items.length && /(^|\n)\s*\d+(의\d+)?\.\s/.test(chosenText)) {
      for (const it of items) {
        if (!new RegExp('(^|\\n)\\s*' + it + '\\.\\s').test(chosenText))
          return { status: 'missing', reason: chosen.key + ' 제' + it + '호 원문 없음(조문 일부만 검색됨)', lawDoc: chosenLaw, doc: chosenDoc, key: chosen.key };
      }
    } else if (items.length) {
      // 호를 주장했는데 원문에 호 구조가 없다 — 청크 경계에서 줄바꿈이 사라지면
      // ('…으로 한다.1. 가입자선로운영비용…') 위 정규식이 불발해 호 검사가 통째로 생략됐다(실측 12.4%).
      // 검사를 못 한 것이지 맞다는 뜻이 아니므로 초록을 주지 않는다. (#169-보론5)
      return { status: 'nocheck', reason: chosen.key + ' 제' + items.join('·') + '호 구조를 원문에서 찾지 못해 대조 불가',
               lawDoc: chosenLaw, doc: chosenDoc, key: chosen.key, paras: paras, items: items };
    }
    // 인용문에 내용이 없으면(제목·번호뿐) 판정할 것이 없다 — 표시를 그대로 둔다
    if ((headingOnly ? normQ(cite.after || '') : beforeBody).length < 24)
      // 번호·제목만 적고 내용을 옮기지 않았다 — 대조할 주장이 없으므로 '확인됨'이 될 수 없다.
      // (프롬프트에서도 이런 인용을 금지한다 — system_prompt [핵심 원칙] 1)
      return { status: 'noclaim', kind: 'article', lawDoc: chosenLaw, doc: chosenDoc, key: chosen.key, paras: paras, items: items, text: chosenText, overlap: chosenRatio, claim: claim, reason: '조문 번호·제목만 적혀 대조할 내용이 없음' };
    return { status: 'ok', kind: 'article', lawDoc: chosenLaw, doc: chosenDoc, key: chosen.key, paras: paras, items: items, text: chosenText, overlap: chosenRatio, claim: claim };
  }

  // 3) Haiku 판정 — 원문이 있었던 인용만. callHaiku(system, user) → Promise<string(JSON 배열 텍스트)>
  const JUDGE_SYSTEM =
    '당신은 법령 인용 검증자입니다. 각 항목의 "인용문"(AI 답변의 한 대목)이 "원문"(법령·고시 조문)의 내용을 사실과 다르게 옮겼는지만 판정합니다.\n' +
    '불일치로 보는 경우: 조문 번호·항·호가 원문과 다르다 / 의무의 주체·상대방이 바뀌었다 / 요건·효과·기한·수치·예외가 원문과 다르다 / 원문에 없는 내용을 원문의 규정처럼 서술했다.\n' +
    '불일치가 아닌 경우: 요약·생략·표현 차이 / 원문에 근거한 해석·의견 / 다른 조문을 함께 언급 / 인용문이 원문의 일부만 다룸 / 인용문이 조문 번호·제목만 적고 내용을 옮기지 않음(→ "판단불가").\n' +
    '확신이 없으면 "판단불가". 출력은 JSON 배열만, 설명 금지: [{"id":1,"verdict":"일치|불일치|판단불가","reason":"30자 이내"}]';

  async function judgeCitations(items, callHaiku) {
    if (!items.length || typeof callHaiku !== 'function') return {};
    const user = items.map(function (it) {
      return '### 항목 ' + it.id + '\n[인용 대상] ' + it.target + '\n[인용문]\n' + it.claim + '\n[원문]\n' + it.source;
    }).join('\n\n');
    const raw = await callHaiku(JUDGE_SYSTEM, user);
    const s = String(raw || '');
    const i = s.indexOf('['), j = s.lastIndexOf(']');
    if (i === -1 || j <= i) throw new Error('판정 JSON 없음');
    const arr = JSON.parse(s.slice(i, j + 1));
    const out = {};
    for (const v of arr) if (v && v.id != null) out[String(v.id)] = { verdict: String(v.verdict || ''), reason: String(v.reason || '').slice(0, 120) };
    return out;
  }

  // 표시 없는 통째 인용에 표시를 붙인다(#155-보론7, 11:39 답변 — 모델이 조문을 그대로 옮기고도 표시를 하나도 안 붙였다).
  // 원문과 60% 이상 그대로 겹치는 문단은 기계가 증명할 수 있으므로 「[원문 확인됨: 법령명 제N조]」를 문단 끝에 붙인다.
  // 제목(#)·표(|)·이미 표시가 있는 문단·짧은 문단은 건너뛴다. 항·호는 적지 않는다(어느 항인지 단정하지 않기 위해).
  // 바로 옆 문단에 **모델이 직접 쓴** 표시가 있으면 그 조문을 신뢰한다.
  //   실측(#169-보론4): 모델은 "…수리하여야 한다" 다음 문단에 '[원문 확인됨: 동법 제9조제5항]'을
  //   써 뒀는데, 기계는 같은 문단에 '제5조의2'를 붙였다. 둘이 어긋나면 어느 쪽이 맞는지 모르므로
  //   기계가 덧붙이지 않는다(모델 표시는 뒤이어 정상 검증 경로를 탄다).
  //   인용 **본문 안**의 조문 번호는 보지 않는다 — 법령 문장은 다른 조문을 흔히 인용한다
  //   (예: 전기통신사업법 제50조② 본문에 '제52조제1항과 제53조'가 나온다).
  function neighborTagKeys(parts, i) {
    const keys = [];
    const re = /\[원문\s*확인됨[^\]]*?제\s*(\d+조(?:의\d+)?)/g;
    for (const j of [i - 2, i + 2]) {
      const seg = String(parts[j] || '');
      let m;
      while ((m = re.exec(seg)) !== null) if (keys.indexOf(m[1]) < 0) keys.push(m[1]);
    }
    return keys;
  }

  function autoTagVerbatim(answer, chunks) {
    const text = String(answer || '');
    const arts = new Map();
    for (const c of chunks || []) {
      const k = articleKey(c && c.article_no);
      if (!k || !c.doc_name) continue;
      const gk = c.doc_name + '|' + k;
      if (!arts.has(gk)) arts.set(gk, []);
      arts.get(gk).push(c);
    }
    if (!arts.size) return { answer: text, added: 0 };
    const merged = new Map();
    for (const [gk, list] of arts) {
      list.sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
      merged.set(gk, mergeChunkTexts(list.map(function (c) { return c.content || ''; })));
    }
    let added = 0;
    const parts = text.split(/(\n[ \t]*\n)/);   // 문단과 구분자를 번갈아 보존
    for (let i = 0; i < parts.length; i += 2) {
      const p = parts[i];
      const body = p.replace(/^\s*[-*>]\s+/, '');
      if (!p.trim() || /^\s*#/.test(p) || /^\s*\|/.test(p)) continue;
      if (/\[(원문\s*확인됨|⚠️ 원문|학습 데이터 기반|근거 조문 미확인)[^\]]*\]/.test(p)) continue;
      if (normQ(body).length < 40) continue;
      let best = null, bestR = 0, secondR = 0;
      for (const [gk, t] of merged) {
        const r = quoteOverlap(body, t);
        if (r > bestR) { secondR = bestR; bestR = r; best = gk; }
        else if (r > secondR) { secondR = r; }
      }
      if (!best || bestR < VERBATIM_MIN) continue;
      // ① 2등과 겨우 차이 나면 단정하지 않는다(같은 문언이 두 조문에 있는 경우)
      if (bestR - secondR < AMBIG_MARGIN) continue;
      const doc = best.slice(0, best.lastIndexOf('|')), key = best.slice(best.lastIndexOf('|') + 1);
      // ② 옆 문단에 모델이 쓴 표시가 있고 그 조문과 다르면 붙이지 않는다
      const nb = neighborTagKeys(parts, i);
      if (nb.length && nb.indexOf(key) < 0) continue;
      const tag = ' [원문 확인됨: ' + docFamily(doc) + ' 제' + key + ']';
      // 문단 끝의 굵게(**) 닫힘 안쪽에 넣지 않는다 — 끝 공백만 떼고 뒤에 붙인다
      parts[i] = p.replace(/\s+$/, '') + tag;
      added++;
    }
    return { answer: parts.join(''), added: added };
  }

  // 표시 없는 인용 대조(#230, 2026-09-26 운영자 결정 — 판정 기준은 그대로): 모델이 조문을 인용 문단이나 따옴표로 옮기고도
  // 표시를 붙이지 않으면 검증기가 보지 않았다. 96760b6b 답변은 「전기통신사업법 제2조는 / (인용 문단) / 으로 정의합니다」 꼴의
  // 무표시 인용 4개 중 2개가 원문과 달랐다(장려금 정의에서 '판매에 관하여'·'모든' 누락, 제50조①5의2와 ②를 섞은 합성문).
  // 조문 번호가 인용 바로 앞에 있는 것만 골라 보이지 않는 표지(QUOTE_MARK)가 든 표시를 붙이고, 모델 표시와 같은 경로
  // (원문 그대로 → 확인됨 / 아니면 Haiku 판정)로 보낸다. 끝에서 확인됨은 표시를 남기고(기계가 대조했으므로), 다름·원문 없음·대조 못 함은
  // 세 상태 표시로 바꾸고, 대조할 것이 없으면(번호 못 읽음·내용 없음·중복) 표시를 지운다 — 경고로 만들지 않는다(#155 unparsed 원칙).
  // 판정 기준에 '인용 형태면 생략도 불일치' 줄을 더하는 안은 기각: 시험에서 멀쩡한 요약 인용(제52조① 조치 나열을 '등'으로 줄임)까지
  // 불일치로 잡았다. 현행 기준으로는 장려금·제50조 2건 불일치, 제52조 일치.
  const QUOTE_MARK = '⁠';   // 단어 결합자(보이지 않음) — 기계가 붙인 표시 식별용, 결과 답변에는 남기지 않는다
  const ART_REF_RE = /제\s?\d+\s?조(?:\s?의\s?\d+)?(?:\s?제\s?\d+\s?항)?(?:\s?제\s?\d+\s?호(?:\s?의\s?\d+)?)?/g;
  const INTRO_TOPIC_RE = /(?:은|는|에서|에는|에\s?따르면|에\s?의하면)\s*[:：]?\s*$/;
  const INTRO_ASFOLLOWS_RE = /(?:다음과|아래와)\s?같이\s?(?:규정|정의|명시|정하)[가-힣\s]{0,12}[.:：]\s*$/;
  const CONT_RE = /^\s*(?:고|라고|이라고|로|으로|를|을|이라는|라는|와|과)(?=[\s,.]|$)/;
  // 인용 앞 문장의 마지막 조문 참조 → 표시 안에 적을 대상(법령명은 앞 낱말이 법령명일 때만, '동법'이면 이어받기)
  function introCiteLabel(intro, maxTail) {
    const s = String(intro || '').replace(/\*\*/g, '');
    let m, last = null;
    ART_REF_RE.lastIndex = 0;
    while ((m = ART_REF_RE.exec(s)) !== null) last = m;
    if (!last || s.length - (last.index + last[0].length) > maxTail) return null;
    const info = lawNameBefore(s.slice(0, last.index));
    const law = info && info.inherit ? (info.level === '시행령' ? '동령' : '동법')
      : info && info.subord ? info.subord : (info && info.candidates ? info.text : '');
    return (law ? law + ' ' : '') + last[0].replace(/\s+/g, '');
  }
  function tagUntaggedQuotes(answer) {
    const text = String(answer || '');
    const parts = text.split(/(\n[ \t]*\n)/);   // 문단과 구분자를 번갈아 보존
    const hasTag = function (p) { return /\[(원문\s*확인됨|원문 없음|원문과 다름|⚠️ 원문|학습 데이터 기반|근거 조문 미확인)[^\]]*\]/.test(p); };
    const skip = function (p) { return !p.trim() || /^\s*#/.test(p) || /^\s*\|/.test(p) || hasTag(p); };
    let added = 0;
    for (let i = 0; i < parts.length; i += 2) {
      const p = parts[i];
      if (skip(p)) continue;
      // ① 인용 문단: 앞 문단이 「…제N조제M항은」·「…제N조는 다음과 같이 규정합니다.」로 끝나는 따로 선 문단
      const prev = i >= 2 ? parts[i - 2] : '';
      const next = i + 2 < parts.length ? parts[i + 2] : '';
      if (stripCiteBody(p).length >= 24 && prev && !hasTag(prev)) {
        const pv = prev.replace(/\*\*/g, '').replace(/\s+$/, '');
        let label = null;
        if (INTRO_TOPIC_RE.test(pv) && CONT_RE.test(next)) label = introCiteLabel(pv.replace(INTRO_TOPIC_RE, ''), 12);
        else if (INTRO_ASFOLLOWS_RE.test(pv)) label = introCiteLabel(pv.replace(INTRO_ASFOLLOWS_RE, ''), 40);
        if (label) {
          parts[i] = p.replace(/\s+$/, '') + ' [원문 확인됨: ' + label + QUOTE_MARK + ']';
          added++;
          continue;
        }
      }
      // ② 문장 안 따옴표 인용: 「제N조제M항은 "…(25자 이상)…"고 규정」 — 닫는 따옴표 바로 뒤에 붙인다
      parts[i] = p.replace(/(제\s?\d+\s?조[^"“”\n]{0,24}?(?:은|는|에서|에는|에\s?따르면)\s*)(["“])([^"”\n]{25,}?)(["”])(?=\s*(?:고|라고|이라고|로|으로|를|을|이라는|라는)(?:[\s,.]|$))/g,
        function (all, intro, q1, body, q2, off) {
          const label = introCiteLabel(p.slice(0, off) + intro, 12);
          if (!label) return all;
          added++;
          return intro + q1 + body + q2 + ' [원문 확인됨: ' + label + QUOTE_MARK + ']';
        });
    }
    return { answer: parts.join(''), added: added };
  }

  // 종합: 답변 → 표시 검증·교체
  //   { answer, chunks, annexSources, systemPrompt, callHaiku, maxJudge, autoTag, quoteTag }
  //   → { answer, verdicts: [{tag, kind, key, law, status, reason, judge, auto}], changed, autoTagged, quoteTagged, citedDocs }
  async function verifyCitations(args) {
    const chunks = ((args && args.chunks) || []).concat(args && args.systemPrompt ? pseudoChunksFromPrompt(args.systemPrompt) : []);
    // 표시 없는 통째 인용에 먼저 표시를 붙인다(autoTag=false로 끌 수 있음) — 그 뒤 검증은 모델이 붙인 표시와 같은 경로
    const at = (args && args.autoTag === false) ? { answer: String((args && args.answer) || ''), added: 0 } : autoTagVerbatim((args && args.answer) || '', chunks);
    // 그다음 표시 없는 인용 문단·따옴표 인용에 대조용 표시(#230, quoteTag=false로 끌 수 있음)
    const qt = (args && args.quoteTag === false) ? { answer: at.answer, added: 0 } : tagUntaggedQuotes(at.answer);
    const answer = qt.answer;
    const cites = findCitations(answer);
    if (!cites.length) return { answer: answer, verdicts: [], changed: 0, autoTagged: at.added, quoteTagged: 0, citedDocs: [] };
    const results = cites.map(function (c) {
      const auto = String(c.tag).indexOf(QUOTE_MARK) !== -1;
      // 직전 인용 문단에 같은 조의 표시가 이미 있는 토막 표시는 중복 — 판정하지 않고 지운다(#176)
      if (c.dupOfPrev) return Object.assign({}, c, { status: 'dup', reason: '직전 인용 문단의 표시와 중복', key: c.tagTarget.key, auto: auto });
      return Object.assign({}, c, checkCitation(c, chunks, (args && args.annexSources) || []), { auto: auto });
    });
    // 8 → 24 (#169-보론5). 실측 답변 하나에 표시가 22개였는데 9번째부터 판정 없이 초록이었다.
    // 판정은 여러 인용을 한 콜에 묶어 보내므로 상한을 올려도 호출 수는 늘지 않는다.
    const maxJudge = args && args.maxJudge != null ? args.maxJudge : 24;
    // 원문 그대로 인용(verbatim, 겹침 0.85↑)은 판정할 것이 없다 — Haiku에 보내지 않는다.
    const judgeable = results.filter(function (r) { return r.status === 'ok' && r.text && !r.verbatim; });
    const toJudge = judgeable.slice(0, maxJudge);
    // 상한을 넘긴 것·판정기가 없는 것은 '대조 못 함'으로 남긴다 — 조용히 초록으로 두지 않는다.
    judgeable.slice(maxJudge).forEach(function (r) { r.status = 'unjudged'; r.reason = '문구 판정 상한(' + maxJudge + '건) 초과'; });
    if (toJudge.length && !(args && typeof args.callHaiku === 'function'))
      toJudge.forEach(function (r) { r.status = 'unjudged'; r.reason = '판정기 미가동'; });
    if (toJudge.length && args && typeof args.callHaiku === 'function') {
      try {
        const items = toJudge.map(function (r, i) {
          const claim = String(r.claim || r.segment || '').replace(/\*\*/g, '').replace(/\s+/g, ' ').trim();
          return {
            id: i + 1,
            target: (r.lawDoc || r.lawText || '') + ' ' + r.key + (r.paras.length ? ' 제' + r.paras.join('·') + '항' : '') + (r.items.length ? ' 제' + r.items.join('·') + '호' : ''),
            claim: claim.length > 900 ? '…' + claim.slice(-900) : claim,
            source: r.text.length > 4000 ? r.text.slice(0, 4000) + '\n…(이하 생략)' : r.text,
          };
        });
        const verdicts = await judgeCitations(items, args.callHaiku);
        toJudge.forEach(function (r, i) {
          const v = verdicts[String(i + 1)];
          if (!v) { r.status = 'unjudged'; r.reason = '판정 결과 없음'; return; }
          r.judge = v;
          if (v.verdict === '불일치') { r.status = 'mismatch'; r.reason = v.reason; }
          else if (v.verdict !== '일치') r.status = 'unclear';
        });
      } catch (e) {
        // 종전에는 judgeError 만 남기고 status 를 ok 로 두어, 판정기가 죽어도 전건이 초록이었다.
        toJudge.forEach(function (r) {
          if (r.status === 'ok') { r.status = 'unjudged'; r.reason = '판정 호출 실패'; }
          r.judgeError = String(e && e.message || e);
        });
      }
    }
    let out = answer, changed = 0, quoteTagged = 0;
    const cut = function (r) {   // 표시를 지운다(앞 공백 하나 포함)
      const lead = /\s$/.test(out.slice(0, r.tagStart)) ? r.tagStart - 1 : r.tagStart;
      out = out.slice(0, lead) + out.slice(r.tagEnd);
    };
    for (const r of results.slice().reverse()) {
      // 꼬리표에 대상이 적혀 있었으면 바꾼 표시에도 남긴다 — 어느 조문 얘기인지 읽는 사람이 알 수 있게
      const tgt = r.tagTarget ? String(r.tag).replace(QUOTE_MARK, '').slice(1, -1).replace(/^원문\s*확인됨/, '').replace(/^[\s:：—\-–,]+/, '').trim() : '';
      if (r.auto) {
        // 기계가 붙인 인용 대조 표시(#230): 대조할 것이 없던 것은 흔적 없이 지우고, 확인된 것은 법령명을 채워 남긴다
        if (r.status === 'dup' || r.status === 'unparsed' || r.status === 'noclaim') { cut(r); continue; }
        quoteTagged++;
        if (r.status === 'ok') {
          const law = r.lawDoc || (r.doc ? docFamily(r.doc) : '');
          const named = /(법|법률|령|규칙|고시|규정|기준|세칙|지침)\s/.test(tgt + ' ') && !/^동법\s/.test(tgt);
          const label = law && !named ? law + ' ' + tgt.replace(/^동법\s*/, '') : tgt;
          out = out.slice(0, r.tagStart) + '[원문 확인됨: ' + label + ']' + out.slice(r.tagEnd);
          continue;
        }
        out = out.slice(0, r.tagStart) + buildTag(r.status, r.reason, tgt) + out.slice(r.tagEnd); changed++;
        continue;
      }
      // ok(= 실제로 대조해 맞음)는 그대로. 나머지는 세 상태 표시(#176)로 바꾸고, 중복(dup)은 지운다.
      if (r.status === 'ok') continue;
      if (r.status === 'dup') { cut(r); changed++; continue; }
      out = out.slice(0, r.tagStart) + buildTag(r.status, r.reason, tgt) + out.slice(r.tagEnd); changed++;
    }
    // 답변이 실제로 인용해 확인된 문서 — 출처 목록을 이 순서로 앞세우는 데 쓴다(#176)
    const citedDocs = [];
    for (const r of results) if (r.status === 'ok' && r.doc && citedDocs.indexOf(r.doc) === -1) citedDocs.push(r.doc);
    // 지운 기계 표시는 기록에서도 뺀다(판정 대상이 아니었다)
    const kept = results.filter(function (r) { return !(r.auto && (r.status === 'dup' || r.status === 'unparsed' || r.status === 'noclaim')); });
    return {
      answer: out, changed: changed, autoTagged: at.added, quoteTagged: quoteTagged, citedDocs: citedDocs,
      verdicts: kept.map(function (r) {
        const v = { tag: String(r.tag).replace(QUOTE_MARK, ''), kind: r.kind, key: r.key || (r.annex ? (r.annexType || '별표') + ' ' + r.annex : null), law: r.lawDoc || r.lawText || null,
          paras: r.paras || [], items: r.items || [], status: r.status, reason: r.reason || null, judge: r.judge || null, doc: r.doc || null,
          verbatim: !!r.verbatim, overlap: typeof r.overlap === 'number' ? Math.round(r.overlap * 100) / 100 : null };
        if (r.auto) v.auto = 'quote';
        return v;
      }),
    };
  }

  const CiteVerify = {
    TAG_UNVERIFIED: TAG_UNVERIFIED, TAG_MISSING: TAG_MISSING, TAG_MISMATCH: TAG_MISMATCH, TAG_UNCHECKED: TAG_UNCHECKED, buildTag: buildTag,
    articleKey: articleKey, docFamily: docFamily, mergeChunkTexts: mergeChunkTexts,
    expandArticles: expandArticles, pseudoChunksFromPrompt: pseudoChunksFromPrompt,
    buildCitingExcerpts: buildCitingExcerpts, citeRegex: citeRegex, excerptAround: excerptAround,
    isOtherLawRef: isOtherLawRef, isSanctionTitle: isSanctionTitle, selfCiteIndexes: selfCiteIndexes, sanctionExcerpt: sanctionExcerpt,
    tagUntaggedQuotes: tagUntaggedQuotes, introCiteLabel: introCiteLabel, QUOTE_MARK: QUOTE_MARK,
    lawNameBefore: lawNameBefore, familyMatches: familyMatches, resolveLaw: resolveLaw, lawScope: lawScope, quoteOverlap: quoteOverlap,
    parseSegment: parseSegment, findCitations: findCitations, checkCitation: checkCitation,
    judgeCitations: judgeCitations, verifyCitations: verifyCitations, autoTagVerbatim: autoTagVerbatim,
  };
  root.CiteVerify = CiteVerify;
  if (typeof module !== 'undefined' && module.exports) module.exports = CiteVerify;
})(typeof globalThis !== 'undefined' ? globalThis : this);
