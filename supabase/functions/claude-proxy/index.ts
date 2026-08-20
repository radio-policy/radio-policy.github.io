// ============================================================================
//  Supabase Edge Function : claude-proxy  (대시보드 AI 기능 인증 프록시)
//
//  역할: 대시보드의 모든 Anthropic 호출(14곳)을 대신 수행한다.
//   - 종전에는 브라우저가 api.anthropic.com을 직접 불렀고, 키는 app_config에서
//     anon으로 읽어왔다 → **인터넷 누구나 DB에서 키를 꺼내 갈 수 있었다.**
//     이제 키는 Edge Secret(ANTHROPIC_API_KEY)에만 있고 밖으로 나가지 않는다.
//   - 로그인(Supabase Auth) + 관리자 승인(profiles.approved)을 통과해야 호출된다.
//   - 자문은 개인·팀 일일 한도로 차감된다(charge_ai_usage).
//
//  ★ verify_jwt는 게이트가 아니다 — 켜도 **anon 키를 유효한 JWT로 통과**시킨다.
//    실제 관문은 아래 auth.getUser(token)이다. 이 검사를 제거하지 말 것.
//
//  ★ 한도 판별은 body.stream 플래그다(서버가 관찰하는 값 → 위조 불가).
//    스트리밍 = 자문·보고서초안(비용 큰 Sonnet 장문) → 'advisory' 한도 차감.
//    비스트리밍 = 뉴스요약·용어추출 등 경량 호출 → 한도 없음, 남용 백스톱만.
//    클라이언트가 보내는 헤더로 판별하도록 바꾸면 위조로 한도를 우회할 수 있다.
//
//  ★ 스트리밍은 TransformStream + EdgeRuntime.waitUntil(pipeTo) 형태여야 한다.
//    `new Response(upstream.body)` 만 반환하면 런타임이 함수를 조기 종료(EarlyDrop)해
//    긴 답변이 중간에 끊긴다. (자문은 45초~2분, 유료 플랜 상한 400초)
//
//  Secrets: ANTHROPIC_API_KEY / SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY
// ============================================================================

import 'jsr:@supabase/functions-js/edge-runtime.d.ts';
import { createClient } from 'jsr:@supabase/supabase-js@2';

// env는 반드시 trim — 콘솔에 붙여넣을 때 줄바꿈이 딸려 들어가면 인증이 조용히 어긋난다(#51)
const env = (k: string) => (Deno.env.get(k) || '').trim();

const ANTHROPIC_KEY = env('ANTHROPIC_API_KEY');
const ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages';

// 대시보드 정본(GitLab Pages) + 로컬 검증용. 그 외 출처는 CORS로 막는다.
const ALLOWED_ORIGINS = [
  'https://radio-policy.gitlab.io',
  'http://localhost:8000',
  'http://127.0.0.1:8000',
];
// 모델 화이트리스트 — 임의 모델·초장문 요청으로 비용이 튀는 것을 막는다
const ALLOWED_MODELS = ['claude-sonnet-5', 'claude-haiku-4-5-20251001'];
const MAX_TOKENS_CAP = 32000;

function corsHeaders(origin: string | null): Record<string, string> {
  const allow = origin && ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    'Access-Control-Allow-Origin': allow,
    'Access-Control-Allow-Headers': 'authorization, content-type',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Vary': 'Origin',
  };
}

/** 대시보드는 Anthropic 오류 형식(err.error.message)을 그대로 화면에 띄운다 — 같은 모양으로 돌려준다. */
function errJson(status: number, type: string, message: string, cors: Record<string, string>) {
  return new Response(JSON.stringify({ error: { type, message } }), {
    status,
    headers: { ...cors, 'content-type': 'application/json' },
  });
}

Deno.serve(async (req) => {
  const cors = corsHeaders(req.headers.get('origin'));
  if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
  if (req.method !== 'POST') return errJson(405, 'method', 'POST만 허용됩니다.', cors);
  if (!ANTHROPIC_KEY) return errJson(500, 'config', 'ANTHROPIC_API_KEY 미설정', cors);

  // ── ① 인증 ──
  const auth = req.headers.get('authorization') || '';
  const token = auth.toLowerCase().startsWith('bearer ') ? auth.slice(7).trim() : '';
  if (!token) return errJson(401, 'auth', '로그인이 필요합니다.', cors);

  const sb = createClient(env('SUPABASE_URL'), env('SUPABASE_SERVICE_ROLE_KEY'));
  const { data: userData } = await sb.auth.getUser(token);
  const user = userData?.user;
  // anon 키를 Bearer로 보내면 여기서 걸린다(user가 없다) — 이것이 실제 관문
  if (!user) return errJson(401, 'auth', '로그인이 필요합니다. 다시 로그인해 주세요.', cors);

  // ── ② 요청 검증 ──
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return errJson(400, 'bad_request', '요청 형식이 올바르지 않습니다.', cors);
  }
  const model = String(body.model || '');
  if (!ALLOWED_MODELS.includes(model)) {
    return errJson(400, 'model', `허용되지 않은 모델입니다: ${model}`, cors);
  }
  if (Number(body.max_tokens || 0) > MAX_TOKENS_CAP) {
    return errJson(400, 'max_tokens', `max_tokens 상한(${MAX_TOKENS_CAP})을 넘었습니다.`, cors);
  }

  // ── ③ 승인 확인 + 한도 차감 (선차감: 동시 요청이 한도를 함께 넘는 것 방지) ──
  const kind = body.stream === true ? 'advisory' : 'general';
  const { data: charge, error: chargeErr } = await sb.rpc('charge_ai_usage', {
    p_user: user.id,
    p_kind: kind,
  });
  if (chargeErr) {
    console.error('[한도 차감 실패]', chargeErr);
    return errJson(500, 'quota', '사용량 확인 중 오류가 발생했습니다.', cors);
  }
  const c = (charge ?? {}) as Record<string, unknown>;
  if (!c.ok) {
    const reason = String(c.reason || '');
    if (reason === 'not_approved') {
      return errJson(403, 'not_approved',
        'AI 기능은 관리자 승인 후 이용할 수 있습니다. 승인 대기 중입니다.', cors);
    }
    if (reason === 'member_limit') {
      return errJson(429, 'quota',
        `오늘 자문 한도(${c.limit}회)를 모두 사용했습니다. 내일 다시 이용해 주세요.`, cors);
    }
    if (reason === 'team_limit') {
      return errJson(429, 'quota',
        `${c.team_name ?? '팀'}의 오늘 자문 한도(${c.team_limit}회)를 모두 사용했습니다. ` +
        '내일 다시 이용하거나 관리자에게 한도 조정을 요청해 주세요.', cors);
    }
    return errJson(429, 'quota', '오늘 이용 한도를 초과했습니다.', cors);
  }

  // ── ④ Anthropic 호출 — body를 그대로 전달 ──
  // cache_control(프롬프트 캐싱)·tools(web_search)·thinking 설정이 손실 없이 넘어가야 한다.
  let upstream: Response;
  try {
    upstream = await fetch(ANTHROPIC_URL, {
      method: 'POST',
      headers: {
        'x-api-key': ANTHROPIC_KEY,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
      },
      body: JSON.stringify(body),
    });
  } catch (e) {
    console.error('[Anthropic 연결 실패]', e);
    await sb.rpc('refund_ai_usage', { p_user: user.id, p_kind: kind });
    return errJson(502, 'upstream', 'AI 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.', cors);
  }

  // 한 바이트도 받지 못한 실패만 환불한다. 스트림 중간 끊김은 환불하지 않는다
  // — 비용은 이미 발생했고, 중단을 반복해 한도를 우회하는 길이 되기 때문(텔레그램 선례와 동일).
  if (!upstream.ok) {
    const text = await upstream.text();
    await sb.rpc('refund_ai_usage', { p_user: user.id, p_kind: kind });
    console.error('[Anthropic 오류]', upstream.status, text.slice(0, 300));
    return new Response(text, {
      status: upstream.status,
      headers: { ...cors, 'content-type': 'application/json' },
    });
  }

  // ── ⑤ 응답 전달 ──
  if (body.stream === true && upstream.body) {
    // 바이트를 그대로 흘려보낸다 → 브라우저의 기존 SSE 파서가 한 줄도 바뀌지 않는다.
    const { readable, writable } = new TransformStream();
    // waitUntil로 붙잡지 않으면 응답 반환 시점에 런타임이 함수를 정리해 스트림이 끊긴다
    EdgeRuntime.waitUntil(
      upstream.body.pipeTo(writable).catch((e) => console.error('[스트림 중단]', e)),
    );
    return new Response(readable, {
      headers: {
        ...cors,
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      },
    });
  }

  return new Response(upstream.body, {
    status: 200,
    headers: { ...cors, 'content-type': 'application/json' },
  });
});
