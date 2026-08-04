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
import { answerAdvisory, answerLawQuery } from '../_shared/rag.ts';
import { NEWS_TAGS, TAG_SLUGS } from '../_shared/news_tags.ts';

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
  law_count_date?: string | null; law_count?: number;   // 자연어 /law 일일 상한 (2026-08-03)
  end_hour: number;      // 수신 종료 시각(18~22) — 종전 하드코딩 '23시 이후 무발송'을 대체 (2026-08-03)
  // 관심분야. **빈 배열 = 전체 수신**(캐논 하나). 6개를 다 켜면 []로 정규화하므로,
  // 나중에 7번째 태그가 생겨도 기존 '전체' 구독자가 자동으로 받는다.
  tags: string[];
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
  // 관심분야: 빈 배열 = 전체 수신이므로 화면에는 6개 모두 ✅로 보여준다(캐논은 하나, 표시도 하나).
  const tagOn = (slug: string) => !s.tags?.length || s.tags.includes(slug);
  const tagRows: Array<Array<{ text: string; callback_data: string }>> = [];
  for (let i = 0; i < NEWS_TAGS.length; i += 2) {
    tagRows.push(NEWS_TAGS.slice(i, i + 2).map((t) => ({
      text: `${chk(tagOn(t.slug))} ${t.label}`, callback_data: `g:${t.slug}`,
    })));
  }
  return { inline_keyboard: [
    [{ text: `${chk(s.topic_briefing)} 📡 모닝 브리핑`, callback_data: 't:briefing' },
     { text: `${chk(s.topic_urgent)} 📡 주요 뉴스`, callback_data: 't:urgent' }],
    [{ text: `${chk(s.topic_assembly)} 🏛️ 법안 동향`, callback_data: 't:assembly' }],
    // ── 관심분야 ── 모닝 브리핑은 팀이 같은 그림을 보는 자리라 전원 동일하게 두고,
    // 하루 여러 번 오는 '주요 뉴스'에만 적용한다.
    // 주요 뉴스가 꺼져 있으면 태그 버튼을 아예 감춘다 — 눌러도 아무 효과가 없는 죽은 버튼을
    // 남겨두면 "껐는데 왜 켜져 보이나"로 혼동된다(운영자 지적 2026-08-03). 선택값은 DB에
    // 그대로 남아 있어 주요 뉴스를 다시 켜면 원래 상태로 돌아온다.
    ...(s.topic_urgent
      ? [[{ text: '— 관심분야 (📡 주요 뉴스에만 적용) —', callback_data: 'noop' }], ...tagRows]
      : [[{ text: '— 관심분야는 📡 주요 뉴스를 켜면 표시됩니다 —', callback_data: 'noop' }]]),
    [{ text: '— 아래는 하나만 선택 —', callback_data: 'noop' }],
    [{ text: `${sel(s.days === 'daily')} 매일 받기`, callback_data: 'd:daily' },
     { text: `${sel(s.days === 'weekday')} 평일만`, callback_data: 'd:weekday' }],
    // 수신 창 = 시작~종료. 브리핑은 시작 시각에 1회, 주요 뉴스·법안은 그 뒤 새로 생기는 대로
    // 매시 :25에 전달되고, 종료 시각을 넘기면 다음 날 시작 시각까지 발송이 없다.
    // (종전에는 종료가 '23시'로 코드에 박혀 있었다 — 구독자가 고르게 바꿈, 2026-08-03)
    [{ text: `받기 시작 시각 — 현재 ${hh(s.briefing_hour)}시`, callback_data: 'noop' }],
    [6, 7, 8, 9, 10].map((v) => ({
      text: `${sel(s.briefing_hour === v)}${hh(v)}`,
      callback_data: `h:${v}`,
    })),
    [{ text: `받기 종료 시각 — 현재 ${hh(s.end_hour)}시 (이후 무발송)`, callback_data: 'noop' }],
    [18, 19, 20, 21, 22].map((v) => ({
      text: `${sel(s.end_hour === v)}${hh(v)}`,
      callback_data: `e:${v}`,
    })),
    // '구독 해지' 버튼은 두지 않는다 — 항목 3개를 모두 끄면 결과가 같은데
    // 상태만 두 가지가 되어 "어느 쪽으로 껐는지" 헷갈렸다.
  ] };
}

const START_TEXT =
  '✅ <b>구독 완료!</b>\n\n' +
  '선택한 요일·시각에 <b>모닝 브리핑</b>이 도착하고, <b>주요 뉴스·법안 동향</b>은 그 시각 이후 새로 생기는 대로 전달됩니다.\n' +
  '🌙 <b>받기 종료 시각을 넘기면 다음 날 시작 시각까지 발송하지 않습니다.</b>\n' +
  '아래 버튼으로 콘텐츠·요일·수신 시각을 바로 바꿀 수 있어요. (언제든 /settings)\n' +
  '항목을 모두 끄면 알림이 오지 않습니다.\n\n' +
  '📖 <b>법령 검색</b> — <code>/law 3G 종료 관련 법령</code> (궁금한 주제 → 관련 법령·조항과 이유. 조문 번호를 알면 <code>/law 전기통신사업법 19조</code> 로 원문 즉답)\n' +
  '🤖 <b>AI 자문</b> — <code>/ask 질문</code> (동향·시사점까지 종합, 운영자 최초 1회 승인 필요)';

// ── 조문 원문 조회 (비용 0) ──
const ARTICLE_RE = /^(.{2,40}?)\s*제?\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*$/;

// 약칭 → 정식 법령명. /law는 doc_name ilike 부분일치인데, "정보통신망법"처럼 정식명에
// 그 문자열이 통째로 들어 있지 않은 통칭은 전멸한다(첫 조회 실패 = 이탈). 조회 전에 치환한다.
// 키는 공백 제거형으로 저장 — 입력도 공백 제거 후 대조 ("개인정보 보호법"류 표기 흔들림 흡수).
const LAW_ALIASES: Record<string, string> = {
  '정보통신망법': '정보통신망 이용촉진 및 정보보호 등에 관한 법률',
  '망법': '정보통신망 이용촉진 및 정보보호 등에 관한 법률',
  '전기통신법': '전기통신사업법',            // 약칭 유입 대비 (정식명은 전기통신사업법)
  '개인정보보호법': '개인정보 보호법',        // 정식명은 띄어쓰기 포함
  '위치정보법': '위치정보의 보호 및 이용 등에 관한 법률',
  '단통법': '이동통신단말장치 유통구조 개선에 관한 법률',
  '단말기유통법': '이동통신단말장치 유통구조 개선에 관한 법률',
  '방발법': '방송통신발전 기본법',
  '방송통신발전법': '방송통신발전 기본법',
  '정보통신기반보호법': '정보통신기반 보호법',  // 정식명은 띄어쓰기 포함
  '통비법': '통신비밀보호법',
  '방통위설치법': '방송통신위원회의 설치 및 운영에 관한 법률',
  '방통위법': '방송통신위원회의 설치 및 운영에 관한 법률',
  'ICT특별법': '정보통신 진흥 및 융합 활성화 등에 관한 특별법',
  '정보통신융합법': '정보통신 진흥 및 융합 활성화 등에 관한 특별법',
  '지능정보화법': '지능정보화 기본법',
  'IPTV법': '인터넷 멀티미디어 방송사업법',
  '클라우드법': '클라우드컴퓨팅 발전 및 이용자 보호에 관한 법률',
};

// "정보통신망법 시행령"처럼 접미사가 붙어도 본체만 치환하고 접미사는 보존한다
// (시행령/시행규칙 조회의 기존 동작을 깨지 않기 위함 — 치환 후에도 ilike 부분일치는 그대로).
function resolveLawName(docName: string): string {
  const m = docName.match(/^(.*?)\s*(시행령|시행규칙)?$/);
  const base = (m?.[1] ?? docName).replace(/\s+/g, '');
  const suffix = m?.[2] ? ' ' + m[2] : '';
  // 라틴 약칭(ICT·IPTV)은 대소문자 표기가 흔들린다 — 대문자 정규화로 한 번 더 대조 (한글은 toUpperCase 무영향)
  const official = LAW_ALIASES[base] ?? LAW_ALIASES[base.toUpperCase()];
  return official ? official + suffix : docName;
}

const LAW_DAILY_LIMIT = 10;  // 자연어 /law 일일 상한 — 승인 불필요(팀 조회 기능), 운영자 지정 10회 (Haiku 건당 ~$0.01)

async function handleLawQuery(chatId: number, q: string): Promise<Promise<void> | void> {
  const query = q.trim();
  if (!query) {
    await sendTelegramHtml(BOT_TOKEN, chatId,
      '사용법: <code>/law 3G 종료 관련 법령</code> — 궁금한 주제를 그대로 쓰면 관련 법령·조항과 이유를 찾아 드립니다.\n' +
      '조문 번호를 알 때는 <code>/law 전기통신사업법 19조</code> 처럼 쓰면 원문이 바로 나옵니다.');
    return;
  }
  const m = query.match(ARTICLE_RE);
  if (m) { await handleArticleLookup(chatId, m[1].trim(), m[2], m[3]); return; }

  // 자연어 질의 → 법령 한정 답변 (2026-08-03 개편 — 운영자: "몇조가 뭐냐고 묻는 게 아니라
  // 궁금한 사항이 어떤 법과 관련돼 있는지 알고 싶은 게 대부분").
  // /ask와의 경계: 법령 내용만 — 뉴스·동향·시사점은 /ask 몫. 승인 불필요, 일일 상한만.
  const sub = await getSub(chatId);
  if (sub) {
    const today = todayKst();
    const used = sub.law_count_date === today ? (sub.law_count || 0) : 0;
    if (used >= LAW_DAILY_LIMIT) {
      await sendTelegramHtml(BOT_TOKEN, chatId, `⏳ 오늘 법령 검색 한도(${LAW_DAILY_LIMIT}회)를 모두 사용했습니다. 내일 다시 이용해 주세요.`);
      return;
    }
    await upsertSub(chatId, { law_count_date: today, law_count: used + 1 });
  }
  await sendTelegramHtml(BOT_TOKEN, chatId, '🔎 관련 법령을 찾고 있습니다... (약 20초)');

  // /ask와 같은 패턴 — webhook 200을 먼저 돌려보내고 백그라운드 실행 (텔레그램 재시도 방지)
  return (async () => {
    const typing = () => { tg('sendChatAction', { chat_id: chatId, action: 'typing' }); };
    typing();
    const typingTimer = setInterval(typing, 15_000);
    try {
      const answer = await answerLawQuery(sb, query);
      if (!answer) {
        await sendTelegramHtml(BOT_TOKEN, chatId,
          `🔎 "<b>${escapeHtml(query.slice(0, 60))}</b>" — 등재된 법령·고시에서 관련 조문을 찾지 못했습니다.\n` +
          '이 시스템 DB는 전파·통신 분야 법령 위주입니다.\n' +
          `🔗 <a href="https://www.law.go.kr/lsSc.do?query=${encodeURIComponent(query.slice(0, 50))}">국가법령정보센터에서 검색</a>`);
        return;
      }
      let html = mdToTelegramHtml(answer);
      html += '\n\n<i>📖 조문 원문은 <code>/law 법령명 N조</code> 로 바로 볼 수 있습니다 · 동향·시사점까지 필요하면 /ask</i>';
      for (const part of splitByLines(html)) await sendTelegramHtml(BOT_TOKEN, chatId, part);
    } catch (e) {
      console.error('[법령 검색 실패]', e);
      await sendTelegramHtml(BOT_TOKEN, chatId, '⚠️ 법령 검색 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.');
    } finally {
      clearInterval(typingTimer);
    }
  })();
}

async function handleArticleLookup(chatId: number, rawDocName: string, artNo: string, subNo?: string): Promise<void> {
  const docName = resolveLawName(rawDocName);   // 약칭이면 정식명으로 치환 후 조회 (미등재 안내·법령센터 링크도 정식명 기준)
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
    // 생성이 45~53초 걸리는데 텔레그램 typing 표시는 ~5초면 꺼진다 — 15초 간격으로 재전송해
    // "먹통 아님"을 계속 보여준다. 완료/실패 시 finally에서 반드시 중지.
    const typing = () => { tg('sendChatAction', { chat_id: chatId, action: 'typing' }); };
    typing();
    const typingTimer = setInterval(typing, 15_000);
    try {
      // 시스템 프롬프트는 app_config에서 읽는다 (원본은 루트 system_prompt.js — sync_system_prompt.py로 업로드).
      // 함수에 번들하지 않으므로 프롬프트 수정 시 재배포가 필요 없다.
      const { data: cfg } = await sb.from('app_config').select('value').eq('key', 'system_prompt').maybeSingle();
      const systemPrompt = (cfg?.value as string) || '';
      if (!systemPrompt) throw new Error('app_config.system_prompt 미등록 — python sync_system_prompt.py 실행 필요');
      const { answer, sources, webSources } = await answerAdvisory(sb, systemPrompt, q);
      let html = mdToTelegramHtml(answer);
      // 출처 표기 두 갈래 (2026-08-03 "참고가 전부 법령" 사고):
      //  🌐 = 모델이 본문에 실제 인용한 웹 문서(진짜 근거) — 수치·현황은 대개 여기서 온다
      //  📚 = 검색돼 프롬프트에 들어간 내부 자료 — 전부 반영됐다는 뜻이 아니므로 그렇게 적는다
      if (webSources.length) {
        const items = webSources.slice(0, 5).map((w) => {
          let host = ''; try { host = new URL(w.url).hostname.replace(/^www\./, ''); } catch { /* URL 파싱 실패 시 제목만 */ }
          return `<a href="${escapeHtml(w.url)}">${escapeHtml(w.title.slice(0, 60))}</a>${host ? ' (' + escapeHtml(host) + ')' : ''}`;
        });
        html += '\n\n<i>🌐 웹 출처: ' + items.join(' · ') + '</i>';
      }
      if (sources.length) html += '\n<i>📚 검색된 내부 자료(전부 반영된 것은 아님): ' + escapeHtml(sources.slice(0, 6).join(', ')) + '</i>';
      for (const part of splitByLines(html)) await sendTelegramHtml(BOT_TOKEN, chatId, part);
      // 기존 chat_logs에 기록 (source 컬럼이 없어 category로 구분 — 스키마 변경 없음)
      // 웹 출처는 '[웹] 제목 (url)' 접두사로 함께 남긴다 — splitSources() 관례(접두사 구분)와 동일
      const logSources = webSources.map((w) => `[웹] ${w.title} (${w.url})`).concat(sources).join(', ');
      await sb.from('chat_logs').insert({ question: q, answer, category: '텔레그램', sources: logSources });
    } catch (e) {
      console.error('[자문 실패]', e);
      // 쿼터 환불 — 선차감은 유지하되(동시성 안전) 실패 경로에서 -1 복원.
      // 실측(8/1): 5차감/2성공 — 환불이 없으면 실패가 일일 상한 20회를 갉아먹는다.
      try {
        const cur = await getSub(chatId);
        if (cur && cur.ai_count_date === today && cur.ai_count > 0) {
          await upsertSub(chatId, { ai_count: cur.ai_count - 1 });
        }
      } catch (re) { console.error('[쿼터 환불 실패]', re); }
      // 실패도 로그로 남겨 실패율 추적 가능하게 (성공과 같은 category='텔레그램', answer에 실패 표식)
      try {
        await sb.from('chat_logs').insert({
          question: q,
          answer: '[자문 실패] ' + String((e as Error)?.message ?? e).slice(0, 500),
          category: '텔레그램', sources: '',
        });
      } catch (le) { console.error('[실패 로그 기록 실패]', le); }
      await sendTelegramHtml(BOT_TOKEN, chatId, '⚠️ 자문 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.\n(이번 실패는 오늘 사용 횟수에서 차감되지 않습니다)');
    } finally {
      clearInterval(typingTimer);
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
    tags: [],   // 빈 배열 = 전체 수신 (DB 기본값과 동일)
  };

  const patch: Record<string, unknown> = {};
  if (data === 't:briefing') { patch.topic_briefing = !sub.topic_briefing; ack = patch.topic_briefing ? '모닝 브리핑 ON' : '모닝 브리핑 OFF'; }
  else if (data === 't:urgent') { patch.topic_urgent = !sub.topic_urgent; ack = patch.topic_urgent ? '주요 뉴스 ON' : '주요 뉴스 OFF'; }
  else if (data === 't:assembly') { patch.topic_assembly = !sub.topic_assembly; ack = patch.topic_assembly ? '법안 동향 ON' : '법안 동향 OFF'; }
  else if (data.startsWith('g:')) {
    // ── 관심분야 토글 ── 불리언 토글과 달리 배열 연산이라 3단계다.
    //  ① 빈 배열(=전체 수신)이면 먼저 6개 전체로 전개한다 — 그래야 "하나만 끄기"가 성립한다.
    //  ② 토글.
    //  ③ 결과가 6개면 다시 []로 정규화 — 캐논을 하나만 두면 나중에 태그가 늘어도 '전체' 구독자가 자동 수신.
    const slug = data.slice(2);
    if (!TAG_SLUGS.includes(slug)) { await tg('answerCallbackQuery', { callback_query_id: cb.id }); return; }
    // 주요 뉴스가 꺼져 있으면 태그 버튼은 화면에 없다. 그래도 옛 화면(스크롤 위 예전 메시지)에서
    // 누를 수 있으므로 서버에서도 막는다 — 안 막으면 "껐는데 설정이 바뀌는" 상태가 된다.
    if (!sub.topic_urgent) {
      await tg('answerCallbackQuery', {
        callback_query_id: cb.id, show_alert: true,
        text: '📡 주요 뉴스가 꺼져 있어 관심분야는 적용되지 않습니다.\n먼저 주요 뉴스를 켜 주세요.',
      });
      return;
    }
    const known = (sub.tags || []).filter((t) => TAG_SLUGS.includes(t));   // 폐기된 slug는 조용히 정리
    const cur = (sub.tags || []).length ? known : [...TAG_SLUGS];
    const next = cur.includes(slug) ? cur.filter((t) => t !== slug) : [...cur, slug];
    if (!next.length) {
      // 0개는 '아무것도 안 받음'인데 그건 토픽 OFF와 같은 상태다. 같은 결과를 두 가지 상태로
      // 표현하면 "어느 쪽으로 껐는지" 헷갈린다(구독 해지 버튼을 뺀 것과 같은 이유).
      await tg('answerCallbackQuery', {
        callback_query_id: cb.id, show_alert: true,
        text: '관심분야는 최소 1개가 켜져 있어야 합니다.\n전부 끄려면 📡 주요 뉴스를 끄세요.',
      });
      return;
    }
    patch.tags = next.length === TAG_SLUGS.length ? [] : TAG_SLUGS.filter((t) => next.includes(t));
    const label = NEWS_TAGS.find((t) => t.slug === slug)!.label;
    ack = next.includes(slug) ? `${label} 받기` : `${label} 제외`;
  }
  else if (data === 'd:daily') { patch.days = 'daily'; ack = '매일 받기로 변경'; }
  else if (data === 'd:weekday') { patch.days = 'weekday'; ack = '평일(월~금)만 받기로 변경'; }
  else if (data.startsWith('e:')) {
    // 종료 시각도 발송 기록을 건드리지 않는다 (h: 와 같은 이유 — 아래 주석 참조)
    patch.end_hour = Number(data.slice(2));
    ack = `받는 종료 시각 ${String(patch.end_hour).padStart(2, '0')}시로 변경`;
  }
  else if (data.startsWith('h:')) {
    // 발송 기록(last_briefing_sent_date)은 건드리지 않는다 (2026-08-03 재발송 사고).
    // 지우면 "이미 받은 날 + 새 시각이 이미 지남" 조합에서 다음 :25에 오늘분이 또 온다.
    // 안 지우면: 오늘 아직 안 받았으면 기록이 원래 오늘이 아니라 새 시각에 자연 수신,
    // 이미 받았으면 내일부터 새 시각 — 어느 쪽도 초기화가 필요 없다.
    patch.briefing_hour = Number(data.slice(2));
    // ack에 "내일부터"라고 못 박지 않는다 — 오늘분을 아직 안 받은 사람은 오늘 새 시각에 받는다.
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

// ── 재전송 차단 (#83) ──────────────────────────────────────────────────────
//  텔레그램은 웹훅이 60초 안에 200을 못 받으면 **같은 update_id로 재전송**한다.
//  /law·/ask는 답변 생성이 1~2분이라, 응답이 늦으면 같은 질문에 답이 여러 번 나갔다
//  (2026-08-04 실측: 웹훅 실행 45~56초가 상시 — 60초 문턱 바로 아래에서 돌고 있었다).
//  update_id는 업데이트마다 고유하므로 최초 1건만 통과시키면
//  **재전송은 막히고 새 질문(다른 update_id)은 그대로 지나간다.**
//  insert 실패(테이블 없음·DB 장애)는 통과시킨다 — 중복 몇 건이 무응답보다 낫다(fail-open).
async function claimUpdate(updateId: unknown, chatId?: number): Promise<boolean> {
  if (typeof updateId !== 'number') return true;      // update_id 없으면 판별 불가 → 통과
  try {
    const { data, error } = await sb.from('telegram_updates')
      .upsert({ update_id: updateId, chat_id: chatId ?? null }, { onConflict: 'update_id', ignoreDuplicates: true })
      .select('update_id');
    if (error) { console.error('[dedup] 조회 실패(통과 처리)', error); return true; }
    return (data?.length ?? 0) > 0;                   // 0행 = 이미 처리된 재전송
  } catch (e) {
    console.error('[dedup] 예외(통과 처리)', e);
    return true;
  }
}

// 2일 지난 기록 청소 — 1% 확률로만 돌려 매 요청 부담을 없앤다
function sweepUpdates(updateId: unknown): void {
  if (typeof updateId !== 'number' || updateId % 100 !== 0) return;
  const cutoff = new Date(Date.now() - 2 * 86400_000).toISOString();
  sb.from('telegram_updates').delete().lt('received_at', cutoff)
    .then(() => {}, (e: unknown) => console.error('[dedup] 청소 실패(무시)', e));
}

// ── 메인 ──
Deno.serve(async (req: Request) => {
  if (req.headers.get('x-telegram-bot-api-secret-token') !== WEBHOOK_SECRET || !WEBHOOK_SECRET) {
    return new Response('unauthorized', { status: 401 });
  }
  let update: Record<string, unknown>;
  try { update = await req.json(); } catch { return new Response('bad request', { status: 400 }); }

  const chatIdForClaim = ((update.message as { chat?: { id?: number } } | undefined)?.chat?.id)
    ?? ((update.callback_query as { message?: { chat?: { id?: number } } } | undefined)?.message?.chat?.id);
  if (!(await claimUpdate(update.update_id, chatIdForClaim))) {
    console.log('[dedup] 재전송 무시:', update.update_id);
    return new Response('ok');                        // 이미 처리한 업데이트 — 조용히 종료
  }
  sweepUpdates(update.update_id);

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
        text: '⚙️ <b>수신 설정</b>\n버튼을 눌러 바로 변경할 수 있습니다.\n✅⬜ = 여러 개 선택 · 🔵⚪ = 하나만 선택\n<i>항목을 모두 끄면 알림이 오지 않습니다.</i>\n\n🌙 <b>발송 시간대</b> — 모닝 브리핑은 <b>시작 시각</b>에 1회, 주요 뉴스·법안은 그 뒤 새로 생기는 대로 전달됩니다. <b>종료 시각을 넘기면 다음 날 시작 시각까지 발송하지 않습니다.</b>',
        reply_markup: settingsKeyboard(sub) });
    } else if (text === '/stop') {
      // 메뉴에서는 뺐지만 하위호환으로 남긴다 — '모든 항목 끄기'로 동작(설정·시각은 보존)
      await upsertSub(chatId, { topic_briefing: false, topic_urgent: false, topic_assembly: false });
      await sendTelegramHtml(BOT_TOKEN, chatId, '🔕 모든 알림을 껐습니다.\n/settings 에서 원하는 항목만 다시 켤 수 있습니다.\n(조문 조회·AI 자문은 계속 사용 가능)');
    } else if (text === '/admin') {
      await handleAdmin(chatId);
    } else if (text.startsWith('/law') || text.startsWith('/법령')) {
      const bg = await handleLawQuery(chatId, text.replace(/^\/(law|법령)\s*/, ''));
      if (bg) (globalThis as { EdgeRuntime?: { waitUntil: (p: Promise<void>) => void } }).EdgeRuntime?.waitUntil(bg);
    } else if (ARTICLE_RE.test(text) && !text.startsWith('/')) {
      await handleLawQuery(chatId, text);   // 평문 "전기통신사업법 19조" 자동 인식 (조번호 패턴 = 즉답 경로만)
    } else if (text.startsWith('/ask')) {
      const bg = await handleAsk(chatId, from, text.replace(/^\/ask\s*/, ''));
      if (bg) (globalThis as { EdgeRuntime?: { waitUntil: (p: Promise<void>) => void } }).EdgeRuntime?.waitUntil(bg);
    } else if (!text.startsWith('/')) {
      const bg = await handleAsk(chatId, from, text);   // 평문 질문 → 자문 경로 (승인 게이트가 비용 방어)
      if (bg) (globalThis as { EdgeRuntime?: { waitUntil: (p: Promise<void>) => void } }).EdgeRuntime?.waitUntil(bg);
    } else {
      await sendTelegramHtml(BOT_TOKEN, chatId, '알 수 없는 명령입니다.\n/settings 설정 · /law 법령검색 · /ask AI자문');
    }
  } catch (e) {
    // 어떤 오류도 200으로 마감 — 비200이면 텔레그램이 같은 업데이트를 재전송해 무한 반복된다
    console.error('[webhook 오류]', e);
  }
  return new Response('ok');
});
