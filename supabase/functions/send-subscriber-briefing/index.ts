// ============================================================================
//  Supabase Edge Function : send-subscriber-briefing  (구독자 정시 발송)
//
//  역할: 매시(pg_cron `subscriber-briefing-hourly`, 25분) 실행되어, 구독자가 고른
//        수신 시각(briefing_hour)에 아래 3종을 **한 번에 모아** 보낸다.
//          📡 모닝 브리핑     — 오늘자 daily_briefings
//          🚨 긴급 뉴스       — 지난 발송 이후 큐(subscriber_queue)에 쌓인 건
//          🏛️ 법안 동향       — 위와 동일
//
//  왜 큐인가: 긴급 재알림 억제·클러스터링(#44)과 법안 상태변경 판정은 Python 크롤러에
//  이미 있다. 판정 결과(HTML)만 subscriber_queue에 적재하고 발송 시점만 여기서 정한다.
//
//  핵심 설계
//   - briefing_hour <= 현재KST시  (= 아님): 브리핑이 늦게 생성돼도(06:20 재시도·PC 백업)
//     다음 정각에 자동으로 따라잡는다. 06:00 생성 레이스 해결.
//   - 중복 방지: 브리핑=last_briefing_sent_date(1일 1회), 긴급·법안=last_*_sent_at
//     (그 시점 이후 큐 항목만) → cron 재시도·중복 트리거에도 안전.
//   - 발송할 게 하나도 없으면 아무것도 보내지 않는다(조용).
//   - system_health 하트비트 기록 → 조용한 실패 감시(지침 운영 원칙).
//
//  보안: x-cron-secret == CRON_SECRET (Vault `subscriber_cron_secret`와 동일값).
// ============================================================================

import 'jsr:@supabase/functions-js/edge-runtime.d.ts';
import { createClient } from 'jsr:@supabase/supabase-js@2';
import { briefingToTelegramHtml, splitByLines, sendTelegramHtml, DASHBOARD_URL, escapeHtml } from '../_shared/telegram_format.ts';

// env는 반드시 trim — 콘솔 붙여넣기 시 줄바꿈이 섞이면 시크릿 비교가 조용히 어긋난다(401)
const env = (k: string) => (Deno.env.get(k) || '').trim();

const BOT_TOKEN = env('SUBSCRIBER_BOT_TOKEN');
const CRON_SECRET = env('CRON_SECRET');
const NONEWS_PREFIX = '🕊️ (신규 뉴스 없음';   // morning_briefing.py _NONEWS_PREFIX 와 일치
const QUEUE_LOOKBACK_H = 48;                  // 큐 조회 범위(시간) — 그 이전 건은 오래돼서 보내지 않음

const sb = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!);

// 운영자 텔레그램 발송과 동일 규칙: [ID:xxx] 태그 제거 + SKT 영향 분석 줄 제외
// (morning_briefing.py 665-669 미러 — 이메일만 분석 포함이라는 채널 정책 유지)
function cleanBriefing(content: string): string {
  return content
    .replace(/\s*\[ID:[^\]]+\]/g, '')
    .split('\n').filter((l) => !l.includes('SKT 영향 분석')).join('\n');
}

function kstNow(): { date: string; hour: number; dow: number; dayStartMs: number } {
  const k = new Date(Date.now() + 9 * 3600 * 1000);
  const dayStartMs = Date.UTC(k.getUTCFullYear(), k.getUTCMonth(), k.getUTCDate()) - 9 * 3600 * 1000;
  return { date: k.toISOString().slice(0, 10), hour: k.getUTCHours(), dow: k.getUTCDay(), dayStartMs };
}

interface Sub {
  chat_id: number;
  days: string;
  topic_briefing: boolean; topic_urgent: boolean; topic_assembly: boolean;
  briefing_hour: number;
  last_briefing_sent_date: string | null;
  last_urgent_sent_at: string | null;
  last_assembly_sent_at: string | null;
}
interface QueueRow { id: number; topic: string; html: string; created_at: string }

Deno.serve(async (req: Request) => {
  if (!CRON_SECRET || req.headers.get('x-cron-secret') !== CRON_SECRET) {
    return new Response('unauthorized', { status: 401 });
  }
  const { date, hour, dow, dayStartMs } = kstNow();
  const isWeekday = dow >= 1 && dow <= 5;
  let sent = 0, failed = 0;

  try {
    // ── 수신 시각이 도래한 구독자 ──
    let q = sb.from('telegram_subscribers')
      .select('chat_id, days, topic_briefing, topic_urgent, topic_assembly, briefing_hour, last_briefing_sent_date, last_urgent_sent_at, last_assembly_sent_at')
      .eq('active', true).lte('briefing_hour', hour);
    if (!isWeekday) q = q.eq('days', 'daily');   // 주말은 '매일' 설정자만
    const subs = ((await q).data || []) as Sub[];
    if (!subs.length) {
      return new Response(JSON.stringify({ ok: true, date, hour, sent: 0, reason: 'no due subscriber' }), { headers: { 'Content-Type': 'application/json' } });
    }

    // ── 오늘 브리핑 (없으면 브리핑만 건너뛰고 긴급·법안은 계속 진행) ──
    const { data: br } = await sb.from('daily_briefings')
      .select('content, created_at').eq('briefing_date', date).maybeSingle();
    let briefingParts: string[] | null = null;
    if (br?.content) {
      const content = br.content as string;
      const html = content.trimStart().startsWith(NONEWS_PREFIX)
        ? `🕊️ <b>${escapeHtml(date)}</b> — 신규 전파정책 뉴스가 없습니다.\n<i>수집 시스템은 정상 동작 중입니다.</i>`
        : briefingToTelegramHtml(cleanBriefing(content));
      const madeAt = br.created_at
        ? new Date(new Date(br.created_at as string).getTime() + 9 * 3600 * 1000).toISOString().slice(11, 16)
        : '06:05';
      briefingParts = splitByLines(html);
      // 기준 시각 명시 — 브리핑은 하루 1회(06시경) 생성이고 수신 시각은 '배달 시각'일 뿐이라,
      // 늦게 받는 사람이 "그 사이 뉴스가 빠졌다"고 오해할 수 있다(내일 브리핑에 포함됨).
      briefingParts[briefingParts.length - 1] +=
        `\n\n<i>※ 오늘 ${madeAt} 기준으로 작성된 브리핑입니다. 이후 소식은 내일 브리핑에 포함됩니다.</i>` +
        `\n📊 <a href="${DASHBOARD_URL}">대시보드에서 전문 보기</a>`;
    }

    // ── 큐(긴급·법안) — 최근 48시간분만 한 번 읽고 구독자별로 시점 필터 ──
    const sinceIso = new Date(Date.now() - QUEUE_LOOKBACK_H * 3600 * 1000).toISOString();
    const { data: qdata } = await sb.from('subscriber_queue')
      .select('id, topic, html, created_at').gte('created_at', sinceIso).order('created_at');
    const queue = (qdata || []) as QueueRow[];

    const pickQueue = (topic: string, lastSent: string | null): QueueRow[] => {
      // 첫 발송(기록 없음)은 오늘 00:00(KST) 이후 건만 — 가입 직후 이틀치가 쏟아지는 것 방지
      const fromMs = lastSent ? new Date(lastSent).getTime() : dayStartMs;
      return queue.filter((r) => r.topic === topic && new Date(r.created_at).getTime() > fromMs);
    };

    const nowIso = new Date().toISOString();
    for (const s of subs) {
      const msgs: string[] = [];

      if (s.topic_briefing && briefingParts && s.last_briefing_sent_date !== date) {
        msgs.push(...briefingParts);
      }
      const urgent = s.topic_urgent ? pickQueue('urgent', s.last_urgent_sent_at) : [];
      const assembly = s.topic_assembly ? pickQueue('assembly', s.last_assembly_sent_at) : [];
      for (const grp of [urgent, assembly]) {
        if (!grp.length) continue;
        // 같은 토픽의 여러 건은 한 메시지로 합치되, 길면 분할 (알림 개수 폭증 방지 — #44 취지)
        for (const part of splitByLines(grp.map((r) => r.html).join('\n\n───\n\n'))) msgs.push(part);
      }
      if (!msgs.length) continue;   // 보낼 게 없으면 조용히 통과

      let ok = true;
      for (const m of msgs) {
        const r = await sendTelegramHtml(BOT_TOKEN, s.chat_id, m);
        if (r === 'blocked') {
          await sb.from('telegram_subscribers').update({ active: false }).eq('chat_id', s.chat_id);
          ok = false; break;
        }
        if (r === false) { ok = false; break; }
        await new Promise((r) => setTimeout(r, 50));   // 텔레그램 레이트리밋 여유
      }

      if (ok) {
        // 실제로 보낸 항목만 '발송함'으로 기록 — 실패 시 다음 정각에 다시 시도된다
        const patch: Record<string, unknown> = {};
        if (s.topic_briefing && briefingParts && s.last_briefing_sent_date !== date) patch.last_briefing_sent_date = date;
        if (urgent.length) patch.last_urgent_sent_at = nowIso;
        if (assembly.length) patch.last_assembly_sent_at = nowIso;
        if (Object.keys(patch).length) await sb.from('telegram_subscribers').update(patch).eq('chat_id', s.chat_id);
        sent++;
      } else failed++;
    }

    await sb.from('system_health').upsert({
      key: 'last_subscriber_briefing_run',
      updated_at: new Date().toISOString(),
      note: `${date} ${hour}시 · 발송 ${sent} · 실패 ${failed} · 대상후보 ${subs.length} · 큐 ${queue.length}`,
    }, { onConflict: 'key' });

    return new Response(JSON.stringify({ ok: true, date, hour, sent, failed, queued: queue.length }), { headers: { 'Content-Type': 'application/json' } });
  } catch (e) {
    console.error('[구독자 정시 발송 실패]', e);
    return new Response(JSON.stringify({ ok: false, error: String(e) }), { status: 500, headers: { 'Content-Type': 'application/json' } });
  }
});
