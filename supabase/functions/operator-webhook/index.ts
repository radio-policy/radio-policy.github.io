// ============================================================================
//  Supabase Edge Function : operator-webhook  (이슈맵 — 운영자봇 버튼 + 승인 파이프)
//
//  두 입구, 한 파이프:
//   ① 텔레그램 운영자봇 콜백 — issue_suggest.py가 보낸 [승인][기각][해소] 인라인 버튼.
//      운영자봇은 지금까지 push 전용이었고 이 함수가 첫 웹훅이다(setWebhook 필요).
//   ② 대시보드 POST {action, issue_id} — admin 로그인 사용자. 같은 파이프를 호출해
//      텔레그램과 대시보드의 동작이 어긋나지 않게 한다(로직 한 벌 원칙).
//
//  검증:
//   - 텔레그램: X-Telegram-Bot-Api-Secret-Token == OPERATOR_WEBHOOK_SECRET
//     + callback 발신 chat_id == OPERATOR_CHAT_ID (운영자 1인 전용)
//     + telegram_updates로 update_id 중복 차단(#83 패턴 재사용)
//   - 대시보드: Bearer JWT → auth.getUser → profiles(user_id).role='admin' & approved
//
//  승인 시 자동 보강 2단(fire-and-forget — 실패가 승인 자체를 막으면 안 된다):
//   ① news-archive-search — 과거 뉴스 재수집(네이버+구글)
//   ② enrichIssue — Sonnet 3콜: 영향 요약·이해관계자 초안·기존 법령 주제 매칭
//      (운영자 승인 2026-09-01: "승인하면 3G·5G 이슈처럼" — 신규 주제 생성·사례 문서는
//       조문·사실 검증이 필요해 세션 몫. 무인 반복 경로라 API가 맞은 경로다.)
//
//  Secrets: TELEGRAM_BOT_TOKEN(운영자봇) / OPERATOR_CHAT_ID / OPERATOR_WEBHOOK_SECRET
//           SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY
// ============================================================================

import 'jsr:@supabase/functions-js/edge-runtime.d.ts';
import { createClient } from 'jsr:@supabase/supabase-js@2';

const env = (k: string) => (Deno.env.get(k) || '').trim();
const BOT = env('TELEGRAM_BOT_TOKEN');
const TG = `https://api.telegram.org/bot${BOT}`;

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
  return new Response(JSON.stringify(body), {
    status, headers: { ...cors, 'content-type': 'application/json' },
  });
}

// ── 승인 후 자동 보강 — Sonnet 3콜 (영향 요약 / 이해관계자 초안 / 기존 주제 매칭) ──
async function sonnet(system: string, user: string, maxTokens: number): Promise<string> {
  const r = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'x-api-key': env('ANTHROPIC_API_KEY'),
      'anthropic-version': '2023-06-01',
      'content-type': 'application/json',
    },
    // Sonnet 5는 temperature를 거부하고 적응형 추론이 기본 ON — 기계적 생성이라 끈다
    body: JSON.stringify({ model: 'claude-sonnet-5', max_tokens: maxTokens,
      thinking: { type: 'disabled' }, system,
      messages: [{ role: 'user', content: user }] }),
  });
  const j = await r.json();
  if (j.error) throw new Error(j.error.message || 'API 오류');
  return (j.content || []).filter((b: { type: string }) => b.type === 'text')
    .map((b: { text: string }) => b.text).join('').trim();
}

async function enrichIssue(sb: ReturnType<typeof createClient>, issueId: number): Promise<string> {
  const { data: iss } = await sb.from('issues')
    .select('id,title,definition,impact_summary').eq('id', issueId).maybeSingle();
  if (!iss) return '이슈 없음';
  const { data: links } = await sb.from('issue_links').select('id,item_type,item_date,title')
    .eq('issue_id', issueId).order('item_date', { ascending: false }).limit(200);
  const news = (links || []).filter((l: { item_type: string }) => l.item_type === 'news').slice(0, 30);
  if (!news.length) return '연결 기사 없음';
  const srcList = news.map((l: { item_date: string; title: string }, k: number) =>
    `[${k + 1}] ${l.item_date || ''} ${l.title || ''}`).join('\n');
  const ctx = `이슈: ${iss.title}\n정의: ${iss.definition || ''}\n연결 기사:\n${srcList}`;
  const done: string[] = [];

  // ① 영향 요약 (기존값 있으면 보존 — 세션 생성분을 덮지 않는다)
  if (!iss.impact_summary) {
    try {
      const t = await sonnet(
        'SKT Comm센터 기술정책팀 보좌역. 목록의 사실만 사용하고 모든 문장 끝에 근거 번호 [n]을 붙인다. 태그 밖 다른 말 금지.',
        ctx + '\n\n<what>무슨 일이 벌어졌는가(2~3문장)</what><why>왜 SKT에 중요한가(2~3문장)</why><action>무엇을 해야 하는가(2~3문장)</action> 형식으로만 출력.', 1000);
      const pick = (tag: string) => (t.match(new RegExp('<' + tag + '>([\\s\\S]*?)</' + tag + '>')) || [])[1]?.trim() || '';
      const what = pick('what'), why = pick('why'), action = pick('action');
      if (what || why) {
        await sb.from('issues').update({ impact_summary: {
          what, why, action,
          sources: news.map((l: { id: number; title: string }, k: number) =>
            ({ n: k + 1, type: 'news', link_id: l.id, title: l.title })),
          model: 'claude-sonnet-5-auto', generated_at: new Date().toISOString(),
        } }).eq('id', issueId);
        done.push('영향요약');
      }
    } catch (e) { console.error('[보강:영향]', issueId, e); }
  }

  // ② 이해관계자 초안 (없을 때만)
  const { count: stk } = await sb.from('issue_links').select('id', { count: 'exact', head: true })
    .eq('issue_id', issueId).eq('item_type', 'stakeholder');
  if (!stk) {
    try {
      const t = await sonnet('통신정책 이슈의 이해관계자 추출기. JSON 하나만 출력한다.',
        ctx + '\n\n주요 이해관계자 3~6개를 {"stakeholders":[{"name":"기관·회사명","stance":"기사에서 확인되는 입장 요지 1문장"}]} JSON으로만. 기사로 확인되는 것만 넣는다.', 700);
      const m = t.match(/\{[\s\S]*\}/);
      const arr = m ? (JSON.parse(m[0]).stakeholders || []) : [];
      for (const st of arr.slice(0, 6)) {
        if (!st?.name) continue;
        await sb.from('issue_links').insert({
          issue_id: issueId, item_type: 'stakeholder',
          item_id: String(st.name).slice(0, 60), title: String(st.name).slice(0, 60),
          note: `${st.stance || ''} (자동 생성 초안)`, added_by: 'auto' });
      }
      if (arr.length) done.push(`이해관계자 ${Math.min(arr.length, 6)}`);
    } catch (e) { console.error('[보강:이해관계자]', issueId, e); }
  }

  // ③ 기존 법령 주제 매칭 (신규 주제 생성은 하지 않는다 — 조문 검증은 세션 몫)
  const { count: tp } = await sb.from('issue_links').select('id', { count: 'exact', head: true })
    .eq('issue_id', issueId).eq('item_type', 'law_topic');
  if (!tp) {
    try {
      const { data: topics } = await sb.from('law_graph_nodes').select('name').eq('node_type', 'topic');
      const names = (topics || []).map((x: { name: string }) => x.name);
      if (names.length) {
        const t = await sonnet('통신 법령 주제 매칭기. JSON 하나만 출력한다.',
          `이슈: ${iss.title} — ${iss.definition || ''}\n주제 목록: ${names.join(' | ')}\n\n이 이슈에 직접 해당하는 주제가 목록에 있으면 {"topic":"목록의 정확한 주제명"} 없으면 {"topic":null} JSON만. 애매하면 null.`, 200);
        const m = t.match(/\{[\s\S]*\}/);
        const topic = m ? JSON.parse(m[0]).topic : null;
        if (topic && names.includes(topic)) {
          await sb.from('issue_links').insert({
            issue_id: issueId, item_type: 'law_topic', item_id: topic, title: topic,
            note: '법령 관계도 주제 연결 (자동 매칭)', added_by: 'auto' });
          done.push(`주제:${topic}`);
        }
      }
    } catch (e) { console.error('[보강:주제]', issueId, e); }
  }
  return done.length ? done.join(' · ') : '추가 보강 없음(기존값 보존)';
}
/** 승인·기각·해소 파이프 — 텔레그램/대시보드 공용. 반환: 사람용 결과 문구. */
async function runAction(sb: ReturnType<typeof createClient>, action: string, issueId: number): Promise<string> {
  const { data: issue } = await sb.from('issues')
    .select('id,title,state,stage,stage_log,resolution_kind').eq('id', issueId).maybeSingle();
  if (!issue) return '이슈를 찾지 못했습니다.';
  const now = new Date().toISOString();
  const log = (issue.stage_log as unknown[]) || [];

  if (action === 'approve') {
    if (issue.state === 'active') return `이미 승인된 이슈입니다: ${issue.title}`;
    if (issue.state !== 'proposed') return `승인할 수 없는 상태(${issue.state})입니다.`;
    await sb.from('issues').update({
      state: 'active', last_activity_at: now, updated_at: now,
    }).eq('id', issueId);
    // 근거 기사는 제안 시점에 이미 연결·잠금돼 있다. 과거 뉴스 보강만 백그라운드로.
    const enrich = fetch(`${env('SUPABASE_URL')}/functions/v1/news-archive-search`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${env('SUPABASE_SERVICE_ROLE_KEY')}`,
        'content-type': 'application/json',
      },
      body: JSON.stringify({ issue_id: issueId }),
    }).then((r) => r.json()).then((j) =>
      console.log('[보강]', issueId, JSON.stringify(j).slice(0, 200)),
    ).catch((e) => console.error('[보강 실패(무시)]', e));
    EdgeRuntime.waitUntil(enrich);
    EdgeRuntime.waitUntil(
      enrichIssue(sb, issueId)
        .then((r) => console.log('[자동보강]', issueId, r))
        .catch((e) => console.error('[자동보강 실패(무시)]', issueId, e)),
    );
    return `✅ 승인됨 — ${issue.title}\n과거 뉴스 재수집 + 자동 보강(영향 요약·이해관계자·법령 주제)을 시작했습니다.\n과거 사례·기점 소급은 세션에서 "이슈 ${issueId} 보강해줘".`;
  }

  if (action === 'reject') {
    if (issue.state === 'rejected') return `이미 기각된 이슈입니다: ${issue.title}`;
    if (issue.state !== 'proposed') return `기각할 수 없는 상태(${issue.state})입니다.`;
    // 제안 시 자동 연결·잠금했던 기사 정리: 링크 제거 + 다른 이슈에 안 걸린 기사만 잠금 해제
    const { data: links } = await sb.from('issue_links').select('item_id')
      .eq('issue_id', issueId).eq('item_type', 'news');
    const ids = (links || []).map((l: { item_id: string }) => l.item_id);
    await sb.from('issue_links').delete().eq('issue_id', issueId);
    for (const nid of ids) {
      const { data: still } = await sb.from('issue_links').select('id')
        .eq('item_type', 'news').eq('item_id', nid).limit(1);
      if (!still?.length) await sb.from('news_feed').update({ locked: false }).eq('id', nid);
    }
    await sb.from('issues').update({ state: 'rejected', updated_at: now }).eq('id', issueId);
    return `❌ 기각됨 — ${issue.title}\n같은 주제는 다시 제안되지 않습니다.`;
  }

  if (action === 'resolve') {
    if (issue.stage === '해소') return `이미 해소된 이슈입니다: ${issue.title}`;
    await sb.from('issues').update({
      stage: '해소', resolution_kind: issue.resolution_kind || '자연 소멸', dormant: false,
      stage_log: [...log, { at: now, from: issue.stage, to: '해소', signal: '운영자 종결(자연 소멸)' }],
      updated_at: now,
    }).eq('id', issueId);
    return `🕊️ 해소 처리됨 — ${issue.title} (자연 소멸)\n사례 아카이브 적재는 세션에서 "이슈 ${issueId} 사례화해줘"로 요청하세요.`;
  }

  if (action === 'keep') {
    return `유지합니다 — ${issue.title} (30일 뒤 다시 확인)`;
  }

  if (action === 'enrich') {           // 수동 재보강 — 기존값 보존, 빈 항목만 채운다
    const r = await enrichIssue(sb, issueId);
    return `🧩 자동 보강 — ${issue.title}: ${r}`;
  }
  return `알 수 없는 동작: ${action}`;
}

Deno.serve(async (req) => {
  const cors = corsHeaders(req.headers.get('origin'));
  if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
  if (req.method !== 'POST') return json(405, { error: { message: 'POST만 허용' } }, cors);

  const sb = createClient(env('SUPABASE_URL'), env('SUPABASE_SERVICE_ROLE_KEY'));
  const tgSecret = req.headers.get('x-telegram-bot-api-secret-token');

  // ── 입구 ①: 텔레그램 콜백 ──
  if (tgSecret) {
    if (tgSecret !== env('OPERATOR_WEBHOOK_SECRET')) return json(403, { ok: false }, cors);
    const update = await req.json().catch(() => null);
    if (!update) return json(200, { ok: true }, cors);   // 텔레그램에는 항상 200 (재전송 폭주 방지)

    // update_id 중복 차단 — 재전송된 같은 update는 무시 (#83 패턴)
    const uid = Number(update.update_id || 0);
    if (uid) {
      const { error: dupErr } = await sb.from('telegram_updates').insert({ update_id: uid });
      if (dupErr) return json(200, { ok: true, dup: true }, cors);
    }

    const cb = update.callback_query;
    if (!cb) return json(200, { ok: true }, cors);       // 명령 등은 처리하지 않는 봇 — 버튼 전용
    const chatId = String(cb.message?.chat?.id ?? '');
    const answer = (text: string) =>
      fetch(`${TG}/answerCallbackQuery`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ callback_query_id: cb.id, text: text.slice(0, 190) }),
      }).catch(() => {});

    if (chatId !== env('OPERATOR_CHAT_ID')) {
      await answer('권한이 없습니다.');
      return json(200, { ok: true }, cors);
    }
    const m = String(cb.data || '').match(/^iss\|(approve|reject|resolve|keep)\|(\d+)$/);
    if (!m) { await answer('알 수 없는 버튼입니다.'); return json(200, { ok: true }, cors); }

    let result = '';
    try {
      result = await runAction(sb, m[1], Number(m[2]));
    } catch (e) {
      console.error('[액션 실패]', e);
      result = '처리 중 오류가 발생했습니다 — 대시보드에서 시도해 주세요.';
    }
    await answer(result.split('\n')[0]);
    // 원 메시지를 결과로 갱신 — 버튼 제거(중복 클릭 방지)
    if (cb.message?.message_id && m[1] !== 'keep') {
      const orig = String(cb.message.text || '');
      await fetch(`${TG}/editMessageText`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          chat_id: chatId, message_id: cb.message.message_id,
          text: `${orig}\n\n— ${result}`,
        }),
      }).catch(() => {});
    }
    return json(200, { ok: true }, cors);
  }

  // ── 입구 ②: 대시보드 (admin JWT) ──
  const auth = req.headers.get('authorization') || '';
  const token = auth.toLowerCase().startsWith('bearer ') ? auth.slice(7).trim() : '';
  if (!token) return json(401, { error: { message: '로그인이 필요합니다.' } }, cors);
  // 내부 호출(service-role Bearer) — 세션·다른 함수의 enrich 재실행용
  if (token === env('SUPABASE_SERVICE_ROLE_KEY')) {
    const body = await req.json().catch(() => null);
    const action = String(body?.action || '');
    const issueId = Number(body?.issue_id || 0);
    if (!['approve', 'reject', 'resolve', 'keep', 'enrich'].includes(action) || !issueId) {
      return json(400, { error: { message: 'action/issue_id가 올바르지 않습니다.' } }, cors);
    }
    try { return json(200, { ok: true, result: await runAction(sb, action, issueId) }, cors); }
    catch (e) { console.error('[내부 액션 실패]', e); return json(500, { error: { message: '처리 실패' } }, cors); }
  }
  const { data: userData } = await sb.auth.getUser(token);
  const user = userData?.user;
  if (!user) return json(401, { error: { message: '로그인이 필요합니다.' } }, cors);
  const { data: prof } = await sb.from('profiles').select('role,approved,active')
    .eq('user_id', user.id).maybeSingle();
  if (prof?.role !== 'admin' || !prof?.approved || prof?.active === false) {
    return json(403, { error: { message: '관리자만 처리할 수 있습니다.' } }, cors);
  }

  const body = await req.json().catch(() => null);
  const action = String(body?.action || '');
  const issueId = Number(body?.issue_id || 0);
  if (!['approve', 'reject', 'resolve', 'keep', 'enrich'].includes(action) || !issueId) {
    return json(400, { error: { message: 'action/issue_id가 올바르지 않습니다.' } }, cors);
  }
  try {
    const result = await runAction(sb, action, issueId);
    return json(200, { ok: true, result }, cors);
  } catch (e) {
    console.error('[액션 실패]', e);
    return json(500, { error: { message: '처리 중 오류가 발생했습니다.' } }, cors);
  }
});
