// ============================================================================
//  Supabase Edge Function : verify-citations  (대시보드 자문의 「[원문 확인됨]」 검증, #155)
//
//  대시보드 자문은 브라우저가 RAG를 조립해 claude-proxy로 스트리밍 받으므로, 답변이 끝난 뒤
//  브라우저가 답변 본문 + 근거 청크 id를 여기로 보낸다. 서버는 청크를 다시 읽어 조문을 통째로
//  붙이고(1안), 각 표시의 인용이 그 원문에 실제로 있는지 대조하며(2안), 있었으면 Haiku가
//  원문과 설명의 일치를 판정한다(3안). 텔레그램 /ask는 rag.ts answerAdvisory 안에서 같은
//  모듈(_shared/cite_verify.js)을 직접 돌린다 — 로직은 한 파일, 진입점만 둘.
//
//  인증·CORS는 claude-proxy와 같다(auth.getUser가 관문, verify_jwt는 게이트가 아님).
//  Haiku 1회가 들어가므로 'general' 백스톱(100/일·60/시간)에 1회로 센다.
//  Secrets: ANTHROPIC_API_KEY / SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY
// ============================================================================

import 'jsr:@supabase/functions-js/edge-runtime.d.ts';
import { createClient } from 'jsr:@supabase/supabase-js@2';
import '../_shared/cite_verify.js';
import { callHaikuText } from '../_shared/usage.ts';

// deno-lint-ignore no-explicit-any
const CiteVerify = (globalThis as any).CiteVerify;

const env = (k: string) => (Deno.env.get(k) || '').trim();
const ANTHROPIC_KEY = env('ANTHROPIC_API_KEY');

const ALLOWED_ORIGINS = [
  'https://radio-policy.gitlab.io',
  'https://radio-policy.github.io',
  'http://localhost:8000',
  'http://127.0.0.1:8000',
];
function corsHeaders(origin: string | null): Record<string, string> {
  const allow = origin && ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    'Access-Control-Allow-Origin': allow,
    'Access-Control-Allow-Headers': 'authorization, content-type',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Vary': 'Origin',
  };
}
function json(status: number, body: unknown, cors: Record<string, string>) {
  return new Response(JSON.stringify(body), { status, headers: { ...cors, 'content-type': 'application/json' } });
}

interface Row { id: number; doc_name: string; article_no?: string; chunk_index?: number; content: string }
// rag.ts fetchArticleChunks·app.js fetchArticleChunks와 동일 조건 — 한쪽만 고치지 말 것
const EXPAND_OPTS = { maxArticles: 10, maxChunksPerArticle: 4, maxAddedChunks: 14 };

Deno.serve(async (req) => {
  const cors = corsHeaders(req.headers.get('origin'));
  if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
  if (req.method !== 'POST') return json(405, { error: { type: 'method', message: 'POST만 허용됩니다.' } }, cors);

  const auth = req.headers.get('authorization') || '';
  const token = auth.toLowerCase().startsWith('bearer ') ? auth.slice(7).trim() : '';
  if (!token) return json(401, { error: { type: 'auth', message: '로그인이 필요합니다.' } }, cors);
  const sb = createClient(env('SUPABASE_URL'), env('SUPABASE_SERVICE_ROLE_KEY'));
  const { data: userData } = await sb.auth.getUser(token);
  const user = userData?.user;
  if (!user) return json(401, { error: { type: 'auth', message: '로그인이 필요합니다. 다시 로그인해 주세요.' } }, cors);

  let body: { answer?: string; chunk_ids?: unknown; annex_sources?: unknown };
  try { body = await req.json(); } catch { return json(400, { error: { type: 'bad_request', message: '요청 형식이 올바르지 않습니다.' } }, cors); }
  const answer = String(body.answer || '');
  if (!answer) return json(400, { error: { type: 'bad_request', message: 'answer 없음' } }, cors);
  const ids = (Array.isArray(body.chunk_ids) ? body.chunk_ids : []).filter((v): v is number => typeof v === 'number').slice(0, 80);
  const annexSources = (Array.isArray(body.annex_sources) ? body.annex_sources : []).map((s) => String(s)).slice(0, 10);

  // 표시도 근거도 없으면 할 일이 없다. 표시가 없어도 근거 청크가 있으면 통째 인용에 표시를 붙여 준다(#155-보론7).
  if (!/\[원문\s*확인됨[^\]]*\]/.test(answer) && !ids.length) return json(200, { answer, verdicts: [], changed: 0, skipped: 'no_tags' }, cors);

  // 승인·백스톱(Haiku 1회 = general 1회)
  const { data: charge, error: chargeErr } = await sb.rpc('charge_ai_usage', { p_user: user.id, p_kind: 'general' });
  if (chargeErr) return json(500, { error: { type: 'quota', message: '사용량 확인 중 오류가 발생했습니다.' } }, cors);
  const c = (charge ?? {}) as Record<string, unknown>;
  if (!c.ok) return json(c.reason === 'not_approved' ? 403 : 429, { error: { type: String(c.reason || 'quota'), message: '검증을 건너뜁니다(한도).' } }, cors);

  // 근거 청크 재조회 (브라우저가 본 것과 같은 id) + 조문 통째 보강
  let chunks: Row[] = [];
  if (ids.length) {
    const r = await sb.from('document_chunks').select('id, doc_name, article_no, chunk_index, content').in('id', ids);
    const byId = new Map<number, Row>((r.data || []).map((x: Row) => [x.id, x]));
    chunks = ids.map((id) => byId.get(id)).filter((x): x is Row => !!x);
  }
  const fetchArticle = async (docName: string, key: string): Promise<Row[]> => {
    const r = await sb.from('document_chunks').select('id, doc_name, article_no, chunk_index, content')
      .eq('doc_name', docName).eq('status', 'current').eq('is_approved', true)
      .like('article_no', key + '%').order('chunk_index', { ascending: true }).limit(40);
    return (r.data || []) as Row[];
  };
  try {
    const ex = await CiteVerify.expandArticles(chunks, fetchArticle, EXPAND_OPTS);
    chunks = ex.chunks;
  } catch (e) { console.warn('[조문 보강 실패]', e); }

  const { data: cfg } = await sb.from('app_config').select('value').eq('key', 'system_prompt').maybeSingle();
  const systemPrompt = (cfg?.value as string) || '';

  try {
    const vr = await CiteVerify.verifyCitations({
      answer, chunks, annexSources, systemPrompt,
      callHaiku: ANTHROPIC_KEY
        ? (sys: string, u: string) => callHaikuText(sb, ANTHROPIC_KEY, sys, u, 'verify-citations:citeJudge', 900)
        : null,
    });
    console.log('[인용 검증]', user.email || user.id, 'auto+' + (vr.autoTagged || 0), JSON.stringify(vr.verdicts.map((v: { key: string; status: string; reason: string }) => [v.key, v.status, v.reason])));
    return json(200, { answer: vr.answer, verdicts: vr.verdicts, changed: vr.changed, autoTagged: vr.autoTagged || 0 }, cors);
  } catch (e) {
    console.error('[인용 검증 실패]', e);
    return json(200, { answer, verdicts: [], changed: 0, error: String(e) }, cors);   // fail-open: 답변은 그대로
  }
});
