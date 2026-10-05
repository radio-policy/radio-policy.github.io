// ============================================================================
//  공용: 인용 2차 판정기 호출 (2026-10-05) — rag.ts(텔레그램 /ask)·verify-citations(대시보드)가 같은 요청을 보낸다.
//
//  1차 판정(Haiku, usage.ts callHaikuText)이 「불일치」라 한 인용만 cite_verify.js judgeCitations2가 이 함수로 다시 판정한다.
//  모델·요청 값은 cite_verify.js의 JUDGE2_MODEL·JUDGE2_REQUEST·JUDGE2_MAX_TOKENS 한 곳(실측 도구 tests/cite_judge_probe.js와 공유).
//  usage.ts에 두지 않은 이유: 그 파일을 고치면 이 호출과 무관한 claude-proxy·assembly-search까지 재배포 대상이 된다.
//  거절(refusal)·HTTP 실패는 throw — 호출측(verifyCitations)이 회색('2차 판정 실패')으로 떨어뜨린다(주황으로 두지 않는다).
// ============================================================================
import type { SupabaseClient } from 'jsr:@supabase/supabase-js@2';
import { ANTHROPIC_URL, recordApiUsage, type ApiUsage } from './usage.ts';
import './cite_verify.js';

// deno-lint-ignore no-explicit-any
const CiteVerify = (globalThis as any).CiteVerify;

export async function callCiteJudge2(sb: SupabaseClient, apiKey: string, system: string, user: string, site: string): Promise<string> {
  const model = CiteVerify.JUDGE2_MODEL as string;
  const res = await fetch(ANTHROPIC_URL, {
    method: 'POST',
    headers: { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
    body: JSON.stringify({ model, max_tokens: CiteVerify.JUDGE2_MAX_TOKENS, ...CiteVerify.JUDGE2_REQUEST, system, messages: [{ role: 'user', content: user }] }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { error?: { message?: string } }).error?.message || `Anthropic HTTP ${res.status}`);
  }
  const data = await res.json() as { content?: { type: string; text?: string }[]; usage?: ApiUsage; stop_reason?: string };
  await recordApiUsage(sb, site, model, data.usage);
  if (data.stop_reason === 'refusal') throw new Error('2차 판정기 거절(refusal)');
  if (data.stop_reason === 'max_tokens') console.warn(`[callCiteJudge2] 출력이 max_tokens에 잘림 — site=${site}`);
  // 추론 블록이 앞에 올 수 있다(모델을 바꿀 때) — text 블록을 찾아 읽는다
  return (data.content || []).find((b) => b.type === 'text')?.text || '';
}
