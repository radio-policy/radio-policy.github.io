// tools_cite_replay.js — 과거 대시보드 자문을 인용 판정기(cite_verify.js) 두 판으로 재연해 **대상 선택·구조 판정**의 차이만 본다 (#286).
//   Anthropic 호출 0. chat_logs 행(답변·chunk_ids·cite_verdicts가 있는 것 — 2026-09-26부터 저장)마다 그때의 근거 청크를 다시 읽고
//   조문 보강(expandArticles)까지 운영과 같게 한 뒤, 옛 판과 새 판의 verifyCitations를 판정기 없이 돌려 (조·문서군·상태)가 달라진 표시를 찍는다.
//   저장된 답변은 검증 뒤 본문이라 바뀐 표시(「원문 없음 — …」·「원문과 다름 — …」)를 모델이 쓴 꼴(「[원문 확인됨: 대상]」)로 되돌려 넣는다.
//
//   node tools_cite_replay.js                       # HEAD 커밋의 cite_verify.js(옛) vs 작업 사본(새), 2026-09-01 이후
//   node tools_cite_replay.js --old path/old.js     # 옛 판 파일을 직접 지정
//   node tools_cite_replay.js --since 2026-10-01    # 기간
//   node tools_cite_replay.js --all-mismatch        # 판정기를 모두 「불일치」로 모의 — "주황이 될 수 있는 표시"가 어떻게 달라지는지(#286 ⓒ 회색 규칙)
//   node tools_cite_replay.js --dump out.json       # 새 판의 표시별 결과(답변 id·질문·tag·key·law·doc·status·reason·cmp·lawGuess)를 JSON으로 — 지금 코드 기준 회색·원문 없음 목록용
//   출력 셋(#288): changed(조·문서·상태가 바뀐 표시) · path-only(상태는 같고 대조 조문 이름표 cmp나 ⓒ 시도 기록만 바뀐 것 — 다중 원문) · shown-text(검증 뒤 본문의 표시 글자)
//   ⓒ(검색 자료 밖 조문 대조)는 DB 문서명 목록(RPC kb_doc_names)과 fetchLawArticle을 쓴다 — 실DB 읽기만, AI 0회
//
//   .env의 SUPABASE_URL·SUPABASE_SERVICE_KEY를 읽는다(service_role — chat_logs는 RLS로 묶여 있다). 세션 셸에서는 HTTP(S)_PROXY를 빼고 돌릴 것.
//   같은 코드 두 번 = 차이 0이어야 한다(판정기가 없으니 잡음도 없다). 규칙·문턱·불용어를 바꾼 뒤 이 재연과 node tests/cite_verify.test.js를 함께 본다.
const fs = require('fs'), path = require('path'), vm = require('vm'), os = require('os'), cp = require('child_process');
const REPO = __dirname;
const arg = function (name, dflt) { const i = process.argv.indexOf(name); return i !== -1 ? process.argv[i + 1] : dflt; };
const since = arg('--since', '2026-09-01');
const ALLMIS = process.argv.indexOf('--all-mismatch') !== -1;
const newPath = path.join(REPO, 'supabase', 'functions', '_shared', 'cite_verify.js');
let oldPath = arg('--old', null);
if (!oldPath) {
  oldPath = path.join(os.tmpdir(), 'cite_verify_head_' + process.pid + '.js');
  fs.writeFileSync(oldPath, cp.execSync('git show HEAD:supabase/functions/_shared/cite_verify.js', { cwd: REPO, maxBuffer: 1 << 24 }));
}

const env = {};
for (const line of fs.readFileSync(path.join(REPO, '.env'), 'utf8').split(/\r?\n/)) {
  const m = line.match(/^([A-Z_]+)=(.*)$/); if (m) env[m[1]] = m[2].trim().replace(/^"|"$/g, '');
}
const URL = env.SUPABASE_URL, KEY = env.SUPABASE_SERVICE_KEY;
if (!URL || !KEY) { console.error('.env에 SUPABASE_URL / SUPABASE_SERVICE_KEY 없음'); process.exit(2); }
async function rest(q) {
  const r = await fetch(URL + '/rest/v1/' + q, { headers: { apikey: KEY, Authorization: 'Bearer ' + KEY } });
  if (!r.ok) throw new Error('REST ' + r.status + ' ' + q.slice(0, 120));
  return r.json();
}
const enc = encodeURIComponent;

function loadModule(p) {   // 두 판을 서로 다른 전역에 올린다(globalThis.CiteVerify가 덮이지 않게)
  const src = fs.readFileSync(p, 'utf8');
  const ctx = { module: { exports: {} }, console, setTimeout, clearTimeout, Promise };
  ctx.globalThis = ctx;
  vm.runInNewContext(src, ctx, { filename: p });
  return ctx.module.exports;
}
function loadSystemPrompt() {   // 운영은 app_config.system_prompt — 저장소의 system_prompt.js와 같아야 한다(tools_release.py ③)
  const src = fs.readFileSync(path.join(REPO, 'system_prompt.js'), 'utf8') + '\n;this.__SP = typeof SYSTEM_PROMPT !== "undefined" ? SYSTEM_PROMPT : null;';
  const ctx = { window: {}, console }; ctx.globalThis = ctx;
  vm.runInNewContext(src, ctx);
  return ctx.__SP || (ctx.window && ctx.window.SYSTEM_PROMPT) || '';
}
// 옛 형식(~#286): 「[원문 없음 — 검색 자료에 해당 조문 없음 (대상)]」·「[원문과 다름 — 판정기 메모: … (대상)]」 — 괄호 안이 모델이 적은 대상.
// 새 형식(#286-보론~): 「[원문과 다름 — <대조 조문>와 대조: …]」·「[원문 없음 — 검색 자료에 <조문> 없음 (… · 표시: <대상>)]」·「[… 직접 확인: <조문> (표시: <대상>)]」
//   — 모델이 적은 대상은 「표시: …」에만 있고(대조 조문과 다를 때만), 없으면 대상 없는 「[원문 확인됨]」으로 되돌린다.
//   #286-보론부터 법령 이름 없는 초록이 대조한 조문으로 채워지므로, 저장된 초록은 모델이 이름을 적은 것과 구별할 수 없다(이름 적은 표시로 재연된다).
// #288: 「[원문 확인됨(검색 자료 밖 조문과 대조): X]」(ⓒ)는 모델이 쓴 「[원문 확인됨: X]」로 — 머리말이 초록이라 아래 되돌리기에 안 걸리지만,
//   그대로 두면 다시 읽을 때 괄호째 표시 글자가 된다(검증기는 괄호를 떼고 읽는다 — 재연 표시 글자를 운영 첫 판정과 맞추려고 여기서도 뗀다).
function untag(answer) {
  return String(answer || '').replace(/\[원문 확인됨\(검색 자료 밖[^)]*\): ([^\]]*)\]/g, '[원문 확인됨: $1]').replace(/\[(원문 없음 — |원문과 다름 — )([^\]]*)\]/g, function (all, head, body) {
    // 옛 꼴을 먼저 가른다(사내 관찰 ③ — 새 꼴 판별식 「검색 자료에 … 없음」이 옛 꼴 「검색 자료에 해당 조문 없음 (대상)」에도 걸려 대상을 잃었다)
    const isOld = /^판정기 메모: |^검색 자료에 해당 조문 없음|^자동 대조 못 함, 직접 확인(?: \(|$)/.test(body);
    if (isOld) {
      const m = body.match(/^(.*) \(([^()]*)\)$/);
      const tgt = m ? m[2].split(' · ')[0].trim() : '';
      return tgt && !/^법령 이름/.test(tgt) ? '[원문 확인됨: ' + tgt + ']' : '[원문 확인됨]';
    }
    const sm = body.match(/(?:^|[(·] ?)표시: ([^()·]+?)\)?$/);   // 새 꼴 — 모델 글자는 「표시: …」에만
    if (sm) return '[원문 확인됨: ' + sm[1].trim() + ']';
    return '[원문 확인됨]';   // 대조 조문은 판정기 것이지 모델 글자가 아니다
  });
}
// 되돌리기 자기 검사 — 꼴을 바꾸면 여기부터 깨진다
(function selfTest() {
  const cases = [
    ['[원문 없음 — 검색 자료에 해당 조문 없음 (전기통신사업법 제52조의3제2항)]', '[원문 확인됨: 전기통신사업법 제52조의3제2항]'],
    ['[원문과 다름 — 판정기 메모: 주체가 다름 (전파법 제24조제1항)]', '[원문 확인됨: 전파법 제24조제1항]'],
    ['[원문 없음 — 자동 대조 못 함, 직접 확인 (전기통신사업법 제55조제2항)]', '[원문 확인됨: 전기통신사업법 제55조제2항]'],
    ['[원문 없음 — 검색 자료에 해당 조문 없음]', '[원문 확인됨]'],
    ['[원문 없음 — 검색 자료에 전파법 시행령 제24조제1항 없음 (법령 이름 없음 → 전파법 시행령으로 봄)]', '[원문 확인됨]'],
    ['[원문 없음 — 검색 자료에 전파법 제5조 없음 (법령 이름 못 맞춤 → 전파법으로 봄 · 표시: 주파수 세부사항 제5조)]', '[원문 확인됨: 주파수 세부사항 제5조]'],
    ['[원문과 다름 — 전파법 제19조제1항과 대조: 무선국 개설허가 규정 (표시: 전기통신사업법 제19조제1항)]', '[원문 확인됨: 전기통신사업법 제19조제1항]'],
    ['[원문 없음 — 자동 대조 못 함, 직접 확인: 전기통신사업법 제55조제2항]', '[원문 확인됨]'],
    // #288 새 꼴: ⓒ 검색 자료 밖 조문 대조 · §5 항 구분 없음(괄호 안 괄호) · ⓓ′ 다중 원문 · ⓑ 고시 번호 추측
    ['[원문 확인됨(검색 자료 밖 조문과 대조): 전기통신사업법 제53조제1항]', '[원문 확인됨: 전기통신사업법 제53조제1항]'],
    ['[원문 없음 — 자동 대조 못 함, 직접 확인: 법령 이름 없음 → 전기통신사업법 제96조제2항 (조문에 항 구분 없음(제2항 표기) · 제2호를 뜻했을 수 있음)]', '[원문 확인됨]'],
    ['[원문 없음 — 자동 대조 못 함, 직접 확인: 전기통신사업법 제96조제2항 (조문에 항 구분 없음(제2항 표기) · 표시: 전기통신사업법 제96조②)]', '[원문 확인됨: 전기통신사업법 제96조②]'],
    ['[원문과 다름 — 법령 이름 없음 → 전기통신사업법 제19조제1항·전기통신사업법 시행령 제24조제1항과 대조: 기한 다름]', '[원문 확인됨]'],
    ['[원문과 다름 — 전기통신사업법 제53조제1항과 대조: 비율 다름 (검색 자료 밖 조문 · 표시: 사업법 제53조①)]', '[원문 확인됨: 사업법 제53조①]'],
    ['[원문 없음 — 자동 대조 못 함, 직접 확인: 고시 번호로 봄 → 경제적 이익 등 제공의 부당한 이용자 차별행위에 관한 세부기준 제1조와 대조하면 다름(같은 번호의 다른 고시일 수 있음) (표시: 방송미디어통신위원회고시 제2026-11호 제1조)]', '[원문 확인됨: 방송미디어통신위원회고시 제2026-11호 제1조]'],
  ];
  for (const [inp, want] of cases) { const got = untag(inp); if (got !== want) { console.error('untag 자기 검사 실패:', inp, '→', got, '(기대 ' + want + ')'); process.exit(2); } }
})();
const EXPAND_OPTS = { maxArticles: 10, maxChunksPerArticle: 4, maxAddedChunks: 14 };   // verify-citations/index.ts와 같은 값
const SEL = 'id,doc_name,article_no,chunk_index,content';
async function fetchChunksByIds(ids) {
  if (!ids.length) return [];
  const rows = await rest('document_chunks?select=' + SEL + '&id=in.(' + ids.join(',') + ')');
  const by = new Map(rows.map(function (r) { return [r.id, r]; }));
  return ids.map(function (id) { return by.get(id); }).filter(Boolean);
}
const artCache = new Map();
function fetchArticle(docName, key) {
  const k = docName + '|' + key;
  if (!artCache.has(k)) artCache.set(k, rest('document_chunks?select=' + SEL + '&doc_name=eq.' + enc(docName) + '&status=eq.current&is_approved=eq.true&article_no=like.' + enc(key + '*') + '&order=chunk_index.asc&limit=40'));
  return artCache.get(k);
}
const lawCache = new Map();
function fetchLawArticle(family, key) {
  const k = family + '|' + key;
  if (!lawCache.has(k)) lawCache.set(k, rest('document_chunks?select=' + SEL + ',status&doc_name=like.' + enc(family + '(*') + '&status=in.(current,pending)&is_approved=eq.true&article_no=like.' + enc(key + '*') + '&order=chunk_index.asc&limit=80'));
  return lawCache.get(k);
}
// DB 문서명 목록(#288 ⓒ — 운영은 RPC kb_doc_names 현행·시행예정, verify-citations/index.ts·rag.ts와 같은 조회)
let lawDocsP = null;
async function rpc(fn, body) {
  const r = await fetch(URL + '/rest/v1/rpc/' + fn, { method: 'POST', headers: { apikey: KEY, Authorization: 'Bearer ' + KEY, 'content-type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error('RPC ' + fn + ' ' + r.status);
  return r.json();
}
function listLawDocs() {
  if (!lawDocsP) lawDocsP = Promise.all([rpc('kb_doc_names', { p_status: 'current' }), rpc('kb_doc_names', { p_status: 'pending' })])
    .then(function (ab) { return ab[0].concat(ab[1]).map(function (x) { return x.doc_name; }); });
  return lawDocsP;
}
function fakeJudges() {   // 1차 전부 불일치, 2차 전부 불일치 + 원문·인용문의 실제 조각을 근거 구절로(grounded)
  return {
    callHaiku: async function (sys, user) {
      const n = (user.match(/### 항목 \d+/g) || []).length;
      return JSON.stringify(Array.from({ length: n }, function (_, i) { return { id: i + 1, verdict: '불일치', reason: '모의' }; }));
    },
    callJudge2: async function (sys, user) {
      const claim = (user.split('[인용문]\n')[1] || '').split('\n[원문]\n')[0], src = user.split('\n[원문]\n')[1] || '';
      return JSON.stringify([{ id: 1, verdict: '불일치', source_span: src.replace(/\s+/g, ' ').trim().slice(0, 40), claim_span: claim.replace(/\s+/g, ' ').trim().slice(0, 30), reason: '모의 불일치' }]);
    },
  };
}
function brief(v) {
  return { tag: v.tag, key: v.key, law: v.law, doc: v.doc ? v.doc.split('(')[0] : null, status: v.status === 'unjudged' ? 'found' : v.status, reason: v.reason, guess: v.lawGuess || null, ev: v.guessEvidence == null ? null : !!v.guessEvidence,
    cmp: v.cmp || null, src: v.srcFetched || null };
}
// 바뀐 표시 글자 — 답변 안 표시를 순서대로(검증 뒤 본문). 판정기 없이 돌리므로 판정기행(unjudged)은 「대조 못 함」 꼴로 나온다
function shownTags(answer) { return String(answer || '').match(/\[원문[^\]]*\]/g) || []; }
(async function main() {
  const OLD = loadModule(oldPath), NEW = loadModule(newPath), sp = loadSystemPrompt();
  const rows = await rest('chat_logs?select=id,created_at,channel,question,answer,chunk_ids,cite_verdicts&created_at=gte.' + since + '&cite_verdicts=not.is.null&chunk_ids=not.is.null&order=created_at.asc&limit=300');
  console.log('rows', rows.length, 'since', since, ALLMIS ? '(모의 판정: 전부 불일치)' : '(판정기 없음 — 구조만)', '| old =', oldPath);
  let items = 0, diffs = 0, pathDiffs = 0, textDiffs = 0;
  const textLog = [];
  const summary = { old: {}, new: {} };
  const dumpPath = arg('--dump', null), dump = [];
  for (const row of rows) {
    if (!Array.isArray(row.cite_verdicts) || !row.cite_verdicts.length) continue;
    const ids = (row.chunk_ids || []).filter(function (x) { return typeof x === 'number'; }).slice(0, 80);
    const chunks0 = await fetchChunksByIds(ids);
    const answer = untag(row.answer);
    const out = {}, shown = {};
    for (const pair of [['old', OLD], ['new', NEW]]) {
      const name = pair[0], CV = pair[1];
      let chunks = chunks0.slice();
      try { chunks = (await CV.expandArticles(chunks, fetchArticle, EXPAND_OPTS)).chunks; } catch (e) { console.warn('expand fail', e.message); }
      const judges = ALLMIS ? fakeJudges() : { callHaiku: null, callJudge2: null };
      // listLawDocs(#288 ⓒ)는 옛 판이 모르는 인자라 넘겨도 무시된다
      const vr = await CV.verifyCitations({ answer: answer, chunks: chunks, annexSources: [], systemPrompt: sp, callHaiku: judges.callHaiku, callJudge2: judges.callJudge2, fetchLawArticle: fetchLawArticle, listLawDocs: listLawDocs });
      out[name] = vr.verdicts.map(brief);
      shown[name] = shownTags(vr.answer);
      for (const v of out[name]) summary[name][v.status] = (summary[name][v.status] || 0) + 1;
      if (name === 'new' && dumpPath) for (const v of vr.verdicts) dump.push({ id: row.id, created_at: row.created_at, channel: row.channel, question: String(row.question || '').slice(0, 80), tag: v.tag, key: v.key, law: v.law, doc: v.doc, status: v.status, reason: v.reason, cmp: v.cmp || null, lawGuess: v.lawGuess || null, guessEvidence: v.guessEvidence == null ? null : v.guessEvidence, verbatim: v.verbatim, overlap: v.overlap, multi: v.multi || null, srcFetched: v.srcFetched || null, nopara: v.nopara || null });
    }
    const n = Math.max(out.old.length, out.new.length);
    items += n;
    for (let i = 0; i < n; i++) {
      const a = out.old[i], b = out.new[i];
      const ka = a ? [a.key, a.doc, a.status].join('|') : '-', kb = b ? [b.key, b.doc, b.status].join('|') : '-';
      const head = '\n# ' + row.created_at.slice(0, 16) + ' ' + row.id.slice(0, 8) + ' Q: ' + String(row.question || '').slice(0, 40);
      if (ka !== kb) {
        diffs++;
        console.log(head);
        console.log('  tag : ' + (a || b).tag);
        console.log('  old : ' + ka + (a && a.reason ? '  — ' + a.reason : ''));
        console.log('  new : ' + kb + (b && b.reason ? '  — ' + b.reason : '') + (b && b.guess ? '  [guess=' + b.guess + ' ev=' + b.ev + ']' : '') + (b && b.src ? '  [src=' + b.src + ']' : ''));
      } else if (a && b && (a.cmp !== b.cmp || a.src !== b.src)) {
        // 판정 경로만 바뀐 것(#288 — 다중 원문으로 대조 조문이 늘거나 ⓒ를 시도만 함): 상태·대표 조문은 같다
        pathDiffs++;
        console.log(head + '  [경로만]');
        console.log('  tag : ' + a.tag);
        console.log('  cmp : ' + a.cmp + '  →  ' + b.cmp + (b.src ? '  [src=' + b.src + ']' : ''));
      }
    }
    // 바뀐 표시 글자(검증 뒤 본문) — 상태가 같아도 이름표가 바뀌면 여기 나온다
    const m2 = Math.max(shown.old.length, shown.new.length);
    for (let i = 0; i < m2; i++) if (shown.old[i] !== shown.new[i]) { textDiffs++; textLog.push(row.id.slice(0, 8) + ' #' + i + '\n    old ' + (shown.old[i] || '-') + '\n    new ' + (shown.new[i] || '-')); }
  }
  console.log('\nitems', items, 'changed', diffs, 'path-only', pathDiffs, 'shown-text', textDiffs);
  if (textLog.length) console.log('\n[표시 글자 변화]\n  ' + textLog.join('\n  '));
  console.log('old', JSON.stringify(summary.old));
  console.log('new', JSON.stringify(summary.new));
  if (dumpPath) { fs.writeFileSync(dumpPath, JSON.stringify(dump, null, 1), 'utf8'); console.log('dump', dump.length, '→', dumpPath); }
})().catch(function (e) { console.error(e); process.exit(1); });
