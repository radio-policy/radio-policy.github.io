// ============================================================================
//  Supabase Edge Function : voyage-embed
//  역할: 질문(텍스트)을 Voyage AI로 보내 1024차원 임베딩(숫자 배열)으로 변환.
//        대시보드 AI 자문(시맨틱 검색)·관리자 KB 임베딩 채우기가 호출합니다.
//  model 파라미터(하위호환): 미지정=voyage-4-lite(조문/document_chunks), 'voyage-law-2'(법령요약/kb_chunks).
//
//  관문(#29x, 2026-10-10 — 시스템 평가 보안 판정 Q5): 로그인 + 승인 계정만. 그전에는 공개 anon 키만으로
//  누구나 Voyage 요금을 쓸 수 있었다. verify_jwt=true 는 관문이 아니다(anon 키도 JWT) — 실제 관문은
//  아래 auth.getUser(token) + profiles.approved·active 이다. 이 검사를 제거하지 말 것.
//  텔레그램 rag.ts·Deno 회귀 하네스는 Voyage를 직접 부르므로 이 함수와 무관하다. 브라우저 회귀 하네스는
//  캐시에 없는 질문이면 이 함수를 부르므로 로그인한 미리보기 화면에서 돌린다.
//  Secrets: VOYAGE_API_KEY / SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY
// ============================================================================

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from 'jsr:@supabase/supabase-js@2';
import { corsHeaders } from '../_shared/http.ts';
import { recordApiUsage } from '../_shared/usage.ts';

// env는 반드시 trim — 콘솔에 붙여넣을 때 줄바꿈이 딸려 들어가면 인증이 조용히 어긋난다(#51)
const env = (k: string) => (Deno.env.get(k) || '').trim();

const VOYAGE_API_KEY = env('VOYAGE_API_KEY');
const VOYAGE_URL = 'https://api.voyageai.com/v1/embeddings';
const ALLOWED_MODELS = ['voyage-4-lite', 'voyage-law-2'];
// 길이 상한 — 관리자 임베딩 채우기가 document_chunks.content를 그대로 보낸다(실측 최대 6,771자, 2026-10-10)
const MAX_QUERY_CHARS = 8000;

Deno.serve(async (req: Request) => {
  // sb.functions.invoke는 apikey·x-client-info도 보낸다 — preflight에서 허용해야 한다
  const cors = corsHeaders(req.headers.get('origin'), ['apikey', 'x-client-info']);
  const json = (status: number, obj: unknown) =>
    new Response(JSON.stringify(obj), { status, headers: { ...cors, 'Content-Type': 'application/json' } });

  if (req.method === 'OPTIONS') return new Response('ok', { headers: cors });
  if (req.method !== 'POST') return json(405, { error: 'POST only' });

  try {
    if (!VOYAGE_API_KEY) return json(500, { error: 'VOYAGE_API_KEY not configured' });

    // ── 관문: 로그인(세션 토큰) + 승인·활성 계정 ──
    const auth = req.headers.get('authorization') || '';
    const token = auth.toLowerCase().startsWith('bearer ') ? auth.slice(7).trim() : '';
    if (!token) return json(401, { error: { type: 'auth', message: '로그인이 필요합니다.' } });
    const sb = createClient(env('SUPABASE_URL'), env('SUPABASE_SERVICE_ROLE_KEY'));
    const { data: userData } = await sb.auth.getUser(token);
    const user = userData?.user;
    // anon 키를 Bearer로 보내면 여기서 걸린다(user가 없다) — 이것이 실제 관문
    if (!user) return json(401, { error: { type: 'auth', message: '로그인이 필요합니다. 다시 로그인해 주세요.' } });
    const { data: prof } = await sb.from('profiles').select('approved, active').eq('user_id', user.id).maybeSingle();
    if (!prof || !prof.approved || prof.active === false) {
      return json(403, { error: { type: 'not_approved', message: 'AI 기능은 관리자 승인 후 이용할 수 있습니다. 승인 대기 중입니다.' } });
    }

    const { query, model, input_type } = await req.json();
    if (!query || typeof query !== 'string') return json(400, { error: 'query string is required' });
    if (query.length > MAX_QUERY_CHARS) return json(400, { error: `query too long (${query.length} > ${MAX_QUERY_CHARS})` });

    const useModel = ALLOWED_MODELS.includes(model) ? model : 'voyage-4-lite';

    const resp = await fetch(VOYAGE_URL, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${VOYAGE_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: useModel,
        input: [query],
        input_type: (input_type === 'document') ? 'document' : 'query',
      }),
    });

    if (!resp.ok) {
      const err = await resp.text();
      return json(resp.status, { error: `Voyage API error: ${err}` });
    }

    const data = await resp.json();
    const embedding: number[] = data.data[0].embedding;
    // 비용 기록(#211 비용 감시가 Voyage도 보게) — 기록 실패는 삼킨다
    await recordApiUsage(sb, 'voyage-embed:' + useModel, useModel, { input_tokens: data.usage?.total_tokens });

    return json(200, { embedding });

  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return json(500, { error: msg });
  }
});
