// 자문 검색 회귀 하네스 — 텔레그램(rag.ts) 경로 (#201, 2026-09-24 B-2)
//
// 실행(저장소 루트, .env의 SUPABASE_URL·SUPABASE_SERVICE_KEY 사용; deno는 npm 패키지 `deno`로도 된다):
//   deno run --no-check --allow-net --allow-env --allow-read --allow-write tests/rag_regress_deno.ts --tag before [--only q01,q02] [--raw] [--rag <rag.ts 경로>]
// 출력: tests/fixtures/rag_regress_out/<tag>_<시각>.json (git 제외). 비교는 python tests/rag_regress_diff.py A.json B.json
//
// Haiku 확장은 픽스처의 고정 확장어, Voyage 임베딩은 tests/fixtures/rag_regress_embed_cache.json으로 바꿔 끼운다(rag.ts testHooks)
// → Anthropic API 0회. 캐시에 없는 텍스트만 Voyage를 직접 불러(VOYAGE_API_KEY) 캐시에 추가한다.
// ANTHROPIC_API_KEY는 더미('test')로 넣는다 — searchLawArticles가 키 유무로 확장 사용을 가르는데, 훅이 먼저 가로채므로 호출은 없다.
// 결정적 모드(기본): document_chunks 조회 중 order 없는 limit(키워드 ilike limit 4)에 order('id')를 붙여 임의 4건 잡음을 걷어낸다
// (브라우저 하네스와 같은 규칙). --raw 는 운영 그대로. --rag 는 비교용 사본 모듈(예: 변경 전 코드)을 대신 읽는다.
import { createClient } from 'jsr:@supabase/supabase-js@2';

const ROOT = new URL('../', import.meta.url);
const setPath = new URL('fixtures/rag_regression_set.json', ROOT + 'tests/');
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
const ragPath = argv('--rag') ? new URL(argv('--rag'), ROOT) : new URL('supabase/functions/_shared/rag.ts', ROOT);

const rag = await import(ragPath.href);
const set = JSON.parse(await Deno.readTextFile(setPath));
let cache: Record<string, number[]> = {};
try { cache = JSON.parse(await Deno.readTextFile(cachePath)); } catch { cache = {}; }
const cacheMiss: string[] = [];
const expandMap = new Map<string, string[]>(set.questions.map((q: { question: string; expanded: string[] }) => [q.question, q.expanded]));

// --expand-delay N : Haiku 확장의 실제 지연(1~2초)을 흉내 낸다 — 확장 대기와 trgm·시맨틱을 겹치는 효과(B-2)는 이 지연이 있어야 보인다
const expandDelay = Number(argv('--expand-delay') || 0);
rag.testHooks.expand = (query: string) => {
  const e = expandMap.get(query);
  if (!e) throw new Error('픽스처에 없는 질문: ' + query);
  if (!expandDelay) return Promise.resolve(e.slice());
  return new Promise<string[]>((res) => setTimeout(() => res(e.slice()), expandDelay));
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
// RPC 호출을 질문별로 기록한다(함수명·행수·오류코드·ms) — trgm이 statement_timeout(57014)으로 0건이 되는 fail-open 경로를
// 결과 차이의 원인으로 식별하기 위해. 2026-09-24 실측: 두 하네스를 동시에 돌리면 trgm 5~6초가 8초 한도를 넘겨 조용히 비었다.
let rpcLog: Record<string, unknown>[] = [];
{
  // deno-lint-ignore no-explicit-any
  const anySb = sb as any;
  const origRpc = anySb.rpc.bind(anySb);
  anySb.rpc = (fn: string, params?: unknown, opts?: unknown) => {
    const t0 = performance.now();
    const builder = origRpc(fn, params, opts);
    const origThen = builder.then.bind(builder);
    builder.then = (onOk?: (v: unknown) => unknown, onErr?: (e: unknown) => unknown) => origThen((r: { data?: unknown[]; error?: { code?: string; message?: string } }) => {
      rpcLog.push({ fn, ms: Math.round(performance.now() - t0), rows: Array.isArray(r?.data) ? r.data.length : null, error: r?.error ? (r.error.code || r.error.message) : null });
      return onOk ? onOk(r) : r;
    }, onErr);
    return builder;
  };
}
// 검색 단계 로그를 질문별로 붙잡는다(조문 보강·역참조 건수 — fail-open 경로가 0건으로 새는지)
const origLog = console.log;
let logLines: string[] = [];
console.log = (...a: unknown[]) => {
  const s = a.map((x) => typeof x === 'string' ? x : JSON.stringify(x)).join(' ');
  if (/\[조문 보강\]|\[역참조 발췌\]/.test(s)) logLines.push(s.slice(0, 300));
};

const ids = (list: { id?: unknown }[]) => (list || []).map((c) => c && c.id);
const out = { tag, at: new Date().toISOString(), rag: ragPath.pathname, deterministic, expandDelayMs: expandDelay, results: [] as Record<string, unknown>[], cacheMiss: [] as string[], totalMs: 0 };
for (const q of set.questions) {
  if (only && !only.has(q.id)) continue;
  logLines = []; rpcLog = [];
  const t0 = performance.now();
  let ctx: Record<string, unknown> = {}, err: string | null = null;
  try { ctx = await rag.buildAdvisoryContext(sb, q.question); } catch (e) { err = String((e as Error)?.message || e); }
  const ms = Math.round(performance.now() - t0);
  const annex = ctx.annex as { text: string; sources: string[] } | undefined;
  const citing = ctx.citing as { text: string; ids: number[] } | undefined;
  const news = ctx.news as { text: string; sources: string[] } | undefined;
  out.results.push({
    id: q.id, ms, error: err,
    rag: ids(ctx.chunks as []), extra: ids(ctx.extra as []), added: ctx.addedIds || [], citing: citing?.ids || [],
    annex: annex?.sources || [], kb: ((ctx.kb as { doc_id: string; chunk_idx: number }[]) || []).map((r) => r.doc_id + ':' + r.chunk_idx),
    news: news?.sources || [],
    lens: { law: String(ctx.lawContext || '').length, citing: (citing?.text || '').length, annex: (annex?.text || '').length,
            news: (news?.text || '').length, asm: String(ctx.asm || '').length, systemVariable: String(ctx.systemVariable || '').length },
    log: logLines.slice(), rpc: rpcLog.slice(),
  });
  origLog('[ragRegress]', q.id, ms + 'ms', err || '');
}
console.log = origLog;
out.cacheMiss = cacheMiss;
out.totalMs = out.results.reduce((a, r) => a + (r.ms as number), 0);
if (cacheMiss.length) await Deno.writeTextFile(cachePath, JSON.stringify(cache));
await Deno.mkdir(outDir, { recursive: true });
const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, '');
const outPath = new URL(`${tag}_${stamp}.json`, outDir);
await Deno.writeTextFile(outPath, JSON.stringify(out, null, 1));
console.log('[ragRegress] 저장:', outPath.pathname, '총', out.totalMs + 'ms', '캐시 추가', cacheMiss.length, deterministic ? '(결정적 모드)' : '(raw)');
