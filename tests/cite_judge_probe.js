// ============================================================================
//  tests/cite_judge_probe.js — 인용 판정기(1차 Haiku · 2차) 실측 (2026-10-05)
//
//  운영과 같은 supabase/functions/_shared/cite_verify.js로 판정기 입력(대상·인용문·원문)을 만들고, 실제 API로 다시 판정해
//  거짓 「원문과 다름」(real F)·진짜 불일치(synthetic T·S)·초록 표본(green)의 결과를 센다. 고정 자료 tests/fixtures/cite_judge_cases.json.
//  기본은 --dry-run(API 0 — 세트 구성·어림 비용만). 실제 판정은 --allow-api(운영자 고지 뒤 — 일회성 실측이라 사람이 승인한 지출만).
//
//    node tests/cite_judge_probe.js                         # 구성·어림 비용
//    node tests/cite_judge_probe.js --allow-api [--rep1 3] [--rep2 3] [--rep2g 1] [--variants prod,s55m] [--green-stage2] [--only F1,T1]
//
//  1차는 자문 단위 묶음(운영과 같은 한 호출)을 rep1번, 2차는 대상 항목 하나씩 rep2번(변형마다). 2차 'prod' 변형은 cite_verify.js의
//  JUDGE2_MODEL·JUDGE2_REQUEST 그대로다(운영 요청과 같다). 결과 전문은 local_docs/cite_judge_probe/(git 무시)에 남긴다.
//  .env의 SUPABASE_URL·SUPABASE_SERVICE_KEY(읽기 + api_usage 기록)·ANTHROPIC_API_KEY를 쓴다. 판정기 지시문을 고치면 이 도구로 다시 잰다.
//
//  기준선(2026-10-05, 합계 ≈ $2.5): 1차(Haiku, 운영 JUDGE_SYSTEM)는 거짓 5개(F1·F3·F5·F6·F7)를 3회 중 F1·F5·F6·F7 3/3, F3 1/3 불일치로 냈다
//  (= 지금까지의 거짓 주황). 2차 고정 사례 12개(거짓 5 + 진짜 T1·T1b·T2·S1~S4) × 4회: prod(Opus 5.5 medium) 거짓 주황 0/20 · 진짜 28/28 주황.
//  s5(Sonnet 5, 추론 끔) F5 6/8 거짓 주황 · T2·S2 일부 놓침, s55m(Sonnet 5.5 medium) F6 4/8 거짓 주황, 지시문 후보(일부만 든 것을 대상 일반으로 넓힘)는
//  F6을 고치고 F5를 4/4로 되돌려 기각. 초록 표본 64항목: 1차 192회 중 41회 불일치(17항목) → prod 2차 1회: 주황 1(제19조①에 없는 무선국 폐지 신고)·일치 7·판단불가 9.
//  o48(Opus 4.8 추론 끔 — 사내 후보, 같은 날 사내 요청): 거짓 주황 0/20이지만 T1b(그림 07 꼴, 주체 한정 생략)를 4/4 「주체 생략됐으나 내용 일치」로 놓침 —
//  2차 일치 = 초록이면 진짜 주황이 초록이 된다(그 밖 진짜 24/24 주황, F1은 판단불가 4/4).
// ============================================================================
'use strict';
const fs = require('fs');
const path = require('path');
const REPO = path.join(__dirname, '..');
const CV = require(path.join(REPO, 'supabase', 'functions', '_shared', 'cite_verify.js'));
const FX = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'cite_judge_cases.json'), 'utf8'));

const argv = process.argv.slice(2);
const arg = function (k, d) { const i = argv.indexOf(k); return i === -1 ? d : argv[i + 1]; };
const ALLOW = argv.includes('--allow-api');
const REP1 = +arg('--rep1', 3), REP2 = +arg('--rep2', 3), REP2G = +arg('--rep2g', 1);   // REP2G = 초록 표본 항목의 2차 반복
const ONLY = arg('--only', '') ? arg('--only', '').split(',') : null;
const GREEN2 = argv.includes('--green-stage2');
const HAIKU = 'claude-haiku-4-5-20251001';
const VARIANTS = {
  prod: { model: CV.JUDGE2_MODEL, extra: CV.JUDGE2_REQUEST, max: CV.JUDGE2_MAX_TOKENS },
  s5: { model: 'claude-sonnet-5', extra: { thinking: { type: 'disabled' } }, max: 2000 },
  s55m: { model: 'claude-sonnet-5-5', extra: { output_config: { effort: 'medium' } }, max: 8000 },
  o55m: { model: 'claude-opus-5-5', extra: { output_config: { effort: 'medium' } }, max: 8000 },
  o48: { model: 'claude-opus-4-8', extra: { thinking: { type: 'disabled' } }, max: 2000 },   // 사내판 후보(사내 플랫폼에 Opus 5.5 없음, 2026-10-05 사내 요청)
  // 지시문 후보 시험용 — system을 바꿔 보낸다(운영 JUDGE2_SYSTEM은 그대로). 후보 글은 아래 CAND_SYSTEM
  s55m_cand: { model: 'claude-sonnet-5-5', extra: { output_config: { effort: 'medium' } }, max: 8000, cand: true },
};
// 2차 지시문 후보(채택하면 cite_verify.js JUDGE2_SYSTEM으로 옮기고 시험 지문을 갱신한다). 아래는 2026-10-05에 기각한 후보 — 다음 후보를 잴 때 바꿔 쓴다
const CAND_SYSTEM = CV.JUDGE2_SYSTEM.replace(
  '원문이 어느 하나에 해당하면 되는 대상·행위를 여럿 나열하는데 인용문이 그중 일부만 든 것(든 것이 원문 목록에 있으면 일치)',
  '원문이 정한 대상(주체·상대방·행위·조항 목록) 가운데 일부만 들어 말한 것 — 든 것이 원문에 들어 있으면 일치(인용문이 「…이란 …이다」처럼 정의를 통째로 옮기면서 일부를 뺀 것은 제외)');
const VARS = arg('--variants', 'prod').split(',').filter(function (v) { return VARIANTS[v]; });
const PRICE = { 'claude-haiku-4-5-20251001': [1, 5], 'claude-sonnet-5': [2, 10], 'claude-sonnet-5-5': [2, 10], 'claude-opus-5-5': [4, 20], 'claude-opus-4-8': [5, 25] };   // $/MTok 입력·출력

const env = {};
for (const line of fs.readFileSync(path.join(REPO, '.env'), 'utf8').split(/\r?\n/)) {
  const m = line.match(/^([A-Z_]+)=(.*)$/); if (m) env[m[1]] = m[2].trim().replace(/^['"]|['"]$/g, '');
}
const SB = env.SUPABASE_URL.replace(/\/+$/, ''), SKEY = env.SUPABASE_SERVICE_KEY;
const SH = { apikey: SKEY, Authorization: 'Bearer ' + SKEY };
async function sbGet(p) {
  const r = await fetch(SB + '/rest/v1/' + p, { headers: SH });
  if (!r.ok) throw new Error('supabase ' + r.status + ' ' + (await r.text()).slice(0, 200));
  return r.json();
}
async function chunksByIds(ids) {
  let out = [];
  for (let i = 0; i < ids.length; i += 60) out = out.concat(await sbGet('document_chunks?id=in.(' + ids.slice(i, i + 60).join(',') + ')&select=id,doc_name,article_no,chunk_index,content'));
  const by = new Map(out.map(function (c) { return [c.id, c]; }));
  return ids.map(function (id) { return by.get(id); }).filter(Boolean);
}
// 조문 통째 보강(운영 fetchArticleChunks와 같은 조건 — 단, 당시 현행이던 판도 읽게 status 조건은 뺀다: doc_name에 판이 들어 있다)
async function fetchArticle(doc, key) {
  return sbGet('document_chunks?doc_name=eq.' + encodeURIComponent(doc) + '&is_approved=eq.true&article_no=like.' + encodeURIComponent(key + '*') +
    '&order=chunk_index.asc&limit=40&select=id,doc_name,article_no,chunk_index,content');
}
// 저장된 답변(검증 뒤 꼬리표)을 모델 원래 답변으로 되돌린다 — 판정 기록이 있으면 순서대로 정확히, 없으면 꼬리표 꼴로
const ANY_TAG_RE = /\[(?:원문\s*확인됨|원문 없음 — [^\]]*|원문과 다름 — 판정기 메모: )[^\]]*\]/g;
function restoreAnswer(answer, verdicts) {
  const vs = (verdicts || []).filter(function (v) { return v.status !== 'dup'; });
  const tags = [];
  let m; ANY_TAG_RE.lastIndex = 0;
  while ((m = ANY_TAG_RE.exec(answer))) tags.push({ i: m.index, end: m.index + m[0].length });
  if (verdicts && tags.length === vs.length) {
    let out = answer;
    for (let k = tags.length - 1; k >= 0; k--) {
      const t = tags[k], v = vs[k];
      if (v.auto === 'quote') { const lead = /\s$/.test(out.slice(0, t.i)) ? t.i - 1 : t.i; out = out.slice(0, lead) + out.slice(t.end); }
      else out = out.slice(0, t.i) + v.tag + out.slice(t.end);
    }
    return out;
  }
  return String(answer || '')
    .replace(/\[원문과 다름 — 판정기 메모: [^\]]*?\(([^()\]]*(?:\([^()\]]*\)[^()\]]*)*)\)\]/g, '[원문 확인됨: $1]')
    .replace(/\[원문 없음 — [^\]]*?\(([^()\]]*(?:\([^()\]]*\)[^()\]]*)*)\)\]/g, '[원문 확인됨: $1]')
    .replace(/\[(?:원문과 다름|원문 없음)[^\]]*\]/g, '[원문 확인됨]')
    .replace(/\[⚠️ 원문[^\]]*\]/g, '[원문 확인됨]')
    .replace(/\[원문 확인 안 됨[^\]]*\]/g, '[원문 확인됨]');
}
// 운영과 같은 경로로 판정기 입력 항목을 뽑는다(판정은 흉내 — '일치')
async function judgeItems(answer, chunks, systemPrompt) {
  const ex = await CV.expandArticles(chunks, fetchArticle, { maxArticles: 10, maxChunksPerArticle: 4, maxAddedChunks: 14 });
  const items = [];
  await CV.verifyCitations({ answer: answer, chunks: ex.chunks, annexSources: [], systemPrompt: systemPrompt, callHaiku: async function (sys, user) {
    for (const p of user.split(/\n\n(?=### 항목 \d+\n)/)) {
      const mm = p.match(/^### 항목 (\d+)\n\[인용 대상\] (.*)\n\[인용문\]\n([\s\S]*?)\n\[원문\]\n([\s\S]*)$/);
      if (mm) items.push({ id: +mm[1], target: mm[2], claim: mm[3], source: mm[4] });
    }
    return JSON.stringify(items.map(function (x) { return { id: x.id, verdict: '일치', reason: '' }; }));
  } });
  return items;
}
const tok = function (s) { return Math.ceil(String(s || '').length / 1.2); };   // 한글 어림(글자/1.2)
const usageSum = {};
async function recordUsage(site, model, u) {
  const k = model; usageSum[k] = usageSum[k] || [0, 0, 0];
  usageSum[k][0] += (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0); usageSum[k][1] += u.output_tokens || 0; usageSum[k][2]++;
  try {
    await fetch(SB + '/rest/v1/api_usage', { method: 'POST', headers: Object.assign({ 'content-type': 'application/json', Prefer: 'return=minimal' }, SH),
      body: JSON.stringify({ host: 'pc', site: site.slice(0, 80), model: model, input_tokens: u.input_tokens || 0, cache_read: u.cache_read_input_tokens || 0,
        cache_write: u.cache_creation_input_tokens || 0, output_tokens: u.output_tokens || 0 }) });
  } catch (e) { /* 기록 실패는 삼킨다(fail-open) */ }
}
async function callModel(model, extra, maxTokens, system, user, site) {
  for (let attempt = 0; ; attempt++) {
    const res = await fetch('https://api.anthropic.com/v1/messages', { method: 'POST',
      headers: { 'x-api-key': env.ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
      body: JSON.stringify(Object.assign({ model: model, max_tokens: maxTokens }, extra || {}, { system: system, messages: [{ role: 'user', content: user }] })) });
    if ((res.status === 429 || res.status === 529 || res.status >= 500) && attempt < 4) { await new Promise(function (r) { setTimeout(r, 4000 * (attempt + 1)); }); continue; }
    const data = await res.json();
    if (!res.ok) throw new Error(model + ' HTTP ' + res.status + ' ' + JSON.stringify(data).slice(0, 200));
    await recordUsage(site, model, data.usage || {});
    if (data.stop_reason === 'refusal') throw new Error('refusal');
    return (data.content || []).find(function (b) { return b.type === 'text'; })?.text || '';
  }
}
async function pool(tasks, n) {
  const out = new Array(tasks.length); let next = 0;
  await Promise.all(Array.from({ length: n }, async function () { while (next < tasks.length) { const i = next++; out[i] = await tasks[i](); } }));
  return out;
}
const keyRe = function (k) { return new RegExp('\\s' + k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(\\s|$)'); };

(async function main() {
  const sp = (await sbGet('app_config?key=eq.system_prompt&select=value'))[0];
  const systemPrompt = sp ? sp.value : '';
  // ── 세트 구성 ──
  const batches = [];   // {name, items:[{...,case}], cases}
  const realIds = [...new Set(FX.real.map(function (r) { return r.chat_log; }))];
  const green = await sbGet('chat_logs?select=id,created_at,answer,chunk_ids,cite_verdicts&answer=like.*%5B%EC%9B%90%EB%AC%B8*&created_at=lte.' + encodeURIComponent(FX.cutoff) + '&order=created_at.asc');
  const rows = green.slice();
  for (const id of realIds) if (!rows.some(function (r) { return r.id === id; })) rows.push((await sbGet('chat_logs?id=eq.' + id + '&select=id,created_at,answer,chunk_ids,cite_verdicts'))[0]);
  for (const r of rows) {
    const chunks = await chunksByIds((r.chunk_ids || []).filter(function (x) { return typeof x === 'number'; }));
    const items = await judgeItems(restoreAnswer(r.answer, r.cite_verdicts), chunks, systemPrompt);
    if (!items.length) continue;
    for (const it of items) {
      const c = FX.real.find(function (f) { return f.chat_log === r.id && keyRe(f.target).test(it.target); });
      it.case = c ? c.key : 'G'; it.gold = c ? c.gold : '일치?';
    }
    batches.push({ name: r.id.slice(0, 8), items: items });
  }
  for (const s of FX.synthetic) {
    const items = await judgeItems(s.answer, await chunksByIds(s.chunk_ids), systemPrompt);
    items.forEach(function (it) { it.case = s.key; it.gold = s.gold; });
    batches.push({ name: s.key, items: items });
  }
  const sel = ONLY ? batches.filter(function (b) { return b.items.some(function (it) { return ONLY.indexOf(it.case) !== -1; }); }) : batches;
  const allItems = [].concat.apply([], sel.map(function (b) { return b.items; }));
  const fixed = allItems.filter(function (it) { return it.case !== 'G'; });
  const missingCases = FX.real.concat(FX.synthetic).map(function (c) { return c.key; }).filter(function (k) { return !allItems.some(function (it) { return it.case === k; }) && (!ONLY || ONLY.indexOf(k) !== -1); });
  console.log('묶음 ' + sel.length + ' · 항목 ' + allItems.length + ' (고정 사례 ' + fixed.length + ': ' + fixed.map(function (x) { return x.case; }).join(',') + ')' + (missingCases.length ? ' · ⚠ 판정기로 안 간 사례: ' + missingCases.join(',') : ''));
  // 어림 비용
  const sys1 = tok(CV.JUDGE_SYSTEM), sys2 = tok(CV.JUDGE2_SYSTEM);
  let in1 = 0; for (const b of sel) in1 += sys1 + b.items.reduce(function (a, it) { return a + tok(it.claim) + tok(it.source) + 30; }, 0);
  const n2 = fixed.length * REP2 + (GREEN2 ? (allItems.length - fixed.length) * REP2G : 0);   // 2차 호출 수(변형마다)
  const est = (in1 * REP1 * 1 + sel.length * REP1 * 150 * 5) / 1e6 + VARS.reduce(function (a, v) { const pr = PRICE[VARIANTS[v].model] || [4, 20]; return a + n2 * ((sys2 + 600) * pr[0] + (VARIANTS[v].model === 'claude-sonnet-5' ? 200 : 400) * pr[1]) / 1e6; }, 0);
  console.log('어림 비용 ≈ $' + est.toFixed(2) + ' (1차 ' + sel.length + '묶음×' + REP1 + ', 2차 변형마다 ' + n2 + '회 × ' + VARS.join('/') + ')');
  if (!ALLOW) { console.log('--dry-run: API 0회. 실제 판정은 --allow-api'); return; }

  // ── 1차: 자문 묶음째 REP1번 ──
  const t1 = [];
  for (const b of sel) for (let k = 0; k < REP1; k++) t1.push(function () {
    return CV.judgeCitations(b.items, function (s, u) { return callModel(HAIKU, null, 3000, s, u, 'cite_judge_probe:stage1'); })
      .then(function (v) { return { b: b, v: v }; }, function (e) { return { b: b, err: String(e.message || e) }; });
  });
  const r1 = await pool(t1, 4);
  for (const it of allItems) it.s1 = [];
  for (const x of r1) for (const it of x.b.items) it.s1.push(x.err ? 'ERR' : ((x.v[String(it.id)] || {}).verdict || '없음') + (x.v[String(it.id)] && x.v[String(it.id)].verdict === '불일치' ? ':' + x.v[String(it.id)].reason : ''));
  // ── 2차: 고정 사례 전부 + (green은 1차 불일치가 한 번이라도 난 것, --green-stage2면 전부) ──
  const t2 = [];
  for (const it of allItems) {
    const s1m = it.s1.some(function (s) { return s.indexOf('불일치') === 0; });
    if (!(it.case !== 'G' || s1m || GREEN2)) continue;
    it.s2 = {};
    for (const vn of VARS) {
      it.s2[vn] = [];
      for (let k = 0; k < (it.case === 'G' ? REP2G : REP2); k++) t2.push(function () {
        const V = VARIANTS[vn];
        return CV.judgeCitations2([Object.assign({}, it, { id: 1 })], function (s, u) { return callModel(V.model, V.extra, V.max, V.cand ? CAND_SYSTEM : s, u, 'cite_judge_probe:stage2:' + vn); })
          .then(function (v) { it.s2[vn].push(v['1'] || { verdict: '없음' }); }, function (e) { it.s2[vn].push({ verdict: 'ERR', reason: String(e.message || e) }); });
      });
    }
  }
  await pool(t2, 4);
  // ── 보고 ──
  const outDir = path.join(REPO, 'local_docs', 'cite_judge_probe');
  fs.mkdirSync(outDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  fs.writeFileSync(path.join(outDir, 'run_' + stamp + '.json'), JSON.stringify({ args: argv, variants: VARS, items: allItems }, null, 1));
  const cnt = function (arr, f) { return arr.filter(f).length; };
  console.log('\n사례 | 정답 | 1차 불일치 | ' + VARS.map(function (v) { return v + ' 불일치(근거 실재)/일치/보류'; }).join(' | ') + ' | 최종 주황률(' + VARS.join('/') + ')');
  for (const it of allItems.filter(function (x) { return x.case !== 'G' || x.s2; })) {
    const p1 = cnt(it.s1, function (s) { return s.indexOf('불일치') === 0; }) / it.s1.length;
    const cols = VARS.map(function (v) { const a = (it.s2 && it.s2[v]) || []; return cnt(a, function (x) { return x.verdict === '불일치'; }) + '(' + cnt(a, function (x) { return x.grounded; }) + ')/' + cnt(a, function (x) { return x.verdict === '일치'; }) + '/' + cnt(a, function (x) { return x.verdict !== '일치' && x.verdict !== '불일치'; }); });
    const fin = VARS.map(function (v) { const a = (it.s2 && it.s2[v]) || []; return a.length ? (p1 * cnt(a, function (x) { return x.grounded; }) / a.length).toFixed(2) : '-'; });
    console.log(it.case + ' | ' + it.gold + ' | ' + cnt(it.s1, function (s) { return s.indexOf('불일치') === 0; }) + '/' + it.s1.length + ' | ' + cols.join(' | ') + ' | ' + fin.join('/') + '  [' + it.target + ']');
  }
  const g = allItems.filter(function (x) { return x.case === 'G'; });
  console.log('\n초록 표본 ' + g.length + '항목: 1차 불일치가 한 번이라도 난 항목 ' + cnt(g, function (x) { return x.s1.some(function (s) { return s.indexOf('불일치') === 0; }); }) +
    ' · 1차 판정 ' + g.reduce(function (a, x) { return a + x.s1.length; }, 0) + '회 중 불일치 ' + g.reduce(function (a, x) { return a + cnt(x.s1, function (s) { return s.indexOf('불일치') === 0; }); }, 0) + '회');
  let cost = 0;
  for (const m in usageSum) { const p = PRICE[m] || [3, 15]; const c = (usageSum[m][0] * p[0] + usageSum[m][1] * p[1]) / 1e6; cost += c; console.log('  ' + m + ': ' + usageSum[m][2] + '회 입력 ' + usageSum[m][0] + ' 출력 ' + usageSum[m][1] + ' ≈ $' + c.toFixed(3)); }
  console.log('실제 비용 ≈ $' + cost.toFixed(3) + ' · 결과 전문 local_docs/cite_judge_probe/run_' + stamp + '.json');
})().catch(function (e) { console.error(e); process.exit(1); });
