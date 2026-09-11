// ============================================================================
//  공용: Anthropic 호출 토큰 기록 + 경량 Haiku 호출 (#155, 2026-09-11)
//
//  Python 쪽은 api_usage.install()이 SDK를 감싸 모든 호출을 api_usage 표에 남기지만(#152),
//  Edge Function(텔레그램 /ask·대시보드 자문·claude-proxy)은 기록이 없어 자문 1건 비용을 추정만 했다.
//  응답에 이미 실려 오는 usage(스트리밍은 message_start 입력분 + message_delta 출력분)를 읽어
//  같은 표에 host='edge'로 남긴다. 추가 API 호출 없음. 기록 실패는 삼킨다(fail-open).
// ============================================================================
import type { SupabaseClient } from 'jsr:@supabase/supabase-js@2';

export const ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages';
export const HAIKU_MODEL = 'claude-haiku-4-5-20251001';

export interface ApiUsage {
  input_tokens?: number; output_tokens?: number;
  cache_creation_input_tokens?: number; cache_read_input_tokens?: number;
}
const USAGE_KEYS: (keyof ApiUsage)[] = ['input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'];

/** 스트림 이벤트의 usage를 누적 — message_delta.output_tokens는 누계라 '있으면 덮어쓴다' */
export function mergeUsage(a: ApiUsage, b: unknown): ApiUsage {
  const out: ApiUsage = { ...(a || {}) };
  if (!b || typeof b !== 'object') return out;
  const src = b as Record<string, unknown>;
  for (const k of USAGE_KEYS) if (typeof src[k] === 'number') out[k] = src[k] as number;
  return out;
}

export async function recordApiUsage(sb: SupabaseClient, site: string, model: string, usage: ApiUsage | null | undefined): Promise<void> {
  if (!usage || !USAGE_KEYS.some((k) => typeof usage[k] === 'number')) return;
  const n = (v: unknown) => (typeof v === 'number' && isFinite(v) ? Math.round(v) : 0);
  try {
    const { error } = await sb.from('api_usage').insert({
      host: 'edge', site: site.slice(0, 80), model,
      input_tokens: n(usage.input_tokens), cache_read: n(usage.cache_read_input_tokens),
      cache_write: n(usage.cache_creation_input_tokens), output_tokens: n(usage.output_tokens),
    });
    if (error) console.warn('[api_usage 기록 실패]', site, error.message);
  } catch (e) { console.warn('[api_usage 기록 실패]', site, e); }
}

/** 비스트리밍 Haiku 한 번 — 텍스트만 돌려주고 usage는 기록한다. 실패는 throw(호출측이 fail-open 결정). */
export async function callHaikuText(sb: SupabaseClient, apiKey: string, system: string, user: string, site: string, maxTokens = 900): Promise<string> {
  const res = await fetch(ANTHROPIC_URL, {
    method: 'POST',
    headers: { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
    body: JSON.stringify({ model: HAIKU_MODEL, max_tokens: maxTokens, system, messages: [{ role: 'user', content: user }] }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { error?: { message?: string } }).error?.message || `Anthropic HTTP ${res.status}`);
  }
  const data = await res.json() as { content?: { type: string; text?: string }[]; usage?: ApiUsage };
  await recordApiUsage(sb, site, HAIKU_MODEL, data.usage);
  return (data.content || []).find((b) => b.type === 'text')?.text || '';
}
