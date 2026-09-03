// ============================================================================
//  Supabase Edge Function : admin-daily-report  (운영자 일일 리포트)
//
//  역할: 매일 09:00 KST(pg_cron `0 0 * * *` UTC), 구독자 목록과 구독자별 사용 통계를 운영자에게 텔레그램으로 보낸다.
//        (운영자 지시 2026-08-14 — "매일 관리자 계정으로 구독자 list 및 각 구독자가 한 작업들 통계")
//
//  발송 경로: 구독자 봇 토큰으로 **운영자 chat_id 에게만** 보낸다. 승인 요청이 이미 같은 경로로
//        가고 있어 시크릿을 새로 넣지 않아도 되고, 운영자 봇(푸시 전용)과 채널이 갈리지 않는다.
//
//  통계 원본: telegram_usage (2026-08-14 신설). 그 전에는 일일 카운터만 있어 매일 초기화됐다 —
//        이 표가 쌓이기 시작한 날부터의 이력만 나온다.
//
//  트리거: pg_cron → trigger_admin_report() → 이 함수 (x-cron-secret 검증).
//  Secrets: SUBSCRIBER_BOT_TOKEN / OPERATOR_CHAT_ID / ADMIN_REPORT_CRON_SECRET
// ============================================================================

import 'jsr:@supabase/functions-js/edge-runtime.d.ts';
import { createClient, type SupabaseClient } from 'jsr:@supabase/supabase-js@2';
import { escapeHtml, splitByLines, sendTelegramHtml } from '../_shared/telegram_format.ts';
import { NEWS_TAGS } from '../_shared/news_tags.ts';

const env = (k: string) => (Deno.env.get(k) || '').trim();
const BOT_TOKEN = env('SUBSCRIBER_BOT_TOKEN');
const OPERATOR_CHAT_ID = Number(env('OPERATOR_CHAT_ID') || '0');
const CRON_SECRET = env('ADMIN_REPORT_CRON_SECRET');
const RETENTION_DAYS = 180;

const sb: SupabaseClient = createClient(
  Deno.env.get('SUPABASE_URL')!,
  Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
);

type Sub = {
  chat_id: number; first_name: string | null; username: string | null;
  active: boolean; ai_allowed: boolean; law_allowed: boolean; unlimited?: boolean;
  briefing_hour: number; end_hour: number; days: string; created_at: string;
  topic_briefing: boolean; topic_urgent: boolean; topic_assembly: boolean;
  tags: string[] | null;
  last_briefing_sent_date: string | null;
  last_urgent_sent_at: string | null;
  last_assembly_sent_at: string | null;
};
type Usage = { chat_id: number; command: string; query: string | null; result_note: string | null; created_at: string };
type QueueRow = { topic: string; created_at: string };

const QUEUE_LABEL: Record<string, string> = {
  briefing: '모닝 브리핑', urgent: '주요 뉴스', assembly: '국회·법률 동향',
};

const CMD_LABEL: Record<string, string> = {
  assem: '국회발언', law: '법령검색', law_article: '조문조회', ask: 'AI자문',
  start: '가입', settings: '설정',
};

/** KST 기준 'YYYY-MM-DD'. Edge 런타임은 UTC 라 +9h 후 잘라 쓴다. */
function kstDate(d: Date): string {
  return new Date(d.getTime() + 9 * 3600 * 1000).toISOString().slice(0, 10);
}

/** 수신 설정 한 줄 — 무엇을 구독 중인지가 핵심이라 켜진 항목만 이름으로 적는다. */
function subscriptionLine(s: Sub): string {
  if (!s.active) return '수신 꺼짐';
  const on: string[] = [];
  if (s.topic_briefing) on.push('📡 브리핑');
  if (s.topic_urgent) on.push('📰 뉴스');
  if (s.topic_assembly) on.push('🏛 국회·법률');
  if (!on.length) return '수신 항목 없음(사실상 중지)';
  const hh = (v: number) => String(v).padStart(2, '0');
  const when = `${s.days === 'weekday' ? '평일' : '매일'} ${hh(s.briefing_hour)}~${hh(s.end_hour ?? 22)}시`;
  return `${on.join(' · ')} | ${when}`;
}

/** 관심분야 — 빈 배열은 '전체'가 캐논이므로 그렇게 표시한다(#설정 화면과 같은 규칙). */
function tagLine(s: Sub): string {
  if (!s.topic_urgent) return '';
  const tags = s.tags || [];
  if (!tags.length) return '관심분야 전체';
  const labels = tags.map((t) => NEWS_TAGS.find((n) => n.slug === t)?.label || t);
  return `관심분야 ${labels.join(', ')}`;
}

function buildReport(subs: Sub[], usage: Usage[], queue: QueueRow[], since7: Date): string {
  const today = kstDate(new Date());
  const yday = kstDate(new Date(Date.now() - 24 * 3600 * 1000));

  const byChat = new Map<number, Usage[]>();
  for (const u of usage) {
    const arr = byChat.get(u.chat_id) || [];
    arr.push(u);
    byChat.set(u.chat_id, arr);
  }

  const ydayRows = usage.filter((u) => kstDate(new Date(u.created_at)) === yday);
  const cmdCount = (rows: Usage[]) => {
    const m: Record<string, number> = {};
    for (const r of rows) m[r.command] = (m[r.command] || 0) + 1;
    return m;
  };
  const fmtCmds = (m: Record<string, number>) =>
    Object.entries(m).sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${CMD_LABEL[k] || k} ${v}`).join(', ') || '-';

  const act = subs.filter((s) => s.active).length;
  let out = `📊 <b>구독자 리포트</b> — ${today}\n` +
    `구독자 <b>${subs.length}명</b> (수신 켬 ${act}) · 어제 명령 <b>${ydayRows.length}건</b>\n` +
    `<i>어제 내역: ${escapeHtml(fmtCmds(cmdCount(ydayRows)))}</i>\n`;

  // ── 구독(푸시) 현황 ── 명령 사용과 별개로, 무엇을 받아 보고 있는지가 이 시스템의 본체다.
  const n = (f: (s: Sub) => boolean) => subs.filter((s) => s.active && f(s)).length;
  const ydayQ = queue.filter((q) => kstDate(new Date(q.created_at)) === yday);
  const qByTopic: Record<string, number> = {};
  for (const q of ydayQ) qByTopic[q.topic] = (qByTopic[q.topic] || 0) + 1;
  out += '\n<b>구독 현황</b> (수신 켠 사람 기준)\n' +
    `📡 모닝 브리핑 ${n((s) => s.topic_briefing)}명 · ` +
    `📰 주요 뉴스 ${n((s) => s.topic_urgent)}명 · ` +
    `🏛 국회·법률 동향 ${n((s) => s.topic_assembly)}명\n` +
    `어제 발송 대상 물량: ${
      Object.entries(qByTopic).map(([k, v]) => `${QUEUE_LABEL[k] || k} ${v}건`).join(' · ') || '없음'
    }\n`;

  // ── 구독자별 ──
  out += '\n<b>구독자별</b> (어제 / 최근 7일)\n';
  const sorted = subs.slice().sort((a, b) => {
    const ua = (byChat.get(a.chat_id) || []).length;
    const ub = (byChat.get(b.chat_id) || []).length;
    return ub - ua;
  });
  for (const s of sorted) {
    const mine = byChat.get(s.chat_id) || [];
    const mineYday = mine.filter((u) => kstDate(new Date(u.created_at)) === yday);
    const name = escapeHtml(s.first_name || '(이름없음)');
    const handle = s.username ? `@${escapeHtml(s.username)}` : `<code>${s.chat_id}</code>`;
    const perms = [s.ai_allowed ? '자문' : '', s.law_allowed ? '법령' : '', s.unlimited ? '무제한' : '']
      .filter(Boolean).join('·') || '기본';
    const last = mine.length
      ? kstDate(new Date(mine[0].created_at))
      : '없음';
    const tags = tagLine(s);
    // 마지막으로 실제 발송된 시점 — 구독은 켜 뒀는데 안 나가고 있는 사람을 잡아내는 지표.
    // 브리핑은 켜 두면 매일 같은 날짜가 찍혀 신호가 없다(운영자 지시 2026-08-14) — 뺀다.
    const sent = [
      s.last_urgent_sent_at ? `뉴스 ${kstDate(new Date(s.last_urgent_sent_at))}` : '',
      s.last_assembly_sent_at ? `국회·법률 ${kstDate(new Date(s.last_assembly_sent_at))}` : '',
    ].filter(Boolean).join(' · ') || '발송 이력 없음';
    out += `\n• <b>${name}</b> ${handle}\n` +
      `  수신 ${escapeHtml(subscriptionLine(s))}\n` +
      (tags ? `  ${escapeHtml(tags)}\n` : '') +
      `  최근 발송 ${escapeHtml(sent)}\n` +
      `  권한 ${escapeHtml(perms)} · 가입 ${escapeHtml((s.created_at || '').slice(0, 10))}\n` +
      `  명령 어제 ${mineYday.length}건 (${escapeHtml(fmtCmds(cmdCount(mineYday)))}) · ` +
      `7일 ${mine.length}건 · 마지막 ${escapeHtml(last)}\n`;
    // 어제 실제로 무엇을 물었는지 최대 3건 — 숫자만으로는 쓰임새를 알 수 없다.
    for (const u of mineYday.slice(0, 3)) {
      out += `    · ${escapeHtml(CMD_LABEL[u.command] || u.command)}: ` +
        `${escapeHtml((u.query || '').slice(0, 60))}` +
        `${u.result_note ? ` <i>(${escapeHtml(u.result_note)})</i>` : ''}\n`;
    }
  }

  if (!usage.length) {
    out += '\n<i>최근 7일 사용 이력이 없습니다. (이력 수집은 2026-08-14 시작 — 그 전 사용분은 남아 있지 않습니다)</i>\n';
  }
  out += `\n<i>집계 기간: ${escapeHtml(kstDate(since7))} ~ ${escapeHtml(today)} · 매일 09:00 발송</i>`;
  return out;
}

Deno.serve(async (req: Request) => {
  if (!CRON_SECRET || req.headers.get('x-cron-secret') !== CRON_SECRET) {
    return new Response('unauthorized', { status: 401 });
  }
  if (!OPERATOR_CHAT_ID) return new Response('OPERATOR_CHAT_ID 미설정', { status: 500 });

  try {
    const since7 = new Date(Date.now() - 7 * 24 * 3600 * 1000);
    const [{ data: subs }, { data: usage }, { data: queue }] = await Promise.all([
      sb.from('telegram_subscribers')
        .select('chat_id, first_name, username, active, ai_allowed, law_allowed, unlimited, ' +
                'briefing_hour, end_hour, days, created_at, tags, ' +
                'topic_briefing, topic_urgent, topic_assembly, ' +
                'last_briefing_sent_date, last_urgent_sent_at, last_assembly_sent_at')
        .order('created_at'),
      sb.from('telegram_usage')
        .select('chat_id, command, query, result_note, created_at')
        .gte('created_at', since7.toISOString())
        .order('created_at', { ascending: false }),
      sb.from('subscriber_queue')
        .select('topic, created_at')
        .gte('created_at', since7.toISOString()),
    ]);

    const html = buildReport((subs || []) as Sub[], (usage || []) as Usage[],
                             (queue || []) as QueueRow[], since7);
    // maxParts 기본값 3(≈11.7KB)이면 구독자가 20~25명을 넘을 때 뒷사람과 '집계 기간' 줄이 조용히 잘린다.
    // 운영자 1명에게만 가는 리포트라 조각이 늘어도 부담이 없어 8로 올린다.
    for (const part of splitByLines(html, 3900, 8)) await sendTelegramHtml(BOT_TOKEN, OPERATOR_CHAT_ID, part);

    // 보관 기간이 지난 이력 정리 — 리포트 잡이 겸한다(별도 cron 잡을 늘리지 않는다).
    const cutoff = new Date(Date.now() - RETENTION_DAYS * 24 * 3600 * 1000).toISOString();
    await sb.from('telegram_usage').delete().lt('created_at', cutoff);

    return new Response(JSON.stringify({ ok: true, subs: subs?.length ?? 0, usage: usage?.length ?? 0 }), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (e) {
    console.error('[admin-daily-report 실패]', e);
    // 실패를 조용히 삼키지 않는다 — 운영자에게 한 줄이라도 알린다.
    try {
      await sendTelegramHtml(BOT_TOKEN, OPERATOR_CHAT_ID,
        '⚠️ 구독자 리포트 생성 실패: ' + escapeHtml(String((e as Error)?.message ?? e).slice(0, 200)));
    } catch { /* 알림까지 실패하면 로그만 */ }
    return new Response('error', { status: 500 });
  }
});
