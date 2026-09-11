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
//  한 파일을 세 곳이 그대로 쓴다 — Deno Edge(rag.ts, verify-citations), 브라우저(index.html <script>),
//  node 테스트(tests/cite_verify.test.js). 그래서 TS 문법·export 없이 globalThis.CiteVerify 에 붙인다.
//  GitLab Pages는 나열된 파일만 싣는다 — .gitlab-ci.yml의 cp 목록에 이 경로가 있어야 한다.
//  DB·API 호출은 전부 호출측이 콜백(fetchArticle, callHaiku)으로 넘긴다 — 이 파일은 순수 로직만.
// ============================================================================
(function (root) {
  'use strict';

  const TAG_RE = /\[원문\s*확인됨[^\]]*\]/g;
  const CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';
  const TAG_MISSING = '[⚠️ 원문 미확인 — 검색 결과에 해당 조문 없음]';
  const TAG_MISMATCH = '[⚠️ 원문과 다르게 설명됨 — 확인 필요]';
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
    for (const gk of order) {
      if (full.size >= maxArticles || budget <= 0) break;
      const g = groups.get(gk);
      let rows = [];
      try { rows = (await fetchArticle(g.doc, g.key)) || []; } catch (e) { rows = []; }
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
  //   반환 { text: 프롬프트 블록, chunks: 검증용 의사 청크(_excerpt=true), ids: 발췌 원본 조각 id }
  function citeRegex(key) {
    // '32조의4'는 '제32조의40'과, '32조'는 '제32조의4'와 구분한다
    const esc = key.replace(/조의(\d+)$/, '조의$1').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp('제' + esc + (/조의\d+$/.test(key) ? '(?!\\d)' : '(?!의\\d)(?!\\d)'));
  }
  function excerptAround(content, re, maxLen) {
    const s = String(content || '');
    const m = s.match(re);
    if (!m) return '';
    const at = m.index;
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
  async function buildCitingExcerpts(chunks, fetchCiting, opts) {
    opts = opts || {};
    const maxPer = opts.maxPerArticle != null ? opts.maxPerArticle : 4;
    const maxTotal = opts.maxTotal != null ? opts.maxTotal : 8;
    const maxLen = opts.maxLen != null ? opts.maxLen : 300;
    const have = new Set();          // 이미 컨텍스트에 있는 doc|key — 발췌 불필요
    const targets = [];
    for (const c of chunks || []) {
      const k = articleKey(c && c.article_no);
      if (!k || !c.doc_name) continue;
      const gk = c.doc_name + '|' + k;
      if (!have.has(gk)) { have.add(gk); targets.push({ doc: c.doc_name, key: k }); }
    }
    const out = [], ids = [], seen = new Set();
    for (const t of targets) {
      if (out.length >= maxTotal) break;
      let rows = [];
      try { rows = (await fetchCiting(t.doc, t.key)) || []; } catch (e) { rows = []; }
      const re = citeRegex(t.key);
      let n = 0;
      rows.sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
      for (const r of rows) {
        if (n >= maxPer || out.length >= maxTotal) break;
        const rk = articleKey(r.article_no);
        if (!rk || rk === t.key) continue;                                   // 자기 자신
        if (/^(부칙|별표|서식|별지|붙임)/.test(String(r.article_no || ''))) continue;
        const gk = r.doc_name + '|' + rk;
        if (have.has(gk) || seen.has(gk)) continue;                          // 이미 실린 조문·중복
        const ex = excerptAround(r.content, re, maxLen);
        if (!ex) continue;
        seen.add(gk); n++;
        out.push({ doc_name: r.doc_name, article_no: r.article_no, cites: t.key, excerpt: ex });
        if (typeof r.id === 'number') ids.push(r.id);
      }
    }
    if (!out.length) return { text: '', chunks: [], ids: [] };
    const text = '\n\n---\n\n[검색된 조문을 인용하는 다른 조문 — 발췌]\n' +
      '아래는 위 조문을 가리키는 같은 법령의 다른 조문(제재·조사·준용 등)에서 **인용 문장만** 잘라 온 것입니다. 전문이 아니므로 ' +
      '이 발췌에 없는 항·호의 내용을 추정하지 마세요. 인용할 때는 「법령명 제N조」와 발췌에 보이는 항·호까지만 적으세요.\n\n' +
      out.map(function (x, i) { return '[역참조 ' + (i + 1) + '] ' + x.doc_name + ' 제' + x.article_no + ' — 제' + x.cites + ' 인용\n' + x.excerpt; }).join('\n\n');
    const pseudo = out.map(function (x) { return { id: null, doc_name: x.doc_name, article_no: x.article_no, chunk_index: 0, content: x.excerpt, _excerpt: true }; });
    return { text: text, chunks: pseudo, ids: ids };
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
    let b = String(before || '').replace(/\s+$/, '');
    while (/\)$/.test(b)) { const i = b.lastIndexOf('('); if (i < 0) break; b = b.slice(0, i).replace(/\s+$/, ''); }
    const m = b.match(/([가-힣A-Za-z0-9·ㆍ‧\s]{1,80})$/);
    if (!m) return null;
    const words = m[1].trim().split(/\s+/).filter(Boolean);
    if (!words.length) return null;
    const last = words[words.length - 1];
    const nl = norm(last);
    if (/^(동법|같은법|이법|법|동령|같은영|이영|영|동규정|이규정|같은규정|이고시|동고시)$/.test(nl)) return { inherit: true };
    if (!LAW_SUFFIX_RE.test(last)) return null;
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
  // 후보 목록을 문서군(family 목록)과 맞춰 하나로 확정. 못 맞추면 null(=법령 미상, 어느 문서든 허용)
  function resolveLaw(nameInfo, families) {
    if (!nameInfo || !nameInfo.candidates) return null;
    for (const cand of nameInfo.candidates) {
      const hit = families.find(function (f) { return familyMatches(f, cand); });
      if (hit) return hit;
    }
    return null;
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
      const bm = s.match(/별표\s*제?\s*(\d+(?:의\d+)?)/);
      return bm ? { kind: 'annex', annex: bm[1] } : { kind: 'none' };
    }
    const byKey = new Map();
    const mentions = [];
    for (let i = 0; i < raw.length; i++) {
      const m = raw[i];
      let rec = byKey.get(m.key);
      if (!rec) { rec = { key: m.key, idx: m.idx, paras: [], items: [], lawInfo: lawNameBefore(s.slice(0, m.idx)) }; byKey.set(m.key, rec); mentions.push(rec); }
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
  const VERBATIM_MIN = 0.6;   // 이 이상 겹치면 "원문 그대로 인용" — 번호 파싱 없이 확인됨, Haiku 판정 생략

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
      const c = Object.assign({ tagStart: tagStart, tagEnd: tagEnd, tag: m[0], segment: text.slice(segStart, tagStart) }, parsed);
      if (c.kind === 'article') {
        if (c.lawInfo && c.lawInfo.inherit) c.lawInherit = lastLaw;
        else if (c.lawInfo && c.lawInfo.candidates) c.lawText = c.lawInfo.text;
        // 후보 = 인용문 안의 조 + 앞 줄에만 있는 조(뒤에 붙임 — 겹침이 같으면 인용문 안의 조가 우선)
        const inSeg = new Set(c.mentions.map(function (x) { return x.key; }));
        const ext = extStart < segStart ? parseSegment(text.slice(extStart, tagStart)) : null;
        c.candidates = c.mentions.slice();
        if (ext && ext.kind === 'article') {
          for (const x of ext.mentions) if (!inSeg.has(x.key)) c.candidates.push(Object.assign({}, x, { extOnly: true }));
        }
        for (const x of c.candidates) if (x.lawInfo && x.lawInfo.inherit) x.lawInherit = lastLaw;
      } else if (c.kind === 'none' && extStart < segStart) {
        // 인용문에 조 번호가 없어도 앞 줄에 있으면 그것이 대상 (「제11조는 다음과 같이 규정합니다.」 + 원문 줄)
        const ext = parseSegment(text.slice(extStart, tagStart));
        if (ext.kind === 'article') {
          Object.assign(c, ext, { kind: 'article' });
          c.candidates = ext.mentions.map(function (x) { return Object.assign({}, x, { extOnly: true }); });
          for (const x of c.candidates) if (x.lawInfo && x.lawInfo.inherit) x.lawInherit = lastLaw;
        }
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
    if (cite.kind === 'annex') {
      const want = norm('별표' + cite.annex);
      const ok = (annexSources || []).some(function (s) { return norm(s).indexOf(want) !== -1 && !new RegExp(want + '\\d').test(norm(s)); })
        || (chunks || []).some(function (c) { return norm(String(c.article_no || '').split('(')[0]) === want; });
      return ok ? { status: 'ok', kind: 'annex' } : { status: 'missing', reason: '별표 ' + cite.annex + ' 원문 없음' };
    }
    const families = [];
    for (const c of chunks || []) { const f = docFamily(c.doc_name); if (f && families.indexOf(f) === -1) families.push(f); }
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
    const claim = cite.segment || '';

    // ① 원문 그대로 인용이면 번호 파싱과 무관하게 확인됨 — 어느 조문(별표 포함)의 텍스트와 겹치는지 본다.
    //    (통째 인용 안의 교차참조가 엉뚱한 조를 가리켜 '미확인'이 되던 오판 방지, #155-보론3)
    let vbBest = null, vbRatio = 0;
    for (const gk of articleText.keys()) {
      const r = quoteOverlap(claim, mergedOf(gk));
      if (r > vbRatio) { vbRatio = r; vbBest = gk; }
    }
    if (vbBest && vbRatio >= VERBATIM_MIN) {
      const [doc, key] = [vbBest.slice(0, vbBest.lastIndexOf('|')), vbBest.slice(vbBest.lastIndexOf('|') + 1)];
      return { status: 'ok', kind: 'article', lawDoc: docFamily(doc), doc: doc, key: key, text: mergedOf(vbBest), verbatim: true, overlap: vbRatio, reason: '원문 그대로 인용(' + Math.round(vbRatio * 100) + '%)' };
    }

    // ② 후보 조문(인용문 안 → 앞 줄) 중 컨텍스트에 있는 것을 고른다 — 여럿이면 인용문과 가장 많이 겹치는 것, 같으면 앞의 것
    const candidates = (cite.candidates && cite.candidates.length) ? cite.candidates : [{ key: cite.key, paras: cite.paras || [], items: cite.items || [], lawInfo: cite.lawInfo, lawInherit: cite.lawInherit }];
    let chosen = null, chosenRatio = -1, chosenDoc = null, chosenText = '', chosenLaw = null;
    const misses = [];
    for (const cand of candidates) {
      let lawDoc = null;
      if (cand.lawInfo && cand.lawInfo.candidates) lawDoc = resolveLaw(cand.lawInfo, families);
      else if (cand.lawInherit) lawDoc = resolveLaw(cand.lawInherit, families);
      let cands = (chunks || []).filter(function (c) { return articleKey(c.article_no) === cand.key; });
      if (lawDoc) cands = cands.filter(function (c) { return docFamily(c.doc_name) === lawDoc; });
      if (!cands.length) { misses.push((lawDoc || (cand.lawInfo && cand.lawInfo.text) || '') + ' ' + cand.key); continue; }
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
    }
    return { status: 'ok', kind: 'article', lawDoc: chosenLaw, doc: chosenDoc, key: chosen.key, paras: paras, items: items, text: chosenText, overlap: chosenRatio };
  }

  // 3) Haiku 판정 — 원문이 있었던 인용만. callHaiku(system, user) → Promise<string(JSON 배열 텍스트)>
  const JUDGE_SYSTEM =
    '당신은 법령 인용 검증자입니다. 각 항목의 "인용문"(AI 답변의 한 대목)이 "원문"(법령·고시 조문)의 내용을 사실과 다르게 옮겼는지만 판정합니다.\n' +
    '불일치로 보는 경우: 조문 번호·항·호가 원문과 다르다 / 의무의 주체·상대방이 바뀌었다 / 요건·효과·기한·수치·예외가 원문과 다르다 / 원문에 없는 내용을 원문의 규정처럼 서술했다.\n' +
    '불일치가 아닌 경우: 요약·생략·표현 차이 / 원문에 근거한 해석·의견 / 다른 조문을 함께 언급 / 인용문이 원문의 일부만 다룸.\n' +
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

  // 종합: 답변 → 표시 검증·교체
  //   { answer, chunks, annexSources, systemPrompt, callHaiku, maxJudge }
  //   → { answer, verdicts: [{tag, kind, key, law, status, reason, judge}], changed }
  async function verifyCitations(args) {
    const answer = String((args && args.answer) || '');
    const chunks = ((args && args.chunks) || []).concat(args && args.systemPrompt ? pseudoChunksFromPrompt(args.systemPrompt) : []);
    const cites = findCitations(answer);
    if (!cites.length) return { answer: answer, verdicts: [], changed: 0 };
    const results = cites.map(function (c) { return Object.assign({}, c, checkCitation(c, chunks, (args && args.annexSources) || [])); });
    const maxJudge = args && args.maxJudge != null ? args.maxJudge : 8;
    // 원문 그대로 인용(verbatim)은 판정할 것이 없다 — Haiku에 보내지 않는다(비용·오판 방지)
    const toJudge = results.filter(function (r) { return r.status === 'ok' && r.text && !r.verbatim; }).slice(0, maxJudge);
    if (toJudge.length && args && typeof args.callHaiku === 'function') {
      try {
        const items = toJudge.map(function (r, i) {
          const claim = r.segment.replace(/\*\*/g, '').replace(/\s+/g, ' ').trim();
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
          if (!v) return;
          r.judge = v;
          if (v.verdict === '불일치') { r.status = 'mismatch'; r.reason = v.reason; }
          else if (v.verdict !== '일치') r.status = 'unclear';
        });
      } catch (e) {
        results.forEach(function (r) { if (r.status === 'ok' && r.text) r.judgeError = String(e && e.message || e); });
      }
    }
    let out = answer, changed = 0;
    for (const r of results.slice().reverse()) {
      let rep = null;
      if (r.status === 'missing') rep = TAG_MISSING;
      else if (r.status === 'mismatch') rep = TAG_MISMATCH;
      if (rep) { out = out.slice(0, r.tagStart) + rep + out.slice(r.tagEnd); changed++; }
    }
    return {
      answer: out, changed: changed,
      verdicts: results.map(function (r) {
        return { tag: r.tag, kind: r.kind, key: r.key || (r.annex ? '별표 ' + r.annex : null), law: r.lawDoc || r.lawText || null,
          paras: r.paras || [], items: r.items || [], status: r.status, reason: r.reason || null, judge: r.judge || null, doc: r.doc || null,
          verbatim: !!r.verbatim, overlap: typeof r.overlap === 'number' ? Math.round(r.overlap * 100) / 100 : null };
      }),
    };
  }

  const CiteVerify = {
    TAG_MISSING: TAG_MISSING, TAG_MISMATCH: TAG_MISMATCH,
    articleKey: articleKey, docFamily: docFamily, mergeChunkTexts: mergeChunkTexts,
    expandArticles: expandArticles, pseudoChunksFromPrompt: pseudoChunksFromPrompt,
    buildCitingExcerpts: buildCitingExcerpts, citeRegex: citeRegex, excerptAround: excerptAround,
    lawNameBefore: lawNameBefore, familyMatches: familyMatches, resolveLaw: resolveLaw, quoteOverlap: quoteOverlap,
    parseSegment: parseSegment, findCitations: findCitations, checkCitation: checkCitation,
    judgeCitations: judgeCitations, verifyCitations: verifyCitations,
  };
  root.CiteVerify = CiteVerify;
  if (typeof module !== 'undefined' && module.exports) module.exports = CiteVerify;
})(typeof globalThis !== 'undefined' ? globalThis : this);
