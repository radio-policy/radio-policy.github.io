// 자문 검색 회귀 하네스 — 대시보드(app.js) 경로 (#201, 2026-09-24 B-2)
//
// 실행: 로컬 프리뷰(http://127.0.0.1:8765/)에서 index.html을 연 뒤 브라우저 콘솔(또는 세션의 javascript_tool)에서
//   var s = document.createElement('script'); s.src = 'tests/rag_regress_browser.js?ts=' + Date.now(); document.head.appendChild(s);
//   await window.ragRegress.run({ tag: 'before' })   // → 스냅샷 객체(window.ragRegress.last). 파일로 남기려면 JSON.stringify 해서 저장.
//
// 무엇을 하나: tests/fixtures/rag_regression_set.json의 질문 20건마다 buildAdvisoryContext(userText)를 실제 Supabase로
// 돌리되, Haiku 확장(expandQueryKeywords)은 픽스처의 고정 확장어로, Voyage 임베딩(getQueryEmbedding)은
// tests/fixtures/rag_regress_embed_cache.json(Deno 하네스 첫 실행이 만든다)으로 바꿔 끼운다 → Anthropic API 0회, 로그인 불필요.
// 단계별 청크 id 목록(RAG 15·조문 정밀검색·통째 보강·역참조·별표·요약·뉴스)과 소요 시간을 기록해, 검색 흐름을 고친 뒤
// 같은 질문의 결과가 그대로인지(순서까지) 대조한다. 시맨틱 캐시가 비면 진짜 voyage-embed Edge를 부르고 캐시에 넣는다.
//
// 결정적 모드(기본 deterministic:true): document_chunks 조회 중 order 없이 limit만 건 것(키워드 ilike limit 4)에 하네스가
// order('id')를 붙인다. 운영 코드는 그대로 두고(그 정렬 없음은 B-5에서 다룬다) **코드 변경이 결과를 바꿨는지**만 보기 위한 장치 —
// 같은 코드로 두 번 돌려도 임의 4건이 달라져 20문항 중 10문항이 어긋나던 잡음(2026-09-24 실측)을 걷어낸다.
// trgm RPC의 동점(#185) 잡음은 클라이언트에서 못 걷어내므로 잔여 잡음은 '같은 코드 2회'로 잰다.
(function () {
  'use strict';
  var SET_URL = 'tests/fixtures/rag_regression_set.json';
  var CACHE_URL = 'tests/fixtures/rag_regress_embed_cache.json';
  var origExpand = window.expandQueryKeywords;
  var origEmbed = window.getQueryEmbedding;
  var origLog = console.log;
  var embedCache = null;      // { "<model>|<text>": number[] }
  var cacheMiss = [];
  var detInstalled = false;

  async function loadJson(url, optional) {
    try {
      var r = await fetch(url + '?ts=' + Date.now(), { cache: 'no-store' });
      if (!r.ok) { if (optional) return null; throw new Error(url + ' ' + r.status); }
      return await r.json();
    } catch (e) { if (optional) return null; throw e; }
  }

  // document_chunks 조회에서 order 없는 limit → order('id') (결정적 모드). select()가 돌려주는 빌더의 order/limit만 감싼다.
  // app.js의 `let sb`는 window 속성이 아니다(스크립트 전역 렉시컬 바인딩) — window.sb로 검사하면 늘 비어 있어 아무것도 안 깔린다(2026-09-24 실측)
  function haveSb() { try { return typeof sb !== 'undefined' && !!sb; } catch (e) { return false; } }
  function installDeterministic() {
    if (detInstalled || !haveSb()) return;
    var origFrom = sb.from.bind(sb);
    sb.from = function (table) {
      var qb = origFrom(table);
      if (table !== 'document_chunks') return qb;
      var origSelect = qb.select.bind(qb);
      qb.select = function () {
        var fb = origSelect.apply(null, arguments);
        var ordered = false;
        var oOrder = fb.order.bind(fb), oLimit = fb.limit.bind(fb);
        fb.order = function () { ordered = true; return oOrder.apply(null, arguments); };
        fb.limit = function (n, o) { if (!ordered) { ordered = true; oOrder('id', { ascending: true }); } return oLimit(n, o); };
        return fb;
      };
      return qb;
    };
    detInstalled = true;
  }

  // RPC 호출 기록(함수명·행수·오류코드·ms) — trgm이 statement_timeout(57014: anon 3초·authenticated 8초)으로 0건이 되는
  // fail-open 경로를 결과 차이의 원인으로 식별하기 위해. 이 하네스는 로그인 없이(anon) 돌므로 trgm은 항상 3초 한도에 걸린다(2026-09-24 실측).
  var rpcLog = [];
  var rpcInstalled = false;
  function installRpcLog() {
    if (rpcInstalled || !haveSb()) return;
    var origRpc = sb.rpc.bind(sb);
    sb.rpc = function (fn, params, o) {
      var t0 = performance.now();
      var b = origRpc(fn, params, o);
      var origThen = b.then.bind(b);
      b.then = function (onOk, onErr) {
        return origThen(function (r) {
          rpcLog.push({ fn: fn, ms: Math.round(performance.now() - t0), rows: Array.isArray(r && r.data) ? r.data.length : null, error: r && r.error ? (r.error.code || r.error.message) : null });
          return onOk ? onOk(r) : r;
        }, onErr);
      };
      return b;
    };
    rpcInstalled = true;
  }

  function ids(list) { return (list || []).map(function (c) { return c && c.id; }); }
  function pendingSummary() {
    var p = window.lastPendingNotice;
    return Array.isArray(p) ? p.map(function (x) { return (x.law_name || '') + '|' + (x.enf_date || ''); }) : p;
  }

  async function run(opts) {
    opts = opts || {};
    var deterministic = opts.deterministic !== false;
    if (deterministic) installDeterministic();
    installRpcLog();
    var set = await loadJson(SET_URL);
    embedCache = (await loadJson(CACHE_URL, true)) || {};
    cacheMiss = [];
    var expandMap = {};
    set.questions.forEach(function (q) { expandMap[q.question] = q.expanded.slice(); });

    // 확장어·임베딩 바꿔 끼우기 (전역 함수 선언은 window 속성이라 재할당된다)
    // expandDelayMs: Haiku 확장의 실제 지연(1~2초)을 흉내 낸다 — 확장 대기와 trgm·시맨틱을 겹치는 효과(B-2)는 이 지연이 있어야 보인다
    var expandDelay = opts.expandDelayMs || 0;
    window.expandQueryKeywords = function (query) {
      var e = expandMap[query];
      if (!e) throw new Error('픽스처에 없는 질문: ' + query);
      if (!expandDelay) return Promise.resolve(e.slice());
      return new Promise(function (res) { setTimeout(function () { res(e.slice()); }, expandDelay); });
    };
    window.getQueryEmbedding = async function (query, model) {
      var key = (model || 'voyage-4-lite') + '|' + query;
      if (embedCache[key]) return embedCache[key].slice();
      var emb = await origEmbed(query, model);
      if (emb) { embedCache[key] = emb; cacheMiss.push(key); }
      return emb;
    };
    // 검색 단계 로그(trgm N개·시맨틱 N개·문서별 채택 등)를 질문별로 붙잡아 둔다 — fail-open 경로가 0건으로 새는지 보기 위해
    var logLines = [];
    console.log = function () {
      var s = Array.prototype.map.call(arguments, function (a) { return typeof a === 'string' ? a : JSON.stringify(a); }).join(' ');
      if (/trgm 검색|시맨틱 검색|문서별 채택|3중 하이브리드|조문 정밀검색 보강|조문 통째 보강|역참조 발췌|보도자료 원본 검색/.test(s)) logLines.push(s.slice(0, 400));
      return origLog.apply(console, arguments);
    };
    var only = opts.only ? new Set(opts.only) : null;
    var out = { tag: opts.tag || '', at: new Date().toISOString(), href: location.href, deterministic: deterministic && detInstalled, rpcLogged: rpcInstalled, expandDelayMs: expandDelay, results: [] };
    try {
      for (var i = 0; i < set.questions.length; i++) {
        var q = set.questions[i];
        if (only && !only.has(q.id)) continue;
        logLines = []; rpcLog = [];
        var t0 = performance.now();
        var ctx, err = null;
        try { ctx = await buildAdvisoryContext(q.question); } catch (e) { err = String(e && e.message || e); ctx = {}; }
        var t1 = performance.now();
        out.results.push({
          id: q.id, ms: Math.round(t1 - t0), error: err,
          rag: ids(ctx.ragChunks), extra: ids(ctx.lawExtra), added: ctx.addedIds || [], citing: ctx.citingIds || [],
          annex: (window.lastAnnexSources || []).slice(), pending: pendingSummary(),
          kb: (ctx.kbRows || []).map(function (r) { return r.doc_id + ':' + r.chunk_idx; }),
          news: (window.lastNewsSources || []).slice(),
          lens: { rag: (ctx.ragContext || '').length, law: (ctx.lawArticleContext || '').length, citing: (ctx.citingContext || '').length,
                  annex: (ctx.annexContext || '').length, pending: (ctx.pendingContext || '').length, kb: (ctx.kbContext || '').length,
                  custom: (ctx.customContext || '').length, news: (ctx.newsContext || '').length, track: (ctx.lawTrackContext || '').length,
                  asm: (ctx.assemblyContext || '').length },
          log: logLines.slice(), rpc: rpcLog.slice()
        });
        origLog('[ragRegress]', q.id, Math.round(t1 - t0) + 'ms', err || '');
      }
    } finally {
      window.expandQueryKeywords = origExpand;
      window.getQueryEmbedding = origEmbed;
      console.log = origLog;
    }
    out.cacheMiss = cacheMiss.slice();
    out.totalMs = out.results.reduce(function (a, r) { return a + r.ms; }, 0);
    window.ragRegress.last = out;
    window.ragRegress.embedCache = embedCache;
    return out;
  }

  window.ragRegress = { run: run, last: null, embedCache: null };
  origLog('[ragRegress] 준비됨 — await ragRegress.run({tag:"before"})');
})();
