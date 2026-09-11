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

  // 표시 하나의 앞 문단에서 인용 대상을 읽는다
  function parseSegment(segment) {
    const s = String(segment || '').replace(/\*\*/g, '');
    const artRe = /제\s?(\d+)\s?조(?:\s?의\s?(\d+))?/g;
    const mentions = [];
    let a;
    while ((a = artRe.exec(s))) mentions.push({ idx: a.index, end: a.index + a[0].length, key: a[1] + '조' + (a[2] ? '의' + a[2] : '') });
    if (!mentions.length) {
      const bm = s.match(/별표\s*제?\s*(\d+(?:의\d+)?)/);
      return bm ? { kind: 'annex', annex: bm[1] } : { kind: 'none' };
    }
    const primary = mentions[0];
    const paras = [], items = [];
    for (let i = 0; i < mentions.length; i++) {
      if (mentions[i].key !== primary.key) continue;
      const stop = i + 1 < mentions.length ? mentions[i + 1].idx : s.length;
      const tail = s.slice(mentions[i].end, stop);
      let pm;
      const pRe = /제\s?(\d+)\s?항/g;
      while ((pm = pRe.exec(tail))) if (paras.indexOf(+pm[1]) === -1) paras.push(+pm[1]);
      // 원문자 항 표기(제5조①)는 조 바로 뒤에 붙은 것만 — 답변 본문의 ①②③ 나열과 섞이지 않게
      const cm = tail.match(/^\s*(?:\([^)]*\))?\s*([①-⑳])/);
      if (cm) { const n = CIRCLED.indexOf(cm[1]) + 1; if (paras.indexOf(n) === -1) paras.push(n); }
      const iRe = /(?:제\s?)?(\d+)\s?호(?:\s?의\s?(\d+))?/g;
      while ((pm = iRe.exec(tail))) { const it = pm[1] + (pm[2] ? '의' + pm[2] : ''); if (items.indexOf(it) === -1) items.push(it); }
    }
    return { kind: 'article', key: primary.key, paras: paras, items: items, lawInfo: lawNameBefore(s.slice(0, primary.idx)) };
  }

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
      const c = Object.assign({ tagStart: tagStart, tagEnd: tagEnd, tag: m[0], segment: text.slice(segStart, tagStart) }, parsed);
      if (c.kind === 'article') {
        if (c.lawInfo && c.lawInfo.inherit) c.lawInherit = lastLaw;
        else if (c.lawInfo && c.lawInfo.candidates) c.lawText = c.lawInfo.text;
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
    let lawDoc = null;
    if (cite.lawInfo && cite.lawInfo.candidates) lawDoc = resolveLaw(cite.lawInfo, families);
    else if (cite.lawInherit) lawDoc = resolveLaw(cite.lawInherit, families);
    let cands = (chunks || []).filter(function (c) { return articleKey(c.article_no) === cite.key; });
    if (!cands.length) return { status: 'missing', reason: (lawDoc || cite.lawText || '') + ' ' + cite.key + ' 원문 없음', lawDoc: lawDoc };
    if (lawDoc) {
      const same = cands.filter(function (c) { return docFamily(c.doc_name) === lawDoc; });
      if (!same.length) return { status: 'missing', reason: lawDoc + ' ' + cite.key + ' 원문 없음(같은 조가 다른 문서에만 있음)', lawDoc: lawDoc };
      cands = same;
    }
    // 문서별로 묶어 가장 긴 것을 정본으로 (같은 조가 현행·시행예정 두 판으로 있을 수 있다)
    const byDoc = new Map();
    for (const c of cands) { if (!byDoc.has(c.doc_name)) byDoc.set(c.doc_name, []); byDoc.get(c.doc_name).push(c); }
    let best = null, bestText = '';
    for (const [doc, list] of byDoc) {
      list.sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
      const t = mergeChunkTexts(list.map(function (c) { return c.content || ''; }));
      if (t.length > bestText.length) { best = doc; bestText = t; }
    }
    // 항·호는 원문에 그 구조가 있을 때만 검사 (단항 조문에 "제1항"이라고 쓴 것까지 잡지 않는다)
    if (cite.paras && cite.paras.length && /[①-⑳]/.test(bestText)) {
      for (const n of cite.paras) {
        if (n >= 1 && n <= 20 && bestText.indexOf(CIRCLED[n - 1]) === -1)
          return { status: 'missing', reason: cite.key + ' 제' + n + '항 원문 없음(조문 일부만 검색됨)', lawDoc: lawDoc, doc: best };
      }
    }
    if (cite.items && cite.items.length && /(^|\n)\s*\d+(의\d+)?\.\s/.test(bestText)) {
      for (const it of cite.items) {
        if (!new RegExp('(^|\\n)\\s*' + it + '\\.\\s').test(bestText))
          return { status: 'missing', reason: cite.key + ' 제' + it + '호 원문 없음(조문 일부만 검색됨)', lawDoc: lawDoc, doc: best };
      }
    }
    return { status: 'ok', kind: 'article', lawDoc: lawDoc, doc: best, text: bestText };
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
    const toJudge = results.filter(function (r) { return r.status === 'ok' && r.text; }).slice(0, maxJudge);
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
          paras: r.paras || [], items: r.items || [], status: r.status, reason: r.reason || null, judge: r.judge || null, doc: r.doc || null };
      }),
    };
  }

  const CiteVerify = {
    TAG_MISSING: TAG_MISSING, TAG_MISMATCH: TAG_MISMATCH,
    articleKey: articleKey, docFamily: docFamily, mergeChunkTexts: mergeChunkTexts,
    expandArticles: expandArticles, pseudoChunksFromPrompt: pseudoChunksFromPrompt,
    lawNameBefore: lawNameBefore, familyMatches: familyMatches, resolveLaw: resolveLaw,
    parseSegment: parseSegment, findCitations: findCitations, checkCitation: checkCitation,
    judgeCitations: judgeCitations, verifyCitations: verifyCitations,
  };
  root.CiteVerify = CiteVerify;
  if (typeof module !== 'undefined' && module.exports) module.exports = CiteVerify;
})(typeof globalThis !== 'undefined' ? globalThis : this);
