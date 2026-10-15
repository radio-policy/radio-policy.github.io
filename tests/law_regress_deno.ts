// /law 자연어 모드 회귀 하네스 — rag.ts buildLawQueryContext (#303, 2026-10-14)
//
// 자문 하네스(tests/rag_regress_deno.ts)와 같은 방식: Haiku 확장은 픽스처(tests/fixtures/law_regression_set.json)의 고정 확장어,
// Voyage 임베딩은 tests/fixtures/rag_regress_embed_cache.json(캐시에 없는 질문만 VOYAGE_API_KEY로 받아 캐시에 추가) → Anthropic API 0회.
// 실행(저장소 루트, .env의 SUPABASE_URL·SUPABASE_SERVICE_KEY 사용; deno는 npm 패키지 `deno` — `npx --no-install deno`):
//   npx --no-install deno run --no-check --allow-net --allow-env --allow-read --allow-write tests/law_regress_deno.ts --tag after
//     [--rag <rag.ts 사본 경로>] [--only l01,l02] [--set <질문 세트>] [--no-expand] [--raw] [--with-text]
// 출력: tests/fixtures/rag_regress_out/law_<tag>_<시각>.json — 질문마다
//   merged  : [검색된 조문] 목록(바탕 검색 — 문서명 앞부분 + 조항, 지목 조문은 '★'), named 수, kb 제목
//   addItems: 덧붙인 항목(sec·dir·fam·key — rag_core.js fetchAddOns의 items), addon: 덧붙인 조각 id
//   lens    : system 전체·[검색된 조문] 구역·덧붙이기 구역 글자 수, meta: search_meta(addons·law_delegations 행)
//   --with-text면 sys(= Haiku에 들어갈 system 전문)도 남긴다.
// 비교 방법: 바탕(merged)이 두 파일에서 같은지(덧붙이기는 뒤에 이어 붙일 뿐 바탕을 바꾸지 않아야 한다) + addItems가 무엇을 더했는지를
//   사람이 읽어 관련성을 매긴다(기록 local_docs/law_probe_261014/). 결정적 모드(기본)는 자문 하네스와 같이 document_chunks의 order 없는 limit에
//   order('id')를 붙인다(요약층 다리의 ilike limit 40이 그 경우). --raw는 운영 그대로.
import { createClient } from 'jsr:@supabase/supabase-js@2';

const ROOT = new URL('../', import.meta.url);
const argvEarly = (name: string) => { const i = Deno.args.indexOf(name); return i >= 0 ? Deno.args[i + 1] : ''; };
const setPath = argvEarly('--set') ? new URL(argvEarly('--set'), ROOT) : new URL('fixtures/law_regression_set.json', ROOT + 'tests/');
const cachePath = new URL('fixtures/rag_regress_embed_cache.json', ROOT + 'tests/');
const outDir = new URL('fixtures/rag_regress_out/', ROOT + 'tests/');

function parseEnvFile(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$/);
    if (m) out[m[1]] = m[2].trim().replace(/^"(.*)"$/, '$1');
  }
  return out;
}
const dotenv = parseEnvFile(await Deno.readTextFile(new URL('.env', ROOT)).catch(() => ''));
for (const k of ['SUPABASE_URL', 'SUPABASE_SERVICE_KEY', 'VOYAGE_API_KEY']) {
  if (!Deno.env.get(k) && dotenv[k]) Deno.env.set(k, dotenv[k]);
}
if (!Deno.env.get('ANTHROPIC_API_KEY')) Deno.env.set('ANTHROPIC_API_KEY', 'test');   // 훅이 가로챈다 — 실제 호출 없음

const args = Deno.args;
const argv = (name: string) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : ''; };
const tag = argv('--tag') || 'run';
const only = argv('--only') ? new Set(argv('--only').split(',')) : null;
const deterministic = !args.includes('--raw');
const withText = args.includes('--with-text');
const noExpand = args.includes('--no-expand');
const ragPath = argv('--rag') ? new URL(argv('--rag'), ROOT) : new URL('supabase/functions/_shared/rag.ts', ROOT);

const rag = await import(ragPath.href);
const set = JSON.parse(await Deno.readTextFile(setPath));
let cache: Record<string, number[]> = {};
try { cache = JSON.parse(await Deno.readTextFile(cachePath)); } catch { cache = {}; }
const cacheMiss: string[] = [];
const expandMap = new Map<string, string[]>(set.questions.map((q: { question: string; expanded: string[] }) => [q.question, q.expanded]));

rag.testHooks.expand = (query: string) => {
  const e = noExpand ? [] : expandMap.get(query);
  if (!e) throw new Error('픽스처에 없는 질문: ' + query);
  return Promise.resolve(e.slice());
};
rag.testHooks.embed = async (query: string, model: string) => {
  const key = (model || 'voyage-4-lite') + '|' + query;
  if (cache[key]) return cache[key].slice();
  const apiKey = Deno.env.get('VOYAGE_API_KEY') || '';
  if (!apiKey) { console.warn('[임베딩 캐시 없음, VOYAGE_API_KEY도 없음]', key.slice(0, 60)); return null; }
  const res = await fetch('https://api.voyageai.com/v1/embeddings', {
    method: 'POST', headers: { 'Authorization': `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: model || 'voyage-4-lite', input: [query], input_type: 'query' }),
  });
  if (!res.ok) { console.warn('[Voyage 실패]', res.status); return null; }
  const data = await res.json();
  const emb = data.data?.[0]?.embedding || null;
  if (emb) { cache[key] = emb; cacheMiss.push(key); }
  return emb;
};

const sb = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_KEY')!);
if (deterministic) {
  // deno-lint-ignore no-explicit-any
  const anySb = sb as any;
  const origFrom = anySb.from.bind(anySb);
  anySb.from = (table: string) => {
    const qb = origFrom(table);
    if (table !== 'document_chunks') return qb;
    const origSelect = qb.select.bind(qb);
    qb.select = (...a: unknown[]) => {
      const fb = origSelect(...a);
      let ordered = false;
      const oOrder = fb.order.bind(fb), oLimit = fb.limit.bind(fb);
      fb.order = (...o: unknown[]) => { ordered = true; return oOrder(...o); };
      fb.limit = (n: number, o?: unknown) => { if (!ordered) { ordered = true; oOrder('id', { ascending: true }); } return oLimit(n, o); };
      return fb;
    };
    return qb;
  };
}
// 검색 단계 로그를 질문별로 붙잡는다(덧붙이기 항목 로그)
const origLog = console.log;
let logLines: string[] = [];
console.log = (...a: unknown[]) => {
  const s = a.map((x) => typeof x === 'string' ? x : JSON.stringify(x)).join(' ');
  if (/덧붙이기/.test(s)) logLines.push(s.slice(0, 400));
};

type Hit = { id?: number; doc_name?: string; article_no?: string; _named?: boolean; _ids?: number[]; content?: string };
const label = (h: Hit) => String(h.doc_name || '').split('(')[0].slice(0, 30) + ' ' + String(h.article_no || '').split('(')[0] + (h._named ? ' ★' : '');
const out = { tag, at: new Date().toISOString(), rag: ragPath.pathname, set: setPath.pathname, noExpand, deterministic, results: [] as Record<string, unknown>[], cacheMiss: [] as string[], totalMs: 0 };
for (const q of set.questions) {
  if (only && !only.has(q.id)) continue;
  logLines = [];
  const t0 = performance.now();
  let ctx: Record<string, unknown> | null = null, err: string | null = null;
  try { ctx = await rag.buildLawQueryContext(sb, q.question); } catch (e) { err = String((e as Error)?.message || e); }
  const ms = Math.round(performance.now() - t0);
  const merged = ((ctx?.merged as Hit[]) || []);
  const addOns = ctx?.addOns as { text: string; chunks: Hit[]; ids: number[]; items: unknown[]; trimmed?: number } | undefined;
  const sys = String(ctx?.system || '');
  const lawSec = sys.indexOf('[검색된 조문]');
  const addSec = sys.indexOf('[위임 관계로 이어진 조문') >= 0 ? sys.indexOf('[위임 관계로 이어진 조문') : -1;
  const kbSec = sys.indexOf('[법령 요약(');
  const lab: Record<string, string> = {};
  for (const c of merged.concat((addOns?.chunks as Hit[]) || [])) if (c && c.id != null) lab[String(c.id)] = label(c);
  out.results.push({
    id: q.id, question: q.question, ms, error: err, empty: ctx === null,
    merged: merged.map(label), mergedIds: merged.map((h) => h.id), named: merged.filter((h) => h._named).length,
    kb: ((ctx?.kb as { title?: string }[]) || []).slice(0, 3).map((r) => String(r.title || '').trim()),
    addItems: addOns?.items || [], addon: addOns?.ids || [], addonChunks: ((addOns?.chunks as Hit[]) || []).map(label),
    lens: { system: sys.length, law: lawSec >= 0 ? ((addSec >= 0 ? addSec : (kbSec >= 0 ? kbSec : sys.length)) - lawSec) : 0, addon: (addOns?.text || '').length, trimmed: addOns?.trimmed || 0 },
    meta: ((ctx?.searchMeta as { fn: string }[]) || []).filter((m) => m.fn === 'addons' || m.fn === 'law_delegations' || m.fn === 'search_law_articles_kw' || m.fn === 'pending_new'),
    // 시행 전 제정 법령 구역(#311-보론) — 붙은 법령·판정(named·kb·sim)·실은 조 수·지목 조·글자 수·조각 id
    pendingNew: (() => { const pn = ctx?.pendingNew as { text: string; ids: number[]; laws: unknown[]; gate: string | null } | undefined; return pn ? { gate: pn.gate, laws: pn.laws, len: (pn.text || '').length, ids: pn.ids } : null; })(),
    log: logLines.slice(), lab,
    ...(withText ? { sys } : {}),
  });
  origLog('[lawRegress]', q.id, ms + 'ms', 'merged', merged.length, 'addon', (addOns?.items || []).length, err || '');
}
console.log = origLog;
out.cacheMiss = cacheMiss;
out.totalMs = out.results.reduce((a, r) => a + (r.ms as number), 0);
// 전 문항 merged 0 = 검색이 조용히 실패한 것(세션 셸의 HTTPS_PROXY를 탄 Deno는 사내 프록시 인증서를 믿지 않아 Supabase·Voyage가 UnknownIssuer로
// 실패하고 호출측 catch가 빈 배열로 삼킨다 — 2026-10-14 첫 실행). `env -u HTTP_PROXY -u HTTPS_PROXY -u NO_PROXY`로 다시 돌릴 것.
if (out.results.length && out.results.every((r) => !(r.merged as string[]).length)) origLog('!! 모든 문항 merged 0 — 프록시(HTTPS_PROXY)·.env 키부터 확인(결과 파일은 쓰지만 비교에 쓰지 말 것)');
if (cacheMiss.length) await Deno.writeTextFile(cachePath, JSON.stringify(cache));
await Deno.mkdir(outDir, { recursive: true });
const stamp = new Date().toISOString().replace(/[-:]/g, '').slice(0, 15);
const outPath = new URL(`law_${tag}_${stamp}.json`, outDir);
await Deno.writeTextFile(outPath, JSON.stringify(out, null, 1));
origLog('[lawRegress] 저장:', outPath.pathname, '문항', out.results.length, '총', out.totalMs + 'ms', '임베딩 새로 받음', cacheMiss.length);
