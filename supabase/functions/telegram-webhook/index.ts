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
import { parseAssemQuery, searchAssemblyWithFallback, attachContext, shortCommittee, type AssemQuery, type AssemKind } from '../_shared/assembly_search.ts';

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
  law_allowed: boolean;  // 자연어 /law 승인 여부 (2026-08-14) — 신규 가입자는 false, 그 전 가입자는 소급 허용
  unlimited?: boolean;   // 일일 한도 면제(#86) — /ask·/law 상한을 건너뛴다. 카운터는 계속 올려 사용량은 관찰 가능
  end_hour: number;      // 수신 종료 시각(18~22) — 종전 하드코딩 '23시 이후 무발송'을 대체 (2026-08-03)
  // 관심분야. **빈 배열 = 전체 수신**(캐논 하나). 6개를 다 켜면 []로 정규화하므로,
  // 나중에 7번째 태그가 생겨도 기존 '전체' 구독자가 자동으로 받는다.
  tags: string[];
}
async function getSub(chatId: number): Promise<Sub | null> {
  const { data } = await sb.from('telegram_subscribers').select('*').eq('chat_id', chatId).maybeSingle();
  return data as Sub | null;
}
/** 명령 사용 이력 기록 (2026-08-14). 실패해도 본 기능을 막지 않는다 — 통계는 부가 기능이다. */
async function logUsage(
  chatId: number, command: string, query = '', ok = true, note = '',
): Promise<void> {
  try {
    await sb.from('telegram_usage').insert({
      chat_id: chatId, command, ok,
      query: query.slice(0, 200) || null,
      result_note: note.slice(0, 120) || null,
    });
  } catch (e) { console.error('[usage 로그 실패(무시)]', e); }
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
  '📖 <b>법령 검색</b> — <code>/law 3G 종료 관련 법령</code> (궁금한 주제 → 관련 법령·조항과 이유. <b>운영자 최초 1회 승인 필요</b>)\n' +
  '   <i>조문 번호를 알면 승인 없이 바로 — <code>/law 전기통신사업법 19조</code></i>\n' +
  '🏛 <b>국회 발언 검색</b> — <code>assem 2019년 국정감사에서 김성수 의원이 무선국 관련 발언 찾아줘</code>\n' +
  '   <i>과방위 상임위·국정감사 회의록 원문에서 찾습니다(20대 국회~현재).</i>\n' +
  '🤖 <b>AI 자문</b> — <code>/ask 질문</code> (동향·시사점까지 종합, 운영자 최초 1회 승인 필요)\n' +
  // 대시보드 자문은 chatHistory를 누적해 대화가 이어지지만 봇은 질문 1건만 보낸다(rag.ts).
  // 웹을 써 본 사람일수록 "그건 언제 시행되나?" 식 후속 질문을 던지므로 가입 시점에 미리 알린다.
  // (답변 하단에도 같은 취지의 한 줄이 붙는다 — 첫 질문 전/후 양쪽에서 닿게)
  '   <i>질문마다 필요한 내용을 다 담아 주세요 — 앞의 질문은 기억하지 않습니다.</i>';

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

// ── /assem 국회 발언 검색 (국회회의록시스템 실시간 검색, AI 비용 0) ──
// 검색 로직·위원회 코드는 _shared/assembly_search.ts 한 곳에만 둔다(대시보드와 공유).
const ASSEM_MAX_HITS = 5;       // 한 번에 보여줄 발언 수

/** 검색 스니펫의 <!HS>…<!HE> 강조 마커를 텔레그램 <b>로. 이스케이프 뒤에 치환해야 안전하다. */
function assemSnippet(raw: string): string {
  return escapeHtml(raw || '')
    .replaceAll('&lt;!HS&gt;', '<b>').replaceAll('&lt;!HE&gt;', '</b>');
}

/** '더 보기' 버튼에 실어 보낼 검색 조건. 텔레그램 callback_data 는 **64바이트 상한**이라
 *  한글(3바이트)이 길면 담기지 않는다 — 그럴 땐 버튼을 달지 않는다(대신 결과에 안내를 남긴다). */
function assemCallbackData(q: AssemQuery, offset: number): string | null {
  const kinds = (q.kinds || []).map((k) => (k === '국정감사' ? 'a' : 's')).join('');
  const d = `as|${offset}|${q.year || ''}|${kinds}|${q.speaker || ''}|${q.query}`;
  return new TextEncoder().encode(d).length <= 64 ? d : null;
}

function parseAssemCallback(data: string): { q: AssemQuery; offset: number } | null {
  const p = data.split('|');
  if (p[0] !== 'as' || p.length < 6) return null;
  const kinds = p[3]
    ? ([...p[3]].map((c) => (c === 'a' ? '국정감사' : '상임위')) as AssemKind[])
    : undefined;
  return {
    offset: Number(p[1]) || 0,
    q: {
      speaker: p[4] || '',
      query: p.slice(5).join('|'),
      year: p[2] ? Number(p[2]) : undefined,
      kinds,
    },
  };
}

async function handleAssemSearch(chatId: number, arg: string): Promise<void> {
  const text = arg.trim();
  if (!text) {
    await sendTelegramHtml(BOT_TOKEN, chatId,
      '사용법: <code>assem 2019년 국정감사에서 김성수 의원이 무선국 관련해서 발언한 내용을 찾아줘</code>\n' +
      '평소 말하듯 쓰시면 의원명·연도·회의 구분을 알아서 골라냅니다. ' +
      '<code>assem 김성수 무선국</code> 처럼 짧게 써도 됩니다.\n' +
      '<i>범위: 20대 국회(2016)~현재, 과방위(20대 전반기 미방위 포함)의 상임위·국정감사 회의록.</i>');
    return;
  }

  let parsed: AssemQuery;
  try {
    parsed = await parseAssemQuery(text, Deno.env.get('ANTHROPIC_API_KEY') || '');
  } catch (e) {
    console.error('[assem 파싱 실패]', e);
    await sendTelegramHtml(BOT_TOKEN, chatId, '⚠️ 질의 해석에 실패했습니다. 잠시 후 다시 시도해 주세요.');
    await logUsage(chatId, 'assem', text, false, '파싱 실패');
    return;
  }
  if (!parsed.query) {
    await sendTelegramHtml(BOT_TOKEN, chatId,
      '🔍 무엇을 찾을지 알아내지 못했습니다.\n<code>assem 김성수 의원 무선국</code> 처럼 ' +
      '<b>찾을 낱말</b>을 넣어 주세요.');
    await logUsage(chatId, 'assem', text, false, '핵심어 미추출');
    return;
  }
  await sendAssemResults(chatId, parsed, 0);
}

/** 검색 실행 + 결과 전송. '더 보기'(offset>0)도 같은 함수를 탄다. */
async function sendAssemResults(chatId: number, q: AssemQuery, offset: number): Promise<void> {
  let result;
  let parsed = q;
  try {
    result = await searchAssemblyWithFallback(q, ASSEM_MAX_HITS, 20_000, offset);
    parsed = result.parsed;   // 재시도로 해석이 바뀌었으면 조건 표시도 실제 쓰인 해석으로 맞춘다
    // 첫 묶음의 1건만 뷰어 원문으로 전문 + 정부측 답변까지 붙인다(+2~3초, AI 비용 0).
    // 텔레그램은 메시지 길이 제한이 있어 대시보드보다 짧게 자른다(블록당 600자, 뒤 3블록).
    if (offset === 0) await attachContext(result, 1, 1, 3, 600);
  } catch (e) {
    console.error('[assem 검색 실패]', e);
    await sendTelegramHtml(BOT_TOKEN, chatId, '⚠️ 국회 회의록 시스템 조회에 실패했습니다. 잠시 후 다시 시도해 주세요.');
    return;
  }

  // 해석 결과를 그대로 보여준다 — 자연어 파싱이 빗나갔을 때 사용자가 바로 알아채고 고쳐 쓸 수 있게.
  const cond = [
    parsed.speaker ? `${parsed.speaker} 의원` : '발언자 무관',
    `“${parsed.query}”`,
    parsed.year ? `${parsed.year}년` : '',
    parsed.dae ? `${parsed.dae}대 국회` : '',   // 대수는 실제 검색 범위를 좁힌다 — 안 찍으면 먹혔는지 알 수 없다
    parsed.daeOut ? `⚠️${parsed.daeOut}대는 범위 밖(20대~)` : '',
    parsed.kinds?.length ? parsed.kinds.join('·') : '',
  ].filter(Boolean).join(' · ');

  if (!result.hits.length) {
    await sendTelegramHtml(BOT_TOKEN, chatId,
      `🔍 ${escapeHtml(cond)} — 결과가 없습니다.\n` +
      '<i>회의록 원문에 나온 낱말 그대로여야 찾힙니다(예: 전파사용료, 무선국 검사). ' +
      '이름 표기나 연도를 빼고 다시 시도해 보세요.</i>');
    return;
  }

  if (offset === 0) {
    await logUsage(chatId, 'assem',
      [parsed.speaker, parsed.query, parsed.year, parsed.dae ? `${parsed.dae}대` : '']
        .filter(Boolean).join(' '),
      true, `${result.total}건`);
  }
  const from = offset + 1;
  const to = offset + result.hits.length;
  let html = `🔍 <b>${escapeHtml(cond)}</b> — 전체 <b>${result.total}</b>건` +
    (result.total > result.hits.length ? ` (최신순 ${from}~${to}번째)` : '') + '\n';
  // 재시도로 조건을 푼 결과라면 반드시 알린다 — 건수가 크면 사용자는 그걸 신뢰의 근거로 읽는다.
  if (result.retried) html += `<i>원래 조건으로는 결과가 없어 <b>${escapeHtml(parsed.query)}</b>(으)로 다시 찾은 결과입니다.</i>\n`;
  for (const h of result.hits) {
    html += `\n📅 <b>${escapeHtml(h.date)}</b> · ${escapeHtml(h.kind)} · ${escapeHtml(shortCommittee(h.committee).slice(0, 30))}\n` +
      `👤 ${escapeHtml(h.speaker)}\n`;
    if (h.context?.length) {
      // 문맥이 있으면 스니펫(206자 절단본) 대신 전문·앞뒤를 보여준다 — 질의와 답변이 짝지어 보이게.
      for (const b of h.context) {
        const who = escapeHtml(b.name + (b.pos ? `(${b.pos})` : ''));
        const body = escapeHtml(b.text).replaceAll('\n', '\n');
        html += b.isTarget
          ? `\n▶ <b>${who}</b>\n${body}\n`
          : `\n▸ <i>${who}</i>\n${body}\n`;
      }
    } else {
      html += `${assemSnippet(h.snippet)}\n`;
    }
    html += (h.url ? `<a href="${h.url}">회의록 원문 보기</a>\n` : '');
  }
  html += '\n<i>출처: 국회회의록시스템 실시간 검색 (20대~현재 과방위 상임위·국정감사)</i>';

  const parts = splitByLines(html);
  for (const part of parts.slice(0, -1)) await sendTelegramHtml(BOT_TOKEN, chatId, part);

  // 마지막 메시지에만 '더 보기' 버튼을 붙인다. 국회 검색 페이지 상한(120건)까지만 넘긴다.
  const nextOffset = offset + result.hits.length;
  const more = result.total > nextOffset && nextOffset < 120
    ? assemCallbackData(parsed, nextOffset) : null;
  const last = parts[parts.length - 1];
  if (more) {
    await tg('sendMessage', {
      chat_id: chatId, parse_mode: 'HTML', text: last, disable_web_page_preview: true,
      reply_markup: { inline_keyboard: [[{
        text: `▼ 다음 ${Math.min(ASSEM_MAX_HITS, result.total - nextOffset)}건 더 보기 (${nextOffset}/${result.total})`,
        callback_data: more,
      }]] },
    });
  } else {
    await sendTelegramHtml(BOT_TOKEN, chatId, last);
    if (result.total > nextOffset) {
      await sendTelegramHtml(BOT_TOKEN, chatId,
        `<i>결과가 ${result.total}건으로 많습니다. 연도나 의원명을 붙여 좁혀 보세요 — 예: ` +
        `<code>assem 2024년 ${escapeHtml(parsed.query)}</code></i>`);
    }
  }
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
  // /ask와의 경계: 법령 내용만 — 뉴스·동향·시사점은 /ask 몫.
  // 승인제 + 일일 상한 (2026-08-14): Haiku 건당 ~25원이라 인원이 늘면 비용이 선형으로 늘어난다.
  // **신규 가입자만** 승인 대상 — 그 전 가입자는 마이그레이션에서 law_allowed=true 로 소급 허용했다.
  // 조문번호 직답(위 ARTICLE_RE 분기)은 DB 조회뿐이라 이 게이트를 타지 않는다.
  const sub = await getSub(chatId);
  // fail-closed. `sub && !sub.law_allowed`로 두면 **구독 행이 없는 계정**(=/start를 거치지 않고 곧장
  // /law를 보낸 경우)이 게이트·일일 한도·사용 로깅을 전부 우회한다. /ask와 같은 `!sub?.x` 형태로 맞춘다.
  if (!sub?.law_allowed) {
    await sendTelegramHtml(BOT_TOKEN, chatId,
      '🔒 법령 검색은 운영자 승인이 필요합니다(최초 1회만).\n승인 요청을 보냈습니다 — 승인되면 다시 질문해 주세요.\n' +
      '<i>조문 번호를 아는 경우엔 승인 없이도 쓸 수 있습니다 — 예: <code>/law 전기통신사업법 19조</code></i>');
    await logUsage(chatId, 'law', query, false, '승인대기');
    if (OPERATOR_CHAT_ID) {
      await tg('sendMessage', {
        chat_id: OPERATOR_CHAT_ID, parse_mode: 'HTML',
        text: `📖 <b>법령 검색 권한 요청</b>\n${escapeHtml(sub?.first_name || '')} (@${escapeHtml(sub?.username || '없음')}, <code>${chatId}</code>)\n첫 질문: ${escapeHtml(query.slice(0, 200))}`,
        reply_markup: { inline_keyboard: [[
          { text: '✅ 승인', callback_data: `law:ok:${chatId}` },
          { text: '❌ 거부', callback_data: `law:no:${chatId}` },
        ]] },
      });
    }
    return;
  }
  if (sub) {
    const today = todayKst();
    const used = sub.law_count_date === today ? (sub.law_count || 0) : 0;
    if (!sub.unlimited && used >= LAW_DAILY_LIMIT) {   // unlimited 면제(#86)
      await sendTelegramHtml(BOT_TOKEN, chatId, `⏳ 오늘 법령 검색 한도(${LAW_DAILY_LIMIT}회)를 모두 사용했습니다. 내일 다시 이용해 주세요.`);
      return;
    }
    await upsertSub(chatId, { law_count_date: today, law_count: used + 1 });
    await logUsage(chatId, 'law', query);
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

// ── 조문 원문을 텔레그램에서 읽히게 다듬는다 (#92 후속) ─────────────────────────
// `/law`는 원문을 **그대로** 보여주는 명령이라, OCR로 되살린 조문(#91)의 마크다운 표가
// 날것으로 노출됐다 — `|---|---|` 구분선, `<br>`, 보존용 HTML 주석까지 화면에 찍혔다.
// 자문(`/ask`)은 모델이 읽고 문장으로 풀어 주므로 문제가 없었고, 그래서 못 봤다.
// 표를 텔레그램에서 표로 보여줄 방법은 없다(고정폭 폰트가 아니다) — **노이즈만 걷어내고
// 행 단위로 읽히게** 한다. 원문 자체는 DB에 그대로 두고 표시할 때만 손댄다.
// ★ 치환 순서가 중요하다: **표 행을 먼저** 처리한 뒤 `<br>`을 푼다.
//   `<br>`을 먼저 개행으로 바꾸면 한 행이 여러 줄로 쪼개져 표 행 정규식이 더는 맞지 않는다.
export function plainifyArticle(text: string): string {
  return (text || '')
    .replace(/<!--[\s\S]*?-->/g, '')            // 원본 이미지 보존 주석 — 사람이 볼 것이 아니다
    .replace(/\*\*(.+?)\*\*/g, '$1')            // 굵게 표시는 이스케이프되면 별표만 남는다
    .replace(/^\s*\|[\s|:-]*\|\s*$/gm, '')      // 마크다운 표 구분선(|---|---|) 행 삭제
    .replace(/^[ \t]*\|(.*)\|[ \t]*$/gm, (_m, row) => {
      const cells = String(row).split('|').map((c: string) => c.trim()).filter((c: string) => c);
      if (cells.length <= 1) return cells.join('');
      const [head, ...vals] = cells;
      // 항목 셀이 여러 줄짜리(<br> 포함)면 값을 아래 줄에 '→'로 붙인다 — 끝에 매달리면 안 읽힌다
      return /<br\s*\/?>/i.test(head)
        ? `${head}<br>   → ${vals.join('  ·  ')}`
        : cells.join('  ·  ');
    })
    .replace(/<br\s*\/?>/gi, '\n   ')            // 셀 안 줄바꿈 → 들여쓴 새 줄
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

async function handleArticleLookup(chatId: number, rawDocName: string, artNo: string, subNo?: string): Promise<void> {
  await logUsage(chatId, 'law_article', `${rawDocName} ${artNo}조${subNo ? '의' + subNo : ''}`);
  const docName = resolveLawName(rawDocName);   // 약칭이면 정식명으로 치환 후 조회 (미등재 안내·법령센터 링크도 정식명 기준)
  // ⚠️ DB의 article_no는 **「12조(교육과목 및 시간)」처럼 '제'가 없는 형식**이다(#92).
  // 실측: `article_no like '제%조%'` 0건 / `~ '^\d+조'` 7,587건. 종전에는 `제${artNo}조`로
  // 조회해 **번호 직접 조회가 한 번도 동작하지 않았다** — 안내문에는 "조문 원문이 바로 나옵니다"라고
  // 적혀 있었고, 자연어 질의는 AI 검색 경로라 멀쩡해서 아무도 눈치채지 못했다.
  // 표기가 바뀔 가능성에 대비해 **두 형식을 모두** 조회한다(현재 DB에는 뒤쪽만 존재).
  const wantedDb = `${artNo}조` + (subNo ? `의${subNo}` : '');   // DB 저장 형식
  const wanted = `제${wantedDb}`;                                 // 사람이 읽는 표기(메시지용)
  const { data } = await sb.from('document_chunks')
    .select('id, doc_name, article_no, content, notice_no, effective_date, chunk_index')
    .eq('is_approved', true).eq('status', 'current')
    .ilike('doc_name', `%${docName}%`)
    .or(`article_no.ilike.${wantedDb}%,article_no.ilike.제${wantedDb}%`)
    .order('chunk_index').limit(30);
  // "19조" 요청 시 "19조의2"가 딸려오는 것 방지 — 의N 요청이 아니면 '의'로 이어지는 조는 제외.
  // 비교 전에 앞의 '제'를 벗겨 두 형식을 같은 자리에서 다룬다.
  const rows = ((data || []) as { id: number; doc_name: string; article_no: string; content: string; notice_no?: string; effective_date?: string }[])
    .filter((r) => {
      const a = (r.article_no || '').split('(')[0].replace(/\s/g, '').replace(/^제/, '');
      return subNo ? a.startsWith(wantedDb) : (a === wantedDb || a.startsWith(wantedDb + '('));
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
  body += '\n' + escapeHtml(plainifyArticle(picked.map((r) => r.content).join('\n')));
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
  // 일일 상한 — unlimited=true인 구독자는 면제(#86). 카운터는 계속 올린다(사용량 관찰용).
  const today = todayKst();
  const used = sub.ai_count_date === today ? sub.ai_count : 0;
  if (!sub.unlimited && used >= AI_DAILY_LIMIT) {
    await sendTelegramHtml(BOT_TOKEN, chatId, `⏳ 오늘 자문 한도(${AI_DAILY_LIMIT}회)를 모두 사용했습니다. 내일 다시 이용해 주세요.`);
    return;
  }
  await upsertSub(chatId, { ai_count_date: today, ai_count: used + 1 });
  await logUsage(chatId, 'ask', q);
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
      // 대화 미유지 고지(#86) — 봇은 질문 1건만 모델에 보낸다(rag.ts `messages: [{role:'user'}]`).
      // 대시보드 자문은 chatHistory를 누적해 이어지므로, 웹을 써 본 사람일수록 "그건 언제 시행되나?"
      // 같은 후속 질문을 던지고 엉뚱한 답을 받는다. 답을 읽은 직후 = 후속 질문을 쓰기 직전이라
      // 이 자리가 가장 잘 닿는다. /law에는 붙이지 않는다(애초에 한 건씩 찾는 용도).
      html += '\n<i>💡 이어지는 질문은 기억하지 않습니다 — 질문마다 필요한 내용을 다 담아 주세요.</i>';
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
  const { data } = await sb.from('telegram_subscribers').select('chat_id, first_name, username, active, ai_allowed, law_allowed').order('created_at');
  const rows = (data || []) as { chat_id: number; first_name?: string; username?: string; active: boolean; ai_allowed: boolean; law_allowed: boolean }[];
  const total = rows.length, act = rows.filter((r) => r.active).length;
  const allowed = rows.filter((r) => r.ai_allowed);
  const lawAllowed = rows.filter((r) => r.law_allowed);
  const label = (r: { first_name?: string; username?: string; chat_id: number }) =>
    `${r.first_name || ''} @${r.username || r.chat_id}`;
  let text = `🛠 <b>구독자 현황</b> — 총 ${total}명 (활성 ${act})\n\n` +
    `<b>AI 자문 승인자</b> (${allowed.length}명)${allowed.length ? '' : '\n(없음)'}\n` +
    `<b>법령 검색 승인자</b> (${lawAllowed.length}명)${lawAllowed.length ? '' : '\n(없음)'}`;
  // 두 권한을 한 화면에서 회수할 수 있게 버튼을 나눠 붙인다(라벨에 어느 권한인지 표기).
  const kb = [
    ...allowed.map((r) => ([{ text: `🚫 자문 회수: ${label(r)}`, callback_data: `ai:rv:${r.chat_id}` }])),
    ...lawAllowed.map((r) => ([{ text: `🚫 법령 회수: ${label(r)}`, callback_data: `law:rv:${r.chat_id}` }])),
  ];
  await tg('sendMessage', { chat_id: chatId, parse_mode: 'HTML', text, reply_markup: { inline_keyboard: kb } });
}

// ── callback_query 처리 ──
async function handleCallback(cb: { id: string; data?: string; from: { id: number }; message?: { chat: { id: number }; message_id: number } }): Promise<void> {
  const data = cb.data || '';
  const chatId = cb.message?.chat.id || cb.from.id;
  const msgId = cb.message?.message_id;
  let ack = '저장했습니다';

  if (data.startsWith('as|')) {
    // 국회 발언 검색 '더 보기' — 다음 묶음을 새 메시지로 보낸다(원 메시지는 그대로 둔다).
    const p = parseAssemCallback(data);
    await tg('answerCallbackQuery', { callback_query_id: cb.id, text: p ? '불러오는 중…' : '만료된 버튼' });
    if (p) await sendAssemResults(chatId, p.q, p.offset);
    return;
  }

  if (data.startsWith('law:')) {
    // 법령 검색 승인/거부/회수 — 운영자 채팅에서 온 콜백만 유효 (2026-08-14)
    const [, action, target] = data.split(':');
    const targetId = Number(target);
    if (cb.from.id !== OPERATOR_CHAT_ID) { await tg('answerCallbackQuery', { callback_query_id: cb.id, text: '권한 없음' }); return; }
    if (action === 'ok') {
      await upsertSub(targetId, { law_allowed: true });
      await sendTelegramHtml(BOT_TOKEN, targetId, '✅ 법령 검색 권한이 승인되었습니다!\n<code>/law 3G 종료 관련 법령</code> 처럼 이용하세요.');
      ack = '승인 완료';
    } else if (action === 'no') {
      await sendTelegramHtml(BOT_TOKEN, targetId, '❌ 법령 검색 권한 요청이 거부되었습니다.\n(조문 번호 직답과 국회 발언 검색은 계속 사용 가능)');
      ack = '거부 처리';
    } else if (action === 'rv') {
      await upsertSub(targetId, { law_allowed: false });
      await sendTelegramHtml(BOT_TOKEN, targetId, '🔒 법령 검색 권한이 회수되었습니다.');
      ack = '회수 완료';
    }
    // 승인/거부 요청 메시지의 버튼만 지운다. 회수(rv)는 /admin 목록에서 눌리는데, 여기서 키보드를
    // 통째로 비우면 남은 다른 사람의 회수 버튼까지 사라져 /admin을 다시 쳐야 한다.
    if (msgId && action !== 'rv') await tg('editMessageReplyMarkup', { chat_id: chatId, message_id: msgId, reply_markup: { inline_keyboard: [] } });
    await tg('answerCallbackQuery', { callback_query_id: cb.id, text: ack });
    return;
  }

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
      await logUsage(chatId, 'start', from.username || from.first_name || '');
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
    } else if (/^\/?(assem|어셈|발언검색)(\s|$)/i.test(text)) {
      // 슬래시 없이 'assem …' 로도 받는다 — 운영자가 쓰는 형태가 그렇다(2026-08-14 지시).
      // 평문 catch-all(/ask)보다 **먼저** 걸러야 자문 경로로 새지 않는다.
      await handleAssemSearch(chatId, text.replace(/^\/?(assem|어셈|발언검색)\s*/i, ''));
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
      await sendTelegramHtml(BOT_TOKEN, chatId, '알 수 없는 명령입니다.\n/settings 설정 · /law 법령검색 · /ask AI자문 · assem 국회 발언검색');
    }
  } catch (e) {
    // 어떤 오류도 200으로 마감 — 비200이면 텔레그램이 같은 업데이트를 재전송해 무한 반복된다
    console.error('[webhook 오류]', e);
  }
  return new Response('ok');
});
