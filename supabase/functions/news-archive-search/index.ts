// ============================================================================
//  Supabase Edge Function : news-archive-search  (이슈맵 — 과거 뉴스 외부 재수집)
//
//  왜 필요한가: news_feed는 60일 롤링이라 그 이전 보도가 DB에 없다. 이슈를 만들어도
//  "작년에 정부 관계자가 뭐라고 했는지" 같은 경과가 통째로 비어 있다.
//  그래서 이슈 승인/보강 시 네이버·구글에서 과거 기사를 다시 찾아 이슈에 붙인다.
//
//  ★ 연결 여부는 운영자가 고르지 않고 Haiku가 판정한다(운영자 지시 2026-08-26).
//    다만 오연결이 이슈를 오염시키므로 ① 1회 상한 ② 제외 목록 반환(감사) ③ 운영자 연결 해제
//    세 가지 안전장치를 둔다.
//
//  ★ 연결된 기사는 locked=true — 60일 정리(refetch_content.py)에서 빠져 영구 보관된다.
//    이슈맵이 곧 뉴스 아카이브의 보존 기준이 된다.
//
//  ★ 운영자가 대시보드에서 지운 기사(deleted_news)는 다시 끌어오지 않는다.
//    크롤러가 지키는 규약을 여기서 깨면 지운 기사가 이슈로 되살아난다.
//
//  Secrets: ANTHROPIC_API_KEY / NAVER_CLIENT_ID / NAVER_CLIENT_SECRET
//           SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY
// ============================================================================

import 'jsr:@supabase/functions-js/edge-runtime.d.ts';
import { createClient } from 'jsr:@supabase/supabase-js@2';

const env = (k: string) => (Deno.env.get(k) || '').trim();

const ANTHROPIC_KEY = env('ANTHROPIC_API_KEY');
const NAVER_ID = env('NAVER_CLIENT_ID');
const NAVER_SECRET = env('NAVER_CLIENT_SECRET');

// claude-proxy와 같은 목록을 유지한다 — 한쪽만 고치면 그 주소에서 기능이 조용히 죽는다
const ALLOWED_ORIGINS = [
  'https://radio-policy.gitlab.io',
  'https://youjinwoong.github.io',
  'http://localhost:8000',
  'http://127.0.0.1:8000',
];

const MAX_LINK = 30;        // 1회 보강당 연결 상한
const MAX_CANDIDATES = 120; // 판정에 넘길 후보 상한(토큰·시간 통제)

function corsHeaders(origin: string | null): Record<string, string> {
  const allow = origin && ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    'Access-Control-Allow-Origin': allow,
    'Access-Control-Allow-Headers': 'authorization, content-type',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Vary': 'Origin',
  };
}

function errJson(status: number, message: string, cors: Record<string, string>) {
  return new Response(JSON.stringify({ error: { message } }), {
    status, headers: { ...cors, 'content-type': 'application/json' },
  });
}

const stripTags = (s: string) =>
  String(s || '').replace(/<[^>]*>/g, '')
    .replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>').replace(/&#39;/g, "'").replace(/&apos;/g, "'").trim();

/** 추적 파라미터·프로토콜 차이로 같은 기사가 중복되는 것을 막는 정규화 키 */
function urlKey(u: string): string {
  try {
    const x = new URL(u);
    x.hash = '';
    ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'ref', 'oc']
      .forEach((p) => x.searchParams.delete(p));
    return (x.host.replace(/^www\./, '') + x.pathname.replace(/\/$/, '') + x.search).toLowerCase();
  } catch {
    return String(u || '').toLowerCase();
  }
}

type Cand = { title: string; url: string; date: string | null; source: string; desc: string };

async function searchNaver(query: string, sort: 'sim' | 'date'): Promise<Cand[]> {
  if (!NAVER_ID || !NAVER_SECRET) return [];
  try {
    const r = await fetch(
      `https://openapi.naver.com/v1/search/news.json?query=${encodeURIComponent(query)}&display=50&sort=${sort}`,
      { headers: { 'X-Naver-Client-Id': NAVER_ID, 'X-Naver-Client-Secret': NAVER_SECRET } },
    );
    if (!r.ok) return [];
    const j = await r.json();
    return (j.items || []).map((a: Record<string, string>) => {
      const link = a.link || '';
      const origin = a.originallink || '';
      const href = link.includes('naver.com') ? link : (origin || link);
      let date: string | null = null;
      if (a.pubDate) {
        const d = new Date(a.pubDate);
        if (!isNaN(d.getTime())) date = d.toISOString().slice(0, 10);
      }
      let host = '';
      try { host = new URL(origin || href).host.replace(/^www\./, ''); } catch { /* 무시 */ }
      return { title: stripTags(a.title), url: href, date, source: host || '네이버뉴스', desc: stripTags(a.description) };
    }).filter((c: Cand) => c.title && c.url);
  } catch {
    return [];
  }
}

/** 구글 뉴스 RSS — 네이버에 없는 기간 지정(after:/before:)이 있어 옛 기사를 정조준할 수 있다 */
async function searchGoogle(query: string, after?: string, before?: string): Promise<Cand[]> {
  try {
    const q = query + (after ? ` after:${after}` : '') + (before ? ` before:${before}` : '');
    const r = await fetch(
      `https://news.google.com/rss/search?q=${encodeURIComponent(q)}&hl=ko&gl=KR&ceid=KR:ko`,
      { headers: { 'user-agent': 'Mozilla/5.0 (compatible; radio-policy-ai/1.0)' } },
    );
    if (!r.ok) return [];
    const xml = await r.text();
    const out: Cand[] = [];
    // Deno에 DOMParser가 없어 정규식으로 뽑는다 — 항목 구조가 단순해 충분하다
    const items = xml.split('<item>').slice(1);
    for (const it of items) {
      const t = it.match(/<title>([\s\S]*?)<\/title>/);
      const l = it.match(/<link>([\s\S]*?)<\/link>/);
      const p = it.match(/<pubDate>([\s\S]*?)<\/pubDate>/);
      const s = it.match(/<source[^>]*>([\s\S]*?)<\/source>/);
      if (!t || !l) continue;
      let date: string | null = null;
      if (p) { const d = new Date(stripTags(p[1])); if (!isNaN(d.getTime())) date = d.toISOString().slice(0, 10); }
      out.push({
        title: stripTags(t[1]).replace(/\s*-\s*[^-]{2,20}$/, ''),   // 구글은 제목 끝에 매체명을 붙인다
        url: stripTags(l[1]), date, source: s ? stripTags(s[1]) : '구글뉴스', desc: '',
      });
    }
    return out.filter((c) => c.title && c.url);
  } catch {
    return [];
  }
}

Deno.serve(async (req) => {
  const cors = corsHeaders(req.headers.get('origin'));
  if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
  if (req.method !== 'POST') return errJson(405, 'POST만 허용됩니다.', cors);

  // ── 인증: 로그인 + 승인된 계정만 (DB에 쓰는 작업이다) ──
  const auth = req.headers.get('authorization') || '';
  const token = auth.toLowerCase().startsWith('bearer ') ? auth.slice(7).trim() : '';
  if (!token) return errJson(401, '로그인이 필요합니다.', cors);

  const sb = createClient(env('SUPABASE_URL'), env('SUPABASE_SERVICE_ROLE_KEY'));
  // 내부 호출(operator-webhook의 승인 파이프)은 service-role 키를 Bearer로 보낸다 —
  // 이 키는 서버에만 있으므로 사용자 검증을 갈음한다. 그 외에는 로그인+승인 필수.
  if (token !== env('SUPABASE_SERVICE_ROLE_KEY')) {
    const { data: userData } = await sb.auth.getUser(token);
    const user = userData?.user;
    if (!user) return errJson(401, '로그인이 필요합니다. 다시 로그인해 주세요.', cors);
    // profiles의 기본키는 id가 아니라 user_id다 — id로 조회하면 컬럼 없음 오류가 난다
    const { data: prof } = await sb.from('profiles').select('approved,active').eq('user_id', user.id).maybeSingle();
    if (!prof?.approved || prof?.active === false) return errJson(403, '승인된 계정만 이용할 수 있습니다.', cors);
  }

  let body: Record<string, unknown>;
  try { body = await req.json(); } catch { return errJson(400, '요청 형식이 올바르지 않습니다.', cors); }

  const issueId = Number(body.issue_id || 0);
  if (!issueId) return errJson(400, 'issue_id가 필요합니다.', cors);
  const limit = Math.min(Number(body.limit || MAX_LINK), MAX_LINK);

  const { data: issue } = await sb.from('issues')
    .select('id,title,definition').eq('id', issueId).maybeSingle();
  if (!issue) return errJson(404, '이슈를 찾지 못했습니다.', cors);

  // ── ① 검색어 ──
  const queries: string[] = Array.isArray(body.queries) && body.queries.length
    ? (body.queries as string[]).slice(0, 4).map(String)
    : [String(issue.title)];

  // ── ② 다중 소스 수집 (네이버 정확도순 + 구글 기간 지정 2구간) ──
  const today = new Date();
  const y1 = new Date(today.getTime() - 365 * 86400000).toISOString().slice(0, 10);
  const y2 = new Date(today.getTime() - 730 * 86400000).toISOString().slice(0, 10);
  const jobs: Promise<Cand[]>[] = [];
  for (const q of queries) {
    jobs.push(searchNaver(q, 'sim'));
    jobs.push(searchGoogle(q, y1));            // 최근 1년
    jobs.push(searchGoogle(q, y2, y1));        // 그 이전 1년
  }
  const found = (await Promise.all(jobs)).flat();

  // ── ③ 중복·기존·삭제분 제외 ──
  const [{ data: linked }, { data: deleted }] = await Promise.all([
    sb.from('issue_links').select('item_id').eq('issue_id', issueId).eq('item_type', 'news'),
    sb.from('deleted_news').select('url'),
  ]);
  const linkedIds = new Set((linked || []).map((r: { item_id: string }) => r.item_id));
  const deadKeys = new Set((deleted || []).map((r: { url: string }) => urlKey(r.url)));

  const { data: linkedRows } = linkedIds.size
    ? await sb.from('news_feed').select('id,url').in('id', [...linkedIds])
    : { data: [] as { id: string; url: string }[] };
  (linkedRows || []).forEach((r) => deadKeys.add(urlKey(r.url)));

  const seen = new Set<string>();
  const cands: Cand[] = [];
  for (const c of found) {
    const k = urlKey(c.url);
    if (!k || seen.has(k) || deadKeys.has(k)) continue;
    seen.add(k);
    cands.push(c);
    if (cands.length >= MAX_CANDIDATES) break;
  }
  if (!cands.length) {
    return new Response(JSON.stringify({ ok: true, linked: [], excluded: [], scanned: found.length }), {
      headers: { ...cors, 'content-type': 'application/json' },
    });
  }

  // ── ④ Haiku 관련성 판정 — 이슈 정의를 기준문에 넣어 이 이슈에 속하는지만 본다 ──
  let keepIdx = new Set<number>();
  if (ANTHROPIC_KEY) {
    const list = cands.map((c, i) => `${i + 1}. ${c.title}${c.date ? ` (${c.date})` : ''}`).join('\n');
    const sys = '너는 정책 모니터링 담당자다. 주어진 이슈에 **직접 속하는** 기사만 고른다. ' +
      '같은 업계·같은 회사라도 사건이 다르면 제외한다. 애매하면 제외한다. ' +
      '반드시 번호만 쉼표로 구분해 출력하고 다른 말은 하지 않는다. 해당 없으면 "none".';
    const usr = `이슈: ${issue.title}\n` +
      (issue.definition ? `정의: ${issue.definition}\n` : '') +
      `\n기사 목록:\n${list}\n\n이 이슈에 직접 속하는 기사 번호만 출력하라.`;
    try {
      const r = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: { 'x-api-key': ANTHROPIC_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
        // 관련성 판정은 Sonnet(운영자 승인 2026-08-26) — 오연결 시 무관 기사 최대 30건이
        // 영구 잠금되는 고부담 판정. 승인·보강 시에만 호출되어 빈도가 낮다.
        body: JSON.stringify({
          model: 'claude-sonnet-5', max_tokens: 800, thinking: { type: 'disabled' },
          system: sys, messages: [{ role: 'user', content: usr }],
        }),
      });
      if (r.ok) {
        const j = await r.json();
        const text = (j.content || []).map((c: { text?: string }) => c.text || '').join('');
        keepIdx = new Set(
          (text.match(/\d+/g) || []).map((n: string) => Number(n) - 1)
            .filter((i: number) => i >= 0 && i < cands.length),
        );
      }
    } catch { /* 판정 실패 시 아래 폴백 */ }
  }
  // 판정이 비면 제목 키워드 폴백 — 크롤러와 같은 원칙(AI 실패가 수집 중단으로 이어지지 않게)
  if (!keepIdx.size) {
    const toks = String(issue.title).split(/[\s·,—-]+/).filter((t) => t.length >= 2);
    cands.forEach((c, i) => { if (toks.filter((t) => c.title.includes(t)).length >= 2) keepIdx.add(i); });
  }

  const picked = cands.filter((_, i) => keepIdx.has(i)).slice(0, limit);
  const excluded = cands.filter((_, i) => !keepIdx.has(i)).map((c) => ({ title: c.title, url: c.url, date: c.date }));

  // ── ⑤ 저장 + 이슈 연결 + 잠금 ──
  const linkedOut: { title: string; url: string; date: string | null }[] = [];
  for (const c of picked) {
    try {
      // url UNIQUE — 이미 있으면 그 행을 쓰고, 없으면 새로 넣는다
      const { data: exist } = await sb.from('news_feed').select('id').eq('url', c.url).maybeSingle();
      let newsId = exist?.id as string | undefined;
      if (!newsId) {
        const { data: ins, error: insErr } = await sb.from('news_feed').insert({
          title: c.title, source: c.source, category: '기타', url: c.url,
          published_at: c.date ? `${c.date}T00:00:00Z` : null,
          summary: c.desc || null, locked: true, is_read: true,
        }).select('id').single();
        if (insErr) continue;
        newsId = ins.id;
      } else {
        await sb.from('news_feed').update({ locked: true }).eq('id', newsId);
      }
      await sb.from('issue_links').upsert({
        issue_id: issueId, item_type: 'news', item_id: newsId,
        item_date: c.date, title: c.title, added_by: 'auto',
      }, { onConflict: 'issue_id,item_type,item_id' });
      linkedOut.push({ title: c.title, url: c.url, date: c.date });
    } catch { /* 개별 실패는 건너뛴다 */ }
  }

  if (linkedOut.length) {
    await sb.from('issues').update({ last_activity_at: new Date().toISOString() }).eq('id', issueId);
  }

  return new Response(JSON.stringify({
    ok: true, scanned: found.length, candidates: cands.length,
    linked: linkedOut, excluded: excluded.slice(0, 60),
  }), { headers: { ...cors, 'content-type': 'application/json' } });
});
