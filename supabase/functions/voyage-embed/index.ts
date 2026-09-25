// ============================================================================
//  Supabase Edge Function : voyage-embed
//  역할: 질문(텍스트)을 Voyage AI로 보내 1024차원 임베딩(숫자 배열)으로 변환.
//        대시보드 AI 자문(시맨틱 검색)이 호출합니다.
//  model 파라미터(하위호환): 미지정=voyage-4-lite(조문/document_chunks), 'voyage-law-2'(법령요약/kb_chunks).
// ============================================================================

import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const VOYAGE_API_KEY = Deno.env.get('VOYAGE_API_KEY');
const VOYAGE_URL = 'https://api.voyageai.com/v1/embeddings';
const ALLOWED_ORIGIN = Deno.env.get('ALLOWED_ORIGIN') || '*';

const corsHeaders = {
  'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
};

Deno.serve(async (req: Request) => {
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders });
  }

  try {
    if (!VOYAGE_API_KEY) {
      return new Response(
        JSON.stringify({ error: 'VOYAGE_API_KEY not configured' }),
        { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    const { query, model, input_type } = await req.json();
    if (!query || typeof query !== 'string') {
      return new Response(
        JSON.stringify({ error: 'query string is required' }),
        { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    const ALLOWED_MODELS = ['voyage-4-lite', 'voyage-law-2'];
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
      return new Response(
        JSON.stringify({ error: `Voyage API error: ${err}` }),
        { status: resp.status, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    const data = await resp.json();
    const embedding: number[] = data.data[0].embedding;

    return new Response(
      JSON.stringify({ embedding }),
      { headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );

  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return new Response(
      JSON.stringify({ error: msg }),
      { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }
});
