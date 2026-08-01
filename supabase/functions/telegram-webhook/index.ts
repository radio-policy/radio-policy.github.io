// ============================================================================
//  Supabase Edge Function : telegram-webhook  (구독자 봇 — 운영자 봇과 별개)
//
//  역할: 구독자 봇(SUBSCRIBER_BOT_TOKEN)의 Telegram webhook 수신부.
//   - /start /settings /stop : 수신 설정 (인라인 키보드로 토픽·요일·수신시각 토글)
//   - /law "OO법 N조" : 조문 원문 즉답 (LLM 없음, 비용 0)
//   - /ask <질문> (또는 평문 질문) : AI 자문 — ai_allowed 승인자만, 일일 상한, 건당 API 과금
//   - /admin : 운영자 전용 (승인자 관리)
//
//  보안: verify_jwt OFF 대신 X-Telegram-Bot-Api-Secret-Token == TELEGRAM_WEBHOOK_SECRET 검증.
//  푸시/풀 독립 원칙: 토픽 토글은 푸시 발송만 제어. /law는 누구나, /ask는 ai_allowed만
//  — 토픽을 전부 꺼도 질의 기능은 동작한다("뉴스는 안 받고 자문만" 케이스).
//
//  발송 시점: 브리핑·긴급·법안 모두 구독자가 고른 시각(briefing_hour)에 send-subscriber-briefing이
//  모아 보낸다. 즉시 발송이 없으므로 '야간 무음'·'구독 해지' 같은 토글은 두지 않는다.
//
//  Secrets: SUBSCRIBER_BOT_TOKEN / TELEGRAM_WEBHOOK_SECRET / OPERATOR_CHAT_ID
//           / ANTHROPIC_API_KEY / VOYAGE_API_KEY  (Project Settings → Edge Functions → Secrets)
// ============================================================================

import 'jsr:@supabase/functions-js/edge-runtime.d.ts';
import { createClient, type SupabaseClient } from 'jsr:@supabase/supabase-js@2';
import { escapeHtml, splitByLines, mdToTelegramHtml, sendTelegramHtml } from '../_shared/telegram_format.ts';
import { answerAdvisory } from '../_shared/rag.ts';

// env는 반드시 trim — Supabase 콘솔에 값을 붙여넣을 때 줄바꿈이 딸려 들어가는 일이 잦고,
// 그러면 시크릿 비교가 조용히 어긋나거나(401) API 헤더가 깨진다. 공백은 시크릿에 의미가 없다.
const env = (k: string) => (Deno.env.get(k) || '').trim();

const BOT_TOKEN = env('SUBSCRIBER_BOT_TOKEN');
const WEBHOOK_SECRET = env('TELEGRAM_WEBHOOK_SECRET');
const OPERATOR_CHAT_ID = Number(env('OPERATOR_CHAT_ID') || '0');
const AI_DAILY_LIMIT = 20;   // 승인자 1인당 자문 일일 상한 (과금 폭주 방지)

const sb: SupabaseClient = createClient(
  Deno.env.get('SUPABASE_URL')!,
  Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
);

// ── Telegram API 호출 ──
async function tg(method: string, payload: Record<string, unknown>): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/${method}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    if (!res.ok) console.error(`[tg ${method}]`, res.status, (await res.text()).slice(0, 200));
    return res.ok ? (await res.json()).result : null;
  } catch (e) { console.error(`[tg ${method}]`, e); return null; }
}

// ── 구독자 행 ──
interface Sub {
  chat_id: number; username: string | null; first_name: string | null; active: boolean;
  topic_briefing: boolean; topic_urgent: boolean; topic_assembly: boolean;
  days: string; briefing_hour: number;
  ai_allowed: boolean; ai_count_date: string | null; ai_count: number;
}
async function getSub(chatId: number): Promise<Sub | null> {
  const { data } = await sb.from('telegram_subscribers').select('*').eq('chat_id', chatId).maybeSingle();
  return data as Sub | null;
}
async function upsertSub(chatId: number, patch: Record<string, unknown>): Promise<void> {
  await sb.from('telegram_subscribers')
    .upsert({ chat_id: chatId, ...patch, updated_at: new Date().toISOString() }, { onConflict: 'chat_id' });
}

// ── 설정 키보드 ──
// 표시 규칙을 성격별로 나눈다 (한 화면에 두 종류의 설정이 섞여 있어 구분이 필요):
//   ✅ / ⬜  = 여러 개를 각각 켜고 끄는 항목 (콘텐츠 3종)
//   🔵 / ⚪  = 여럿 중 하나만 고르는 항목 (요일, 받는 시각)
// ●/○ 는 텔레그램 폰트에서 크기 차이가 거의 없어 "눌렀는데 안 바뀐 것 같다"는 혼동을 줬다.
function settingsKeyboard(s: Sub) {
  const chk = (on: boolean) => on ? '✅' : '⬜';   // 체크박스(다중 선택)
  const sel = (on: boolean) => on ? '🔵' : '⚪';   // 라디오(택일)
  const hh = (v: number) => String(v).padStart(2, '0');
  return { inline_keyboard: [
    [{ text: `${chk(s.topic_briefing)} 📡 모닝 브리핑`, callback_data: 't:briefing' },
     { text: `${chk(s.topic_urgent)} 🚨 긴급 뉴스`, callback_data: 't:urgent' }],
    [{ text: `${chk(s.topic_assembly)} 🏛️ 법안 동향`, callback_data: 't:assembly' }],
    [{ text: '— 아래는 하나만 선택 —', callback_data: 'noop' }],
    [{ text: `${sel(s.days === 'daily')} 매일 받기`, callback_data: 'd:daily' },
     { text: `${sel(s.days === 'weekday')} 평일만`, callback_data: 'd:weekday' }],
    // 수신 시각은 위 3종 모두에 적용된다(긴급·법안도 즉시가 아니라 이 시각에 모아서 발송).
    [{ text: `받는 시각 (브리핑·긴급·법안) — 현재 ${hh(s.briefing_hour)}시`, callback_data: 'noop' }],
    [6, 7, 8, 9, 10, 12].map((v) => ({
      text: `${sel(s.briefing_hour === v)}${hh(v)}`,
      callback_data: `h:${v}`,
    })),
    // '구독 해지' 버튼은 두지 않는다 — 항목 3개를 모두 끄면 결과가 같은데
    // 상태만 두 가지가 되어 "어느 쪽으로 껐는지" 헷갈렸다.
  ] };
}

const START_TEXT =
  '✅ <b>구독 완료!</b>\n\n' +
  '선택한 요일·시각에 <b>모닝 브리핑·긴급 뉴스·법안 동향</b>이 한 번에 도착합니다.\n' +
  '아래 버튼으로 콘텐츠·요일·수신 시각을 바로 바꿀 수 있어요. (언제든 /settings)\n' +
  '항목을 모두 끄면 알림이 오지 않습니다.\n\n' +
  '📖 <b>조문 조회</b> — <code>/law 전기통신사업법 19조</code> (즉답, 원문 그대로)\n' +
  '🤖 <b>AI 자문</b> — <code>/ask 질문</code> (운영자 최초 1회 승인 필요)';

// ── 조문 원문 조회 (비용 0) ──
const ARTICLE_RE = /^(.{2,40}?)\s*제?\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*$/;

async function handleLawQuery(chatId: number, q: string): Promise<void> {
  const query = q.trim();
  if (!query) {
    await sendTelegramHtml(BOT_TOKEN, chatId,
      '사용법: <code>/law 전기통신사업법 19조</code>\n' +
      '조문 번호를 알 때 원문을 바로 꺼냅니다. 내용을 묻는 질문은 <code>/ask</code> 를 쓰세요.');
    return;
  }
  const m = query.match(ARTICLE_RE);
  if (m) { await handleArticleLookup(chatId, m[1].trim(), m[2], m[3]); return; }

  // 자연어 질문은 /ask로 보낸다.
  // 키워드 검색을 네 차례 고쳤지만(불용어·확장·조문필터·가중치) 질의 형태에 따라 계속 무너졌다
  // — 특히 '3G'처럼 한글이 아닌 주제어에서. 반면 /ask는 같은 질문에 조문과 최신 동향을 함께 답한다.
  // /law는 "OO법 N조" 원문 즉답(2~3초·비용 0·원문 그대로)만 담당한다.
  await sendTelegramHtml(BOT_TOKEN, chatId,
    'ℹ️ <b>/law</b> 는 조문 번호를 알 때 원문을 바로 꺼내는 기능입니다.\n' +
    '예: <code>/law 전기통신사업법 19조</code>\n\n' +
    '내용을 묻는 질문은 AI 자문이 훨씬 정확합니다. 아래를 눌러 복사한 뒤 보내세요:\n\n' +
    `<code>/ask ${escapeHtml(query)}</code>`);
}

async function handleArticleLookup(chatId: number, docName: string, artNo: string, subNo?: string): Promise<void> {
  const wanted = `제${artNo}조` + (subNo ? `의${subNo}` : '');
  const { data } = await sb.from('document_chunks')
    .select('id, doc_name, article_no, content, notice_no, effective_date, chunk_index')
    .eq('is_approved', true).eq('status', 'current')
    .ilike('doc_name', `%${docName}%`).ilike('article_no', `${wanted}%`)
    .order('chunk_index').limit(30);
  // "제19조" 요청 시 "제19조의2"가 딸려오는 것 방지 — 의N 요청이 아니면 '의'로 이어지는 조는 제외
  const rows = ((data || []) as { id: number; doc_name: string; article_no: string; content: string; notice_no?: string; effective_date?: string }[])
    .filter((r) => {
      const a = (r.article_no || '').split('(')[0].replace(/\s/g, '');
      return subNo ? a.startsWith(wanted) : (a === wanted || a.startsWith(wanted + '('));
    });
  if (!rows.length) {
    await sendTelegramHtml(BOT_TOKEN, chatId,
      `📖 "<b>${escapeHtml(docName)} ${escapeHtml(wanted)}</b>" — DB에 등재되지 않았습니다.\n` +
      `이 시스템 DB에는 전파 분야 법령·고시 위주로 등재되어 있습니다.\n` +
      `🔗 <a href="https://www.law.go.kr/lsSc.do?query=${encodeURIComponent(docName)}">국가법령정보센터에서 확인</a>`);
    return;
  }
  // 법령명이 여럿 걸리면(본법·시행령·시행규칙) 이름이 가장 짧은 것(본법) 우선, 나머지는 안내
  const names = [...new Set(rows.map((r) => r.doc_name))].sort((a, b) => a.length - b.length);
  const picked = rows.filter((r) => r.doc_name === names[0]);
  const head = picked[0];
  const meta: string[] = [];
  if (head.effective_date) meta.push('시행 ' + head.effective_date);
  if (head.notice_no) meta.push(head.notice_no);
  let body = `📖 <b>${escapeHtml(head.doc_name)} ${escapeHtml(head.article_no || wanted)}</b>\n`;
  if (meta.length) body += `<i>${escapeHtml(meta.join(' · '))}</i>\n`;
  body += '\n' + escapeHtml(picked.map((r) => r.content).join('\n'));
  if (names.length > 1) body += `\n\n<i>같은 조가 있는 다른 문서: ${escapeHtml(names.slice(1).join(', '))} — "${escapeHtml(names[1])} ${wanted}"처럼 문서명을 정확히 지정해 다시 검색하세요.</i>`;
  for (const part of splitByLines(body)) await sendTelegramHtml(BOT_TOKEN, chatId, part);
}

// ── AI 자문 (승인제 + 일일 상한 + 백그라운드 실행) ──
function todayKst(): string {
  return new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
}

async function handleAsk(chatId: number, from: { username?: string; first_name?: string }, question: string): Promise<Promise<void> | void> {
  const q = question.trim();
  if (!q) { await sendTelegramHtml(BOT_TOKEN, chatId, '사용법: <code>/ask 질문 내용</code>'); return; }
  const sub = await getSub(chatId);
  if (!sub?.ai_allowed) {
    // 미승인 → 본인 안내 + 운영자에게 승인 버튼
    await sendTelegramHtml(BOT_TOKEN, chatId, '🔒 AI 자문은 운영자 승인이 필요합니다(최초 1회만).\n승인 요청을 보냈습니다 — 승인되면 다시 질문해 주세요.');
    if (OPERATOR_CHAT_ID) {
      await tg('sendMessage', {
        chat_id: OPERATOR_CHAT_ID, parse_mode: 'HTML',
        text: `👤 <b>AI 자문 권한 요청</b>\n${escapeHtml(from.first_name || '')} (@${escapeHtml(from.username || '없음')}, <code>${chatId}</code>)\n첫 질문: ${escapeHtml(q.slice(0, 200))}`,
        reply_markup: { inline_keyboard: [[
          { text: '✅ 승인', callback_data: `ai:ok:${chatId}` },
          { text: '❌ 거부', callback_data: `ai:no:${chatId}` },
        ]] },
      });
    }
    return;
  }
  // 일일 상한
  const today = todayKst();
  const used = sub.ai_count_date === today ? sub.ai_count : 0;
  if (used >= AI_DAILY_LIMIT) {
    await sendTelegramHtml(BOT_TOKEN, chatId, `⏳ 오늘 자문 한도(${AI_DAILY_LIMIT}회)를 모두 사용했습니다. 내일 다시 이용해 주세요.`);
    return;
  }
  await upsertSub(chatId, { ai_count_date: today, ai_count: used + 1 });
  await sendTelegramHtml(BOT_TOKEN, chatId, '🤔 법령·자료를 검토하고 있습니다... (1~2분 소요)');

  // webhook 200을 먼저 돌려보내고 백그라운드에서 RAG+Sonnet 실행 (텔레그램 재시도 방지)
  return (async () => {
    try {
      // 시스템 프롬프트는 app_config에서 읽는다 (원본은 루트 system_prompt.js — sync_system_prompt.py로 업로드).
      // 함수에 번들하지 않으므로 프롬프트 수정 시 재배포가 필요 없다.
      const { data: cfg } = await sb.from('app_config').select('value').eq('key', 'system_prompt').maybeSingle();
      const systemPrompt = (cfg?.value as string) || '';
      if (!systemPrompt) throw new Error('app_config.system_prompt 미등록 — python sync_system_prompt.py 실행 필요');
      const { answer, sources } = await answerAdvisory(sb, systemPrompt, q);
      let html = mdToTelegramHtml(answer);
      if (sources.length) html += '\n\n<i>📚 참조: ' + escapeHtml(sources.slice(0, 6).join(', ')) + '</i>';
      for (const part of splitByLines(html)) await sendTelegramHtml(BOT_TOKEN, chatId, part);
      // 기존 chat_logs에 기록 (source 컬럼이 없어 category로 구분 — 스키마 변경 없음)
      await sb.from('chat_logs').insert({ question: q, answer, category: '텔레그램', sources: sources.join(', ') });
    } catch (e) {
      console.error('[자문 실패]', e);
      await sendTelegramHtml(BOT_TOKEN, chatId, '⚠️ 자문 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.');
    }
  })();
}

// ── 운영자 /admin ──
async function handleAdmin(chatId: number): Promise<void> {
  if (chatId !== OPERATOR_CHAT_ID) return;   // 운영자 외 무응답
  const { data } = await sb.from('telegram_subscribers').select('chat_id, first_name, username, active, ai_allowed').order('created_at');
  const rows = (data || []) as { chat_id: number; first_name?: string; username?: string; active: boolean; ai_allowed: boolean }[];
  const total = rows.length, act = rows.filter((r) => r.active).length;
  const allowed = rows.filter((r) => r.ai_allowed);
  let text = `🛠 <b>구독자 현황</b> — 총 ${total}명 (활성 ${act})\n\n<b>AI 자문 승인자</b> (${allowed.length}명)`;
  if (!allowed.length) text += '\n(없음)';
  const kb = allowed.map((r) => ([{
    text: `🚫 회수: ${r.first_name || ''} @${r.username || r.chat_id}`,
    callback_data: `ai:rv:${r.chat_id}`,
  }]));
  await tg('sendMessage', { chat_id: chatId, parse_mode: 'HTML', text, reply_markup: { inline_keyboard: kb } });
}

// ── callback_query 처리 ──
async function handleCallback(cb: { id: string; data?: string; from: { id: number }; message?: { chat: { id: number }; message_id: number } }): Promise<void> {
  const data = cb.data || '';
  const chatId = cb.message?.chat.id || cb.from.id;
  const msgId = cb.message?.message_id;
  let ack = '저장했습니다';

  if (data.startsWith('ai:')) {
    // 승인/거부/회수 — 운영자 채팅에서 온 콜백만 유효
    const [, action, target] = data.split(':');
    const targetId = Number(target);
    if (cb.from.id !== OPERATOR_CHAT_ID) { await tg('answerCallbackQuery', { callback_query_id: cb.id, text: '권한 없음' }); return; }
    if (action === 'ok') {
      await upsertSub(targetId, { ai_allowed: true });
      await sendTelegramHtml(BOT_TOKEN, targetId, '✅ AI 자문 권한이 승인되었습니다!\n<code>/ask 질문</code> 으로 이용하세요.');
      ack = '승인 완료';
    } else if (action === 'no') {
      await sendTelegramHtml(BOT_TOKEN, targetId, '❌ AI 자문 권한 요청이 거부되었습니다.');
      ack = '거부 처리';
    } else if (action === 'rv') {
      await upsertSub(targetId, { ai_allowed: false });
      await sendTelegramHtml(BOT_TOKEN, targetId, '🔒 AI 자문 권한이 회수되었습니다.');
      ack = '회수 완료';
    }
    await tg('answerCallbackQuery', { callback_query_id: cb.id, text: ack });
    return;
  }

  if (data.startsWith('kb:')) {
    // (구버전 메시지의 [전문 보기] 버튼 호환) 조문 전문 표시
    const id = Number(data.slice(3));
    const { data: row } = await sb.from('document_chunks')
      .select('doc_name, article_no, content, notice_no, effective_date').eq('id', id).maybeSingle();
    if (row) {
      const r = row as { doc_name: string; article_no?: string; content: string; notice_no?: string; effective_date?: string };
      const meta: string[] = [];
      if (r.effective_date) meta.push('시행 ' + r.effective_date);
      if (r.notice_no) meta.push(r.notice_no);
      let body = `📖 <b>${escapeHtml(r.doc_name)}${r.article_no ? ' ' + escapeHtml(r.article_no) : ''}</b>\n`;
      if (meta.length) body += `<i>${escapeHtml(meta.join(' · '))}</i>\n`;
      body += '\n' + escapeHtml(r.content);
      for (const part of splitByLines(body)) await sendTelegramHtml(BOT_TOKEN, chatId, part);
    }
    await tg('answerCallbackQuery', { callback_query_id: cb.id });
    return;
  }

  if (data === 'noop') { await tg('answerCallbackQuery', { callback_query_id: cb.id }); return; }

  // ── 설정 토글 ──
  // 반응 속도가 체감 품질을 좌우한다. 예전에는 DB 읽기 → 쓰기 → 다시 읽기 → 화면 갱신을
  // 순차로 4번 왕복해 버튼이 굼떴다. 지금은 ① 한 번만 읽고 ② 다음 상태를 로컬에서 계산해
  // ③ DB 쓰기·화면 갱신·응답 확인을 동시에 실행한다(왕복 4회 → 사실상 2회).
  const cur = await getSub(chatId);
  const sub: Sub = cur ?? {
    chat_id: chatId, username: null, first_name: null, active: true,
    topic_briefing: true, topic_urgent: true, topic_assembly: true,
    days: 'daily', briefing_hour: 7,
    ai_allowed: false, ai_count_date: null, ai_count: 0,
  };

  const patch: Record<string, unknown> = {};
  if (data === 't:briefing') { patch.topic_briefing = !sub.topic_briefing; ack = patch.topic_briefing ? '모닝 브리핑 ON' : '모닝 브리핑 OFF'; }
  else if (data === 't:urgent') { patch.topic_urgent = !sub.topic_urgent; ack = patch.topic_urgent ? '긴급 뉴스 ON' : '긴급 뉴스 OFF'; }
  else if (data === 't:assembly') { patch.topic_assembly = !sub.topic_assembly; ack = patch.topic_assembly ? '법안 동향 ON' : '법안 동향 OFF'; }
  else if (data === 'd:daily') { patch.days = 'daily'; ack = '매일 받기로 변경'; }
  else if (data === 'd:weekday') { patch.days = 'weekday'; ack = '평일(월~금)만 받기로 변경'; }
  else if (data.startsWith('h:')) {
    // 시각 변경 시 오늘 발송 기록 초기화 — 새 시각이 아직 안 지났으면 오늘분부터 새 시각에 수신
    patch.briefing_hour = Number(data.slice(2));
    patch.last_briefing_sent_date = null;
    ack = `받는 시각 ${String(patch.briefing_hour).padStart(2, '0')}시로 변경`;
  }
  // 예전 메시지에 남아 있는 해지/재개 버튼 호환 — 항목 일괄 끄기/켜기로 해석한다
  else if (data === 'unsub') {
    patch.topic_briefing = false; patch.topic_urgent = false; patch.topic_assembly = false;
    ack = '모든 알림을 껐습니다 (조회·자문은 계속 사용 가능)';
  }
  else if (data === 'resub') {
    patch.active = true;
    patch.topic_briefing = true; patch.topic_urgent = true; patch.topic_assembly = true;
    ack = '모든 알림을 켰습니다';
  }
  else { await tg('answerCallbackQuery', { callback_query_id: cb.id }); return; }

  const next: Sub = { ...sub, ...patch } as Sub;
  await Promise.all([
    upsertSub(chatId, patch),
    tg('answerCallbackQuery', { callback_query_id: cb.id, text: ack }),
    msgId
      ? tg('editMessageReplyMarkup', { chat_id: chatId, message_id: msgId, reply_markup: settingsKeyboard(next) })
      : Promise.resolve(null),
  ]);
}

// ── 메인 ──
Deno.serve(async (req: Request) => {
  if (req.headers.get('x-telegram-bot-api-secret-token') !== WEBHOOK_SECRET || !WEBHOOK_SECRET) {
    return new Response('unauthorized', { status: 401 });
  }
  let update: Record<string, unknown>;
  try { update = await req.json(); } catch { return new Response('bad request', { status: 400 }); }

  try {
    if (update.callback_query) {
      await handleCallback(update.callback_query as Parameters<typeof handleCallback>[0]);
      return new Response('ok');
    }
    const msg = update.message as { chat: { id: number }; from?: { username?: string; first_name?: string }; text?: string } | undefined;
    if (!msg?.text) return new Response('ok');
    const chatId = msg.chat.id;
    const from = msg.from || {};
    const text = msg.text.trim();

    if (text === '/start' || text.startsWith('/start ')) {
      await upsertSub(chatId, { username: from.username || null, first_name: from.first_name || null, active: true });
      const sub = (await getSub(chatId))!;
      await tg('sendMessage', { chat_id: chatId, parse_mode: 'HTML', text: START_TEXT, disable_web_page_preview: true, reply_markup: settingsKeyboard(sub) });
    } else if (text === '/settings' || text === '/설정') {
      let sub = await getSub(chatId);
      if (!sub) { await upsertSub(chatId, { username: from.username || null, first_name: from.first_name || null }); sub = (await getSub(chatId))!; }
      await tg('sendMessage', { chat_id: chatId, parse_mode: 'HTML',
        text: '⚙️ <b>수신 설정</b>\n버튼을 눌러 바로 변경할 수 있습니다.\n✅⬜ = 여러 개 선택 · 🔵⚪ = 하나만 선택\n<i>항목을 모두 끄면 알림이 오지 않습니다.</i>',
        reply_markup: settingsKeyboard(sub) });
    } else if (text === '/stop') {
      // 메뉴에서는 뺐지만 하위호환으로 남긴다 — '모든 항목 끄기'로 동작(설정·시각은 보존)
      await upsertSub(chatId, { topic_briefing: false, topic_urgent: false, topic_assembly: false });
      await sendTelegramHtml(BOT_TOKEN, chatId, '🔕 모든 알림을 껐습니다.\n/settings 에서 원하는 항목만 다시 켤 수 있습니다.\n(조문 조회·AI 자문은 계속 사용 가능)');
    } else if (text === '/admin') {
      await handleAdmin(chatId);
    } else if (text.startsWith('/law') || text.startsWith('/법령')) {
      await handleLawQuery(chatId, text.replace(/^\/(law|법령)\s*/, ''));
    } else if (ARTICLE_RE.test(text) && !text.startsWith('/')) {
      await handleLawQuery(chatId, text);   // 평문 "전기통신사업법 19조" 자동 인식
    } else if (text.startsWith('/ask')) {
      const bg = await handleAsk(chatId, from, text.replace(/^\/ask\s*/, ''));
      if (bg) (globalThis as { EdgeRuntime?: { waitUntil: (p: Promise<void>) => void } }).EdgeRuntime?.waitUntil(bg);
    } else if (!text.startsWith('/')) {
      const bg = await handleAsk(chatId, from, text);   // 평문 질문 → 자문 경로 (승인 게이트가 비용 방어)
      if (bg) (globalThis as { EdgeRuntime?: { waitUntil: (p: Promise<void>) => void } }).EdgeRuntime?.waitUntil(bg);
    } else {
      await sendTelegramHtml(BOT_TOKEN, chatId, '알 수 없는 명령입니다.\n/settings 설정 · /law 조문조회 · /ask AI자문');
    }
  } catch (e) {
    // 어떤 오류도 200으로 마감 — 비200이면 텔레그램이 같은 업데이트를 재전송해 무한 반복된다
    console.error('[webhook 오류]', e);
  }
  return new Response('ok');
});
