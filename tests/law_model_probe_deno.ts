// /law 자연어 모드 **답변 모델 비교 실측** (#304-보론, 2026-10-14 — 운영자 「세 모델 다 테스트, 저렴하고 결과가 좋으면 더 좋지」)
//
// 운영과 같은 검색 경로(rag.ts buildLawQueryContext — 확장어·임베딩 훅 없음 = Haiku 확장·Voyage 임베딩도 운영과 같음)로 문항마다
// 참조 자료(system)를 한 번 만들고, **같은 system·같은 질문**을 세 모델에 보내 답·usage·시간·stop_reason을 기록한다.
//   haiku45 = 운영 그대로(claude-haiku-4-5-20251001, max_tokens 3000)
//   sonnet5 = claude-sonnet-5, 추론 끔(뉴스 요약 #298·비스트리밍 관례), max_tokens 3000
//   haiku55 = claude-haiku-5-5, 적응형 추론 기본(effort medium), max_tokens 8000(추론 몫 포함 — #281 교훈)
// 기본은 **dry-run**(문항·arm·어림 비용만, API 0회). 실제 호출은 --allow-api(운영자 고지 뒤 — 18문항 × 3 ≈ $1.9).
// 실행(저장소 루트, 프록시 변수 벗고):
//   env -u HTTP_PROXY -u HTTPS_PROXY -u NO_PROXY npx --no-install deno run --no-check --allow-net --allow-env --allow-read --allow-write \
//     tests/law_model_probe_deno.ts [--allow-api] [--only l01,l02] [--arms haiku45,sonnet5,haiku55] [--set <질문 세트>] [--out <폴더>]
// 출력(--out, 기본 local_docs/law_probe_261014/model_ab/):
//   results_<시각>.json  문항 × arm 전부(답·usage·ms·stop_reason·비용)
//   blind_<시각>.md      눈가림 채점 파일 — 문항마다 세 답을 섞어 A/B/C로(모델 이름 없음), 「고르기」 줄
//   key_<시각>.json      A/B/C ↔ arm 열쇠(채점 끝난 뒤에 연다)
//   summary_<시각>.md    arm별 비용·시간·길이·잘림(답 없음)
// 호출마다 api_usage에 site 'law_model_probe:<arm>'으로 남긴다(비용 장부 — 21:30 워치독이 하루 비용 급증으로 한 번 경고할 수 있다).
import { createClient } from 'jsr:@supabase/supabase-js@2';
import { ANTHROPIC_URL, recordApiUsage, type ApiUsage } from '../supabase/functions/_shared/usage.ts';

const ROOT = new URL('../', import.meta.url);
const args = Deno.args;
const argv = (name: string) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : ''; };
const allowApi = args.includes('--allow-api');
const only = argv('--only') ? new Set(argv('--only').split(',')) : null;
const setPath = argv('--set') ? new URL(argv('--set'), ROOT) : new URL('tests/fixtures/law_regression_set.json', ROOT);
const outDir = new URL((argv('--out') || 'local_docs/law_probe_261014/model_ab/').replace(/\/?$/, '/'), ROOT);

function parseEnvFile(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$/);
    if (m) out[m[1]] = m[2].trim().replace(/^"(.*)"$/, '$1');
  }
  return out;
}
const dotenv = parseEnvFile(await Deno.readTextFile(new URL('.env', ROOT)).catch(() => ''));
for (const k of ['SUPABASE_URL', 'SUPABASE_SERVICE_KEY', 'VOYAGE_API_KEY', 'ANTHROPIC_API_KEY']) {
  if (!Deno.env.get(k) && dotenv[k]) Deno.env.set(k, dotenv[k]);
}

// arm 정의 — 단가는 claude-api 스킬 표(2026-10-06 갱신) $/MTok [입력, 출력]; haiku55는 10만 토큰 이하 프롬프트 단가
type Arm = { model: string; body: Record<string, unknown>; price: [number, number]; note: string };
const ARMS: Record<string, Arm> = {
  haiku45: { model: 'claude-haiku-4-5-20251001', body: { max_tokens: 3000 }, price: [1, 5], note: '운영 그대로' },
  sonnet5: { model: 'claude-sonnet-5', body: { max_tokens: 3000, thinking: { type: 'disabled' } }, price: [2, 10], note: '추론 끔' },
  haiku55: { model: 'claude-haiku-5-5', body: { max_tokens: 8000, output_config: { effort: 'medium' } }, price: [0.1, 0.5], note: '적응형 추론(medium)' },
};
const armNames = (argv('--arms') || 'haiku45,sonnet5,haiku55').split(',').filter((a) => ARMS[a]);
if (!armNames.length) throw new Error('--arms에 아는 arm이 없음: ' + Object.keys(ARMS).join(','));

const set = JSON.parse(await Deno.readTextFile(setPath));
const questions = (set.questions as { id: string; question: string }[]).filter((q) => !only || only.has(q.id));

// 어림 비용 — 입력 ≈22K(덧붙이기 포함 실측 평균 system 28K자 ≈ 21K 토큰 + 질문)·출력 ≈2.2K(haiku55는 추론 포함 ≈3K)
const estIn = 22000;
const est = armNames.map((a) => { const p = ARMS[a].price; const out = a === 'haiku55' ? 3000 : 2200; return [a, questions.length * (estIn * p[0] + out * p[1]) / 1e6] as const; });
console.log(`[모델 비교] 문항 ${questions.length} × arm ${armNames.join(',')} — 어림 비용 ` + est.map(([a, c]) => `${a} $${c.toFixed(2)}`).join(' · ') + ` = $${est.reduce((s, x) => s + x[1], 0).toFixed(2)}`);
if (!allowApi) { console.log('dry-run — 실제 호출은 --allow-api (운영자 고지 뒤)'); Deno.exit(0); }
const apiKey = Deno.env.get('ANTHROPIC_API_KEY') || '';
if (!apiKey) throw new Error('ANTHROPIC_API_KEY 없음(.env)');

const rag = await import(new URL('supabase/functions/_shared/rag.ts', ROOT).href);
const sb = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_KEY')!);

type ArmResult = { arm: string; model: string; answer: string; ms: number; stop_reason: string | null; usage: ApiUsage | null; cost: number; error: string | null; chars: number; cut: boolean };
async function callArm(arm: string, system: string, question: string): Promise<ArmResult> {
  const a = ARMS[arm];
  const t0 = performance.now();
  try {
    const res = await fetch(ANTHROPIC_URL, {
      method: 'POST',
      headers: { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
      body: JSON.stringify({ model: a.model, system, messages: [{ role: 'user', content: question }], ...a.body }),
    });
    const ms = Math.round(performance.now() - t0);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return { arm, model: a.model, answer: '', ms, stop_reason: null, usage: null, cost: 0, error: (err as { error?: { message?: string } }).error?.message || `HTTP ${res.status}`, chars: 0, cut: false };
    }
    const data = await res.json() as { content?: { type: string; text?: string }[]; usage?: ApiUsage; stop_reason?: string | null };
    await recordApiUsage(sb, 'law_model_probe:' + arm, a.model, data.usage);
    const text = (data.content || []).filter((b) => b.type === 'text').map((b) => b.text || '').join('\n').trim();
    const u = data.usage || null;
    const inTok = (u?.input_tokens || 0) + (u?.cache_read_input_tokens || 0) + (u?.cache_creation_input_tokens || 0);
    const cost = (inTok * a.price[0] + (u?.output_tokens || 0) * a.price[1]) / 1e6;
    return { arm, model: a.model, answer: text, ms, stop_reason: data.stop_reason ?? null, usage: u, cost, error: null, chars: text.length, cut: data.stop_reason === 'max_tokens' };
  } catch (e) {
    return { arm, model: a.model, answer: '', ms: Math.round(performance.now() - t0), stop_reason: null, usage: null, cost: 0, error: String((e as Error)?.message || e), chars: 0, cut: false };
  }
}

// 문항별 고정 섞기(열쇠 재현용) — id 글자 합으로 시드
function shuffled<T>(items: T[], seed: string): T[] {
  let h = 2166136261; for (const ch of seed) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619) >>> 0; }
  const out = items.slice();
  for (let i = out.length - 1; i > 0; i--) { h = (Math.imul(h, 1103515245) + 12345) >>> 0; const j = h % (i + 1); [out[i], out[j]] = [out[j], out[i]]; }
  return out;
}

await Deno.mkdir(outDir, { recursive: true });
const stamp = new Date().toISOString().replace(/[-:]/g, '').slice(0, 15);
const results: Record<string, unknown>[] = [];
const blind: string[] = [`# /law 답변 눈가림 채점 — ${stamp} (문항 ${questions.length}, 답 ${armNames.length}개씩, 모델 이름 없음)\n\n문항마다 가장 나은 답 하나(동률이면 둘)를 「고르기」 줄에 적고, 틀린 내용이 있으면 「틀림」 줄에 적어 주세요. 열쇠는 key_${stamp}.json(채점 뒤에).\n`];
const key: Record<string, Record<string, string>> = {};
for (const q of questions) {
  const t0 = performance.now();
  let ctx: { system: string; merged: unknown[]; addOns?: { items: unknown[] } } | null = null; let ctxErr: string | null = null;
  try { ctx = await rag.buildLawQueryContext(sb, q.question); } catch (e) { ctxErr = String((e as Error)?.message || e); }
  const ctxMs = Math.round(performance.now() - t0);
  if (!ctx) {
    results.push({ id: q.id, question: q.question, ctxMs, error: ctxErr || '검색 0건', arms: [] });
    console.log(`[모델 비교] ${q.id} 참조 자료 없음(${ctxErr || '검색 0건'})`);
    continue;
  }
  const arms = await Promise.all(armNames.map((a) => callArm(a, ctx!.system, q.question)));
  results.push({ id: q.id, question: q.question, ctxMs, systemChars: ctx.system.length, merged: ctx.merged.length, addItems: ctx.addOns?.items?.length || 0, arms });
  const order = shuffled(armNames, q.id + stamp);
  const labels = ['A', 'B', 'C', 'D'];
  key[q.id] = {};
  blind.push(`\n---\n\n## ${q.id}. ${q.question}\n`);
  order.forEach((a, i) => {
    const r = arms.find((x) => x.arm === a)!;
    key[q.id][labels[i]] = a;
    blind.push(`### 답 ${labels[i]}${r.cut ? ' (길이 상한에서 잘림)' : ''}${r.error ? ' (오류: ' + r.error + ')' : ''}\n\n${r.answer || '(없음)'}\n`);
  });
  blind.push(`**고르기(${q.id}):** \n**틀림(${q.id}):** \n`);
  console.log(`[모델 비교] ${q.id} 자료 ${ctxMs}ms · ` + arms.map((r) => `${r.arm} ${r.ms}ms ${r.chars}자${r.cut ? ' 잘림' : ''}${r.error ? ' 오류' : ''} $${r.cost.toFixed(3)}`).join(' · '));
}
await Deno.writeTextFile(new URL(`results_${stamp}.json`, outDir), JSON.stringify({ stamp, set: setPath.pathname, arms: armNames.map((a) => ({ arm: a, ...ARMS[a] })), results }, null, 1));
await Deno.writeTextFile(new URL(`blind_${stamp}.md`, outDir), blind.join('\n'));
await Deno.writeTextFile(new URL(`key_${stamp}.json`, outDir), JSON.stringify(key, null, 1));
// 요약 — arm별 합계·평균(답 없음)
const lines = [`# 모델 비교 요약 — ${stamp}\n`, '| arm | 모델 | 설정 | 문항 | 비용 합 | 1건 평균 | 응답 평균 ms | 답 길이 평균 | 잘림 | 오류 | 출력 토큰 평균 |', '|---|---|---|---|---|---|---|---|---|---|---|'];
for (const a of armNames) {
  const rs = results.flatMap((r) => ((r.arms as ArmResult[]) || []).filter((x) => x.arm === a));
  const ok = rs.filter((x) => !x.error);
  const avg = (f: (x: ArmResult) => number) => ok.length ? Math.round(ok.reduce((s, x) => s + f(x), 0) / ok.length) : 0;
  lines.push(`| ${a} | ${ARMS[a].model} | ${ARMS[a].note} | ${rs.length} | $${rs.reduce((s, x) => s + x.cost, 0).toFixed(3)} | $${(ok.length ? rs.reduce((s, x) => s + x.cost, 0) / ok.length : 0).toFixed(4)} | ${avg((x) => x.ms)} | ${avg((x) => x.chars)}자 | ${rs.filter((x) => x.cut).length} | ${rs.filter((x) => x.error).length} | ${avg((x) => x.usage?.output_tokens || 0)} |`);
}
await Deno.writeTextFile(new URL(`summary_${stamp}.md`, outDir), lines.join('\n') + '\n');
console.log(lines.join('\n'));
console.log('[모델 비교] 저장:', outDir.pathname, stamp);
