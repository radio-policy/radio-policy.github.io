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
import { pickChips } from '../_shared/news_tags.ts';

// env는 반드시 trim — 콘솔 붙여넣기 시 줄바꿈이 섞이면 시크릿 비교가 조용히 어긋난다(401)
const env = (k: string) => (Deno.env.get(k) || '').trim();

const BOT_TOKEN = env('SUBSCRIBER_BOT_TOKEN');
const CRON_SECRET = env('CRON_SECRET');
const NONEWS_PREFIX = '🕊️ (신규 뉴스 없음';   // morning_briefing.py _NONEWS_PREFIX 와 일치
const QUEUE_LOOKBACK_H = 72;                  // 큐 조회 범위(시간) — 그 이전 건은 오래돼서 보내지 않음. 72h: '평일만' 구독자 금요일 밤 큐(금 23시→월 06:25 ≈ 55h) 이월 소실 방지

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
  // 관심분야. **빈 배열 = 전체 수신**(캐논). NOT NULL DEFAULT '{}' 이라 기존 구독자는 자동 하위호환.
  tags: string[];
}
// news_url NOT NULL = 기사 단위 행(신규), NULL = 구버전 묶음 행·법안 알림
interface QueueRow { id: number; topic: string; html: string; created_at: string; news_url: string | null; tags: string[] | null }

// ── 큐 병합 유틸 (순수 함수 — 로컬 Node 단위검증 가능) ───────────────────────────
// 문제(2026-08-03 06:24 실수신): subscriber_queue의 각 행 html에는 "🚨 긴급 전파정책 뉴스 N건"
// 제목이 **이미 포함된 완성 블록**이 들어 있다(subscriber_notify.format_urgent_html).
// 미발송 행을 구분선으로 단순 연결하면 제목이 행 수만큼 반복되고 번호도 매 행 1부터 다시 시작한다.
// → 같은 형태(같은 제목 틀)의 행끼리 제목 1개 + 번호 1..N으로 다시 조립하고, 같은 기사는 하나만 남긴다.
// 원칙: 형식이 예상과 다르면 그 행은 손대지 않고 원문 그대로 둔다(fail-soft).
// 병합이 어긋나도 알림 자체가 빠지는 일은 절대 없어야 한다(호출측에서도 try/catch로 한 겹 더 감쌈).
const QUEUE_SEP = '\n\n───\n\n';
const HEADER_COUNT_RE = /^(.*?)(\d+)(건.*)$/;   // "🚨 <b>긴급 전파정책 뉴스 4건</b>" → 앞/건수/뒤
const ITEM_START_RE = /^\s*\d+\.\s/;            // "1. <a href=...>제목</a>"

interface CountedBlock { key: string; prefix: string; suffix: string; items: string[] }
interface MergeGroup { prefix: string; suffix: string; items: string[]; seen: Set<string> }

function trimBlankLines(lines: string[]): string[] {
  let a = 0, b = lines.length;
  while (a < b && !lines[a].trim()) a++;
  while (b > a && !lines[b - 1].trim()) b--;
  return lines.slice(a, b);
}

// 한 큐 행을 "제목(N건) + 번호 항목들"로 분해. 조금이라도 어긋나면 null → 호출측이 원문 유지.
function parseCountedBlock(html: string): CountedBlock | null {
  const lines = (html || '').replace(/\r/g, '').split('\n');
  let h = 0;
  while (h < lines.length && !lines[h].trim()) h++;
  if (h >= lines.length) return null;                 // 빈 행
  const header = lines[h];
  if (ITEM_START_RE.test(header)) return null;        // 제목 없이 항목부터 시작 → 병합 대상 아님
  const m = header.match(HEADER_COUNT_RE);
  if (!m) return null;                                // "N건" 제목 형식이 아님(법안 알림 등) → 원문 유지

  const items: string[] = [];
  let buf: string[] | null = null;
  for (let i = h + 1; i < lines.length; i++) {
    const line = lines[i];
    if (ITEM_START_RE.test(line)) {
      if (buf) items.push(trimBlankLines(buf).join('\n'));
      buf = [line];
    } else if (buf) {
      buf.push(line);
    } else if (line.trim()) {
      return null;                                    // 제목과 첫 항목 사이에 예상 못한 본문 → 원문 유지
    }
  }
  if (buf) items.push(trimBlankLines(buf).join('\n'));
  if (!items.length) return null;                     // 항목이 없음 → 원문 유지
  if (parseInt(m[2], 10) !== items.length) return null; // 제목 건수 ≠ 항목 수 → 오탐 가능 → 원문 유지
  return { key: m[1] + '\u0000' + m[3], prefix: m[1], suffix: m[3], items };
}

// 중복 판정 키: 번호와 HTML 태그를 걷어낸 항목 텍스트(제목+출처). URL만 다른 같은 기사도 같은 키가 된다.
function itemKey(item: string): string {
  return item.replace(ITEM_START_RE, '')
    .replace(/<[^>]+>/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function renderMergeGroup(g: MergeGroup): string {
  const body = g.items.map((it, i) => it.replace(ITEM_START_RE, `${i + 1}. `)).join('\n\n');
  return `${g.prefix}${g.items.length}${g.suffix}\n\n${body}`;
}

// 같은 토픽의 큐 행 html 목록 → 발송용 한 덩어리 텍스트.
// 제목 틀이 같은 행끼리만 합치므로, 형태가 다른 알림(법안 등)은 지금까지처럼 구분선으로 분리된다.
export function mergeQueueBlocks(htmls: string[]): string {
  const slots: Array<string | MergeGroup> = [];
  const byKey = new Map<string, MergeGroup>();
  for (const raw of htmls) {
    let p: CountedBlock | null = null;
    try { p = parseCountedBlock(raw); } catch { p = null; }   // 파싱 예외도 fail-soft
    if (!p) { slots.push(raw); continue; }
    let g = byKey.get(p.key);
    if (!g) {
      g = { prefix: p.prefix, suffix: p.suffix, items: [], seen: new Set<string>() };
      byKey.set(p.key, g);
      slots.push(g);                                  // 첫 등장 위치에 병합 블록을 고정(순서 보존)
    }
    for (const it of p.items) {
      const k = itemKey(it);
      if (k) {
        if (g.seen.has(k)) continue;                  // 동일 기사 중복 제거(큐에 남은 과거 중복 방어)
        g.seen.add(k);
      }
      g.items.push(it);
    }
  }
  return slots
    .map((s) => (typeof s === 'string' ? s : renderMergeGroup(s)))
    .filter((t) => !!t.trim())
    .join(QUEUE_SEP);
}
// ── 큐 병합 유틸 끝 ─────────────────────────────────────────────────────────────

// ── 기사 단위 큐 유틸 (순수 함수 — 로컬 Node 단위검증 가능) ────────────────────
// 위 병합 유틸이 "완성된 HTML을 역파싱"하는 방식이었다면, 여기서는 큐가 태그를 **데이터로**
// 들고 오고 Edge가 헤더·번호·칩을 조립한다. 헤더 건수와 칩은 구독자마다 달라서 Python이
// 미리 구울 수 없다.

// 구독자 관심분야로 발송분을 고른다.
//  - 구독자 tags 가 빈 배열 → 전체 수신 (기존 구독자 하위호환의 근거)
//  - 기사 tags 가 null/빈 배열 → **전원 통과(fail-open)**. 태그 판정이 실패했다고 해서
//    기사가 조용히 사라지면 안 된다. 누락은 되돌릴 수 없지만 노이즈는 눈에 보인다.
export function matchTags(rows: QueueRow[], subTags: string[] | null): QueueRow[] {
  const s = (subTags || []).filter((t) => !!t);
  if (!s.length) return rows;
  return rows.filter((r) => {
    const a = r.tags || [];
    if (!a.length) return true;                       // fail-open
    return a.some((t) => s.includes(t));
  });
}

// 워터마크 전진 지점 = 평가한 행들의 max(created_at).
// nowIso를 쓰면 안 되는 이유: 큐 읽기와 워터마크 쓰기 사이에 크롤러가 _trigger_delivery()로
// 새 행을 넣으면 nowIso가 그보다 미래라 그 기사가 **영구 소실**된다.
export function maxCreatedAt(rows: QueueRow[]): string | null {
  let best: string | null = null;
  let bestMs = -Infinity;
  for (const r of rows) {
    const ms = new Date(r.created_at).getTime();
    if (ms > bestMs) { bestMs = ms; best = r.created_at; }
  }
  return best;
}

// 기사 단위 행 렌더러. **html은 절대 파싱하지 않는다 — 순수 append만 한다.**
// (역파싱이 바로 위 95줄짜리 병합 유틸을 낳은 실수다.)
// 헤더 N = 태그 필터 + 중복 제거를 모두 거친 뒤의 건수. 중복 제거 키는 news_url.
export function renderNewsItems(rows: QueueRow[], subTags: string[] | null): string {
  const seen = new Set<string>();
  const picked: QueueRow[] = [];
  for (const r of rows) {
    const k = (r.news_url || '').trim();
    if (k) { if (seen.has(k)) continue; seen.add(k); }
    picked.push(r);
  }
  if (!picked.length) return '';
  const body = picked.map((r, i) => {
    const chips = pickChips(r.tags ?? null, subTags ?? null, 2);
    return `${i + 1}. ${r.html}` + (chips.length ? `\n   🏷 ${chips.join(' · ')}` : '');
  }).join('\n\n');
  return `📡 <b>통신·전파 정책 주요 뉴스 ${picked.length}건</b>\n\n${body}`;
}
// ── 기사 단위 큐 유틸 끝 ────────────────────────────────────────────────────────

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
      // ⚠ select('*')가 아니라 **명시 목록**이다. 컬럼을 빠뜨리면 값이 undefined가 되어
      //   "전체 수신"으로 조용히 퇴화하고 타입 검사도 못 잡는다. 컬럼 추가 시 여기부터 고칠 것.
      .select('chat_id, days, topic_briefing, topic_urgent, topic_assembly, briefing_hour, last_briefing_sent_date, last_urgent_sent_at, last_assembly_sent_at, tags')
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
      .select('id, topic, html, created_at, news_url, tags').gte('created_at', sinceIso).order('created_at');
    const queue = (qdata || []) as QueueRow[];

    // ── 큐 선별 2단 분리 ──
    // 1단 eligible : 토픽 ON && 워터마크 이후 = **평가 대상**(태그 무관).
    //                워터마크는 이 집합 기준으로 전진한다 — 태그 필터로 발송이 0건이 되어도
    //                큐가 고이지 않아야 나중에 태그를 켜는 순간 72h 백로그가 쏟아지지 않는다(#44 재발 방지).
    // 2단 delivered: eligible ∩ 태그 매칭 = 실제 발송분 (matchTags).
    // 토픽이 OFF면 eligible도 비어야 한다 → 워터마크 전진 금지(껐다 켜면 그 사이 건을 받는 현행 유지).
    const pickEligible = (on: boolean, topic: string, lastSent: string | null): QueueRow[] => {
      if (!on) return [];
      // 첫 발송(기록 없음)은 오늘 00:00(KST) 이후 건만 — 가입 직후 이틀치가 쏟아지는 것 방지
      const fromMs = lastSent ? new Date(lastSent).getTime() : dayStartMs;
      return queue.filter((r) => r.topic === topic && new Date(r.created_at).getTime() > fromMs);
    };

    for (const s of subs) {
      const msgs: string[] = [];

      if (s.topic_briefing && briefingParts && s.last_briefing_sent_date !== date) {
        msgs.push(...briefingParts);
      }
      // 1단 — 평가 대상(워터마크 전진의 근거)
      const urgentEligible = pickEligible(s.topic_urgent, 'urgent', s.last_urgent_sent_at);
      const assemblyEligible = pickEligible(s.topic_assembly, 'assembly', s.last_assembly_sent_at);
      // 2단 — 실제 발송분. 법안 동향(assembly)은 기사 단위 개념이 없어 태그 필터를 적용하지 않는다.
      const urgent = matchTags(urgentEligible, s.tags);
      const assembly = assemblyEligible;

      const groups: Array<{ topic: string; rows: QueueRow[] }> = [
        { topic: 'urgent', rows: urgent },
        { topic: 'assembly', rows: assembly },
      ];
      for (const { topic, rows: grp } of groups) {
        if (!grp.length) continue;
        // ── 이중 경로 판별 ──
        //  news_url NOT NULL = 기사 단위 행 → 신규 렌더러(헤더 1회 + 번호 + 칩, 순수 append)
        //  news_url NULL     = 구버전 묶음 행(html에 제목이 이미 포함) → mergeQueueBlocks(존치)
        //  topic='assembly'  = 항상 legacy (법안 알림은 기사 단위가 아니다)
        const isNews = topic === 'urgent';
        const modern = isNews ? grp.filter((r) => !!r.news_url) : [];
        const legacy = isNews ? grp.filter((r) => !r.news_url) : grp;

        const parts: string[] = [];
        if (modern.length) parts.push(renderNewsItems(modern, s.tags));
        if (legacy.length) {
          // 같은 토픽의 여러 건은 한 메시지로 합치되, 길면 분할 (알림 개수 폭증 방지 — #44 취지)
          // 각 행 html에 제목이 이미 들어 있으므로 단순 연결이 아니라 제목 1개로 재조립한다.
          const raws = legacy.map((r) => r.html);
          try {
            parts.push(mergeQueueBlocks(raws));
          } catch (e) {
            // 병합 실패로 알림이 통째로 빠지는 일은 없어야 한다 → 예전 방식(단순 연결)으로 그대로 발송
            console.error('[큐 병합 실패 — 원문 연결로 발송]', e);
            parts.push(raws.join(QUEUE_SEP));
          }
        }
        const body = parts.filter((t) => !!t.trim()).join(QUEUE_SEP);
        if (!body.trim()) continue;
        for (const part of splitByLines(body)) msgs.push(part);
      }

      // ⚠ 여기서 `if (!msgs.length) continue`를 하면 안 된다.
      //   태그 필터로 발송이 0건이어도 워터마크는 전진해야 하므로 아래 patch 경로를 반드시 지난다.
      //   (보낼 게 없으면 아래 루프가 0회 돌 뿐이고, 텔레그램 호출도 발생하지 않는다.)
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
        // 발송에 성공했을 때만 기록 — 실패 시 patch를 건너뛰어 다음 정각에 다시 시도된다(현행 유지).
        const patch: Record<string, unknown> = {};
        if (s.topic_briefing && briefingParts && s.last_briefing_sent_date !== date) patch.last_briefing_sent_date = date;
        // 워터마크는 delivered가 아니라 **eligible** 기준, nowIso가 아니라 **max(created_at)**.
        const uMark = maxCreatedAt(urgentEligible);
        const aMark = maxCreatedAt(assemblyEligible);
        if (uMark) patch.last_urgent_sent_at = uMark;
        if (aMark) patch.last_assembly_sent_at = aMark;
        if (Object.keys(patch).length) await sb.from('telegram_subscribers').update(patch).eq('chat_id', s.chat_id);
        if (msgs.length) sent++;   // 실제로 보낸 사람만 집계 (워터마크만 전진한 경우는 제외)
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
