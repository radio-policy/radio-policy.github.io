// ============================================================================
//  Supabase Edge Function : assembly-search
//
//  역할: 대시보드(과방위 회의록 탭)의 "국회 발언 원문 검색" 백엔드.
//   브라우저에서 record.assembly.go.kr 를 직접 호출하면 CORS 로 막힌다 —
//   국회 사이트는 Access-Control-Allow-Origin 을 주지 않는다. 그래서 이 함수가 중계한다.
//
//  검색·파싱 로직은 갖고 있지 않다. 전부 _shared/assembly_search.ts 를 쓴다 —
//  텔레그램 assem 명령과 **같은 코드**여야 같은 질문에 같은 답이 나온다(배경역사 #88·#92).
//
//  요청 (POST JSON):
//    { "text": "2019년 국정감사에서 김성수 의원이 무선국 관련 발언 찾아줘", "limit": 10 }
//    또는 파싱 없이 직접 지정: { "speaker": "김성수", "query": "무선국", "year": 2019,
//                              "kinds": ["국정감사"], "limit": 10 }
//  응답: { total, hits: [...], parsed: {...}, stored: { total, hits: [...] } | null }
//    - hits: 국회회의록시스템 실시간 원문(snippet 에는 <!HS>…<!HE> 마커가 남아 있다)
//    - stored: 정리해 둔 발언(assembly_speeches 요지) — 첫 페이지(offset 0)에만 붙는다. 두 단 검색(#132).
//      DB 조회 실패는 null 로 내려가고 원문 검색은 그대로 간다(fail-open).
//
//  Secrets: ANTHROPIC_API_KEY (자연어 파싱 보조용 — 없어도 규칙 파서로 동작한다)
//           SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (런타임 자동 주입 — 1단 DB 조회용)
// ============================================================================

import 'jsr:@supabase/functions-js/edge-runtime.d.ts';
import { createClient } from 'jsr:@supabase/supabase-js@2';
import {
  parseAssemQuery, searchAssemblyWithFallback, attachContext, searchStoredSpeeches,
  type AssemKind, type AssemQuery, type AssemStoredResult,
} from '../_shared/assembly_search.ts';

const env = (k: string) => (Deno.env.get(k) || '').trim();
const sb = createClient(env('SUPABASE_URL'), env('SUPABASE_SERVICE_ROLE_KEY'));
const STORED_MAX = 30;   // 1단 표시 상한 — 대시보드는 표로 펼치므로 텔레그램(20)보다 넉넉히

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};

const MAX_LIMIT = 20;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status, headers: { ...CORS, 'Content-Type': 'application/json; charset=utf-8' },
  });
}

Deno.serve(async (req: Request) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  if (req.method !== 'POST') return json({ error: 'POST only' }, 405);

  let body: {
    text?: string; speaker?: string; query?: string; year?: number;
    kinds?: string[]; limit?: number; context?: boolean; offset?: number;
    stored?: boolean;   // false 면 1단(정리해 둔 발언) 생략
  };
  try { body = await req.json(); } catch { return json({ error: 'bad json' }, 400); }

  const limit = Math.min(Math.max(Number(body.limit) || 10, 1), MAX_LIMIT);

  try {
    let q: AssemQuery;
    if (body.query) {
      // 필드를 직접 준 경우 — 파싱하지 않는다(대시보드의 '발언자/검색어' 분리 입력).
      q = {
        speaker: (body.speaker || '').trim(),
        query: body.query.trim(),
        year: body.year || undefined,
        kinds: (body.kinds || []).filter(
          (k): k is AssemKind => k === '상임위' || k === '국정감사') as AssemKind[],
      };
      if (!q.kinds?.length) q.kinds = undefined;
    } else {
      q = await parseAssemQuery(body.text || '', Deno.env.get('ANTHROPIC_API_KEY') || '');
      if (!q.query) {
        return json({ total: 0, hits: [], parsed: q, notice: '찾을 낱말을 알아내지 못했습니다.' });
      }
    }
    const offset = Math.max(0, Number(body.offset) || 0);
    // 1단(정리해 둔 발언)은 첫 페이지에만, 2단(국회 원문)과 **동시에** 시작한다 — DB는 0.2초, 국회는 수 초.
    const storedP: Promise<AssemStoredResult | null> = offset === 0 && body.stored !== false
      ? searchStoredSpeeches(sb, q, STORED_MAX).catch((e) => {
          console.error('[1단 DB 조회 실패(무시)]', String((e as Error)?.message ?? e).slice(0, 120));
          return null;
        })
      : Promise.resolve(null);

    let result;
    try {
      result = await searchAssemblyWithFallback(q, limit, 20_000, offset);
    } catch (e) {
      // 국회 사이트 장애 — 1단이 있으면 그것만이라도 돌려준다(종전엔 502 한 줄).
      const stored = await storedP;
      if (stored && stored.hits.length) {
        return json({ total: 0, hits: [], parsed: q, stored,
                      notice: '국회회의록시스템 조회에 실패해 정리해 둔 발언만 보여드립니다.' });
      }
      throw e;
    }
    let stored = await storedP;
    // 2단이 재시도로 해석을 바꿨는데 1단이 원래 해석으로 0건이면, 바뀐 해석으로 1단도 다시 찾는다.
    if (stored && !stored.hits.length && result.retried) {
      stored = await searchStoredSpeeches(sb, result.parsed, STORED_MAX).catch(() => stored);
    }
    // 상위 1건에는 뷰어 원문을 붙여 **발언 전문 + 정부측 답변**까지 보여준다(실측 +2.4초, AI 비용 0).
    // 검색 스니펫만 주면 206자에서 잘리고 답변이 빠져 "무엇이라 답했나"를 알 수 없다.
    if (body.context !== false) await attachContext(result, 1, 2, 4, 1200);
    return json({ ...result, stored });
  } catch (e) {
    console.error('[assembly-search 실패]', e);
    return json({ error: String((e as Error)?.message ?? e).slice(0, 200) }, 502);
  }
});
