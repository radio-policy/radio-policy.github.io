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
//   - 팀별 알림(#252, 2026-09-27, ⚠️ Fable 재검토 대상): 관리자가 팀·실을 지정한 구독자의 주요 뉴스는
//     topic 'news'·level '긴급'·audience = 't:<팀>'|'d:<실>' 행으로 받는다(공통 구독자는 종전 topic 'urgent' 그대로 —
//     바이트 불변). 「중요+보통」을 고른 사람은 **정기 발송(:25)에서만** level '보통' 행을 한 시간치 한 통으로 받는다
//     — 크롤러 즉시 호출(헤더 `x-delivery: immediate`)은 보통을 평가하지도 워터마크를 옮기지도 않는다.
//     고르는 규칙은 _shared/subscriber_queue.ts(순수 함수, tests/subscriber_queue.test.ts).
//   - 팀 채점 알림(#277 S3, 2026-10-04): 크롤러가 세트를 열면 topic 'team'·audience 't:<팀>' 한 행 — 그 팀이 지정된
//     구독자에게 창 안에서(즉시 호출 없음) 맨 뒤에 붙여 보낸다. 워터마크 last_team_sent_at.
//
//  보안: x-cron-secret == CRON_SECRET (Vault `subscriber_cron_secret`와 동일값).
// ============================================================================

import 'jsr:@supabase/functions-js/edge-runtime.d.ts';
import { createClient } from 'jsr:@supabase/supabase-js@2';
import { briefingToTelegramHtml, splitByLines, sendTelegramHtml, DASHBOARD_URL, escapeHtml } from '../_shared/telegram_format.ts';
// news_tags.ts(pickChips)는 더 이상 여기서 쓰지 않는다 — 칩은 운영자 알림 전용이 됐다.
// 태그 자체는 여전히 '누가 이 기사를 받을지' 필터로 쓴다(_shared/subscriber_queue.ts planSubscriber).
import { matchTags } from '../_shared/news_tags.ts';
import { moreButton } from '../_shared/news_more.ts';
import {
  type QueueRow, maxCreatedAt, planSubscriber, watermarkPatch, renderNormalBatch, renderTeamNotices, fetchAllPages,
} from '../_shared/subscriber_queue.ts';
import {
  type HoldLookup, type HoldTeamRow, holdRecheckRows, holdKey, holdTeamsNeeded, holdDropKeys,
} from '../_shared/subscriber_hold.ts';

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
  topic_kmcc: boolean;   // 방미통위 동향(#154) — 의사일정·위원회 결과. urgent 처럼 크롤러가 큐 적재 직후 이 함수를 즉시 호출한다
  briefing_hour: number;
  end_hour: number;      // 수신 종료 시각(18~22) — 이 시각을 넘기면 다음 날 시작 시각까지 무발송
  last_briefing_sent_date: string | null;
  last_urgent_sent_at: string | null;
  last_assembly_sent_at: string | null;
  last_kmcc_sent_at: string | null;
  // 관심분야. **빈 배열 = 전체 수신**(캐논). NOT NULL DEFAULT '{}' 이라 기존 구독자는 자동 하위호환.
  tags: string[];
  // 팀별 알림(#252) — 관리자가 지정(둘 중 하나, 둘 다 null = 공통). news_level = 봇 「받을 뉴스」('urgent' 기본 | 'normal')
  team_id: number | null;
  division: string | null;
  news_level: string;
  last_normal_sent_at: string | null;   // 보통 묶음 워터마크(중요+보통을 고른 사람만 전진)
  last_team_sent_at: string | null;     // 팀 채점 알림(topic 'team', #277 S3) 워터마크 — 팀이 지정된 구독자만 전진
}
// QueueRow(news_url·audience·level 규약)는 _shared/subscriber_queue.ts로 옮겼다(#252 — 테스트가 같은 타입을 쓴다)

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

// matchTags는 _shared/news_tags.ts로 옮겼다(2026-08-21) — '더 보기'(telegram-webhook)가
// news_feed 행에 **같은 규칙**을 적용해야 해서다. 재수출은 기존 참조 호환용.
export { matchTags };

// 워터마크 전진 지점 = 평가한 행들의 max(created_at) — 본문은 _shared/subscriber_queue.ts로 옮겼다(#252,
// 워터마크 계산 watermarkPatch가 같은 함수를 쓴다). 재수출은 기존 참조 호환용.
export { maxCreatedAt };

// 기사 단위 행 렌더러. **html은 절대 파싱하지 않는다 — 순수 append만 한다.**
// (역파싱이 바로 위 95줄짜리 병합 유틸을 낳은 실수다.)
// 헤더 N = 태그 필터 + 중복 제거를 모두 거친 뒤의 건수. 중복 제거 키는 news_url.
// 태그 칩은 **구독자에게 보이지 않는다**(운영자 지시 2026-08-03). 태그는 여전히 '무엇을 받을지'를
// 정하는 필터로 쓰이지만, 판정이 맞았는지는 팀원이 아니라 운영자가 감시한다 — 그래서 칩은
// 운영자 알림(crawler.py의 운영자 경로)에만 붙는다. 구독자 화면에 틀린 칩이 보이면 판정 오류가
// 그대로 팀원 눈에 노출되고, 팀원은 고칠 방법이 없어 신뢰만 깎인다.
// subTags 인자는 시그니처 유지를 위해 남겨 둔다(호출부·테스트 불변).
export function renderNewsItems(rows: QueueRow[], subTags: string[] | null): string {
  const seen = new Set<string>();
  const picked: QueueRow[] = [];
  for (const r of rows) {
    const k = (r.news_url || '').trim();
    if (k) { if (seen.has(k)) continue; seen.add(k); }
    picked.push(r);
  }
  if (!picked.length) return '';
  const body = picked.map((r, i) => `${i + 1}. ${r.html}`).join('\n\n');
  return `📡 <b>통신·전파 정책 주요 뉴스 ${picked.length}건</b>\n\n${body}`;
}
// ── 기사 단위 큐 유틸 끝 ────────────────────────────────────────────────────────

// ── 보류 재확인 조회(10-05 S0) — 무엇을 뺄지는 _shared/subscriber_hold.ts holdDropKeys(순수 함수)가 정한다 ──
// 단위 행(t:/d:)이 있을 때만 팀 층을 읽는다. 조각마다 실패를 따로 둔다: 기사 조회 실패 = 아무것도 안 뺌(종전),
// 팀 목록 실패 = 실장 행만 안 뺌, 규칙·팀 행 실패 = 단위 행 전부 안 뺌. teamNote = 하트비트에 남길 실패 표시.
async function loadHoldLookup(rows: QueueRow[]): Promise<{ lk: HoldLookup; teamNote: string }> {
  const lk: HoldLookup = { news: null, teamRows: null, rulesById: null, divTeams: null };
  const urls = [...new Set(rows.map((r) => (r.news_url || '').trim()).filter(Boolean))];
  const news = new Map<string, { id: string; urgency: string }>();
  for (let i = 0; i < urls.length; i += 100) {
    const { data, error } = await sb.from('news_feed').select('id, url, urgency').in('url', urls.slice(i, i + 100));
    if (error) { console.error('[보류 등급 재확인 실패 — 이번엔 빼지 않음]', error); return { lk, teamNote: '' }; }
    for (const r of (data || []) as Array<{ id: string; url: string; urgency: string }>) {
      news.set(String(r.url).trim(), { id: String(r.id), urgency: String(r.urgency) });
    }
  }
  lk.news = news;
  const unit = rows.filter((r) => r.topic === 'news');
  if (!unit.length) return { lk, teamNote: '' };
  const fails: string[] = [];
  // 실 → 팀(크롤러 _alert_units와 같은 순서 sort_order·id). 실장 행이 없으면 읽지 않는다
  if (unit.some((r) => (r.audience || '').startsWith('d:'))) {
    const { data, error } = await sb.from('teams').select('id, division').order('sort_order').order('id');
    if (error) { console.error('[보류 재확인 — 팀 목록 조회 실패, 실장 행은 빼지 않음]', error); fails.push('팀 목록'); }
    else {
      const dt: Record<string, number[]> = {};
      for (const t of (data || []) as Array<{ id: number; division: string | null }>) {
        if (t.division) (dt[t.division] ||= []).push(Number(t.id));
      }
      lk.divTeams = dt;
    }
  } else lk.divTeams = {};
  try {
    // 팀 규칙 — 꺼진 것 포함(alertTeamLevel이 enabled를 본다). 칸 목록으로 읽는다(updated_by는 읽지 않음, #269)
    const { data: rs, error: re } = await sb.from('urgency_rules')
      .select('id, team_id, enabled, mode, level').not('team_id', 'is', null);
    if (re) throw re;
    const rulesById: Record<string, unknown> = {};
    for (const r of (rs || []) as Array<{ id: string }>) rulesById[r.id] = r;
    // team_urgency — 단위 행 기사 × 필요한 팀. 한 기사에 팀 수만큼 행이 오므로 묶음 = 1,000 ÷ 팀 수(1,000행 상한, #233)
    const tids = holdTeamsNeeded(unit, lk.divTeams);
    const ids = [...new Set(unit.map((r) => news.get((r.news_url || '').trim())?.id).filter((x): x is string => !!x))];
    const teamRows = new Map<string, Record<number, HoldTeamRow>>();
    if (tids.length && ids.length) {
      const step = Math.max(1, Math.min(100, Math.floor(1000 / tids.length)));
      for (let i = 0; i < ids.length; i += step) {
        const { data, error } = await sb.from('team_urgency').select('news_id, team_id, urgency, source, rule_id')
          .in('news_id', ids.slice(i, i + step)).in('team_id', tids);
        if (error) throw error;
        for (const t of (data || []) as HoldTeamRow[]) {
          const m = teamRows.get(String(t.news_id)) || {};
          m[Number(t.team_id)] = { ...t, team_id: Number(t.team_id) };
          teamRows.set(String(t.news_id), m);
        }
      }
    }
    lk.rulesById = rulesById;
    lk.teamRows = teamRows;
  } catch (e) {
    console.error('[보류 재확인 — 팀 규칙·팀 등급 조회 실패, 팀·실 행은 빼지 않음]', e);
    fails.push('팀 등급');
  }
  return { lk, teamNote: fails.length ? ` · 팀 재확인 실패(${fails.join('·')})` : '' };
}

Deno.serve(async (req: Request) => {
  if (!CRON_SECRET || req.headers.get('x-cron-secret') !== CRON_SECRET) {
    return new Response('unauthorized', { status: 401 });
  }
  const { date, hour, dow, dayStartMs } = kstNow();
  const isWeekday = dow >= 1 && dow <= 5;
  // 크롤러의 즉시 배달 호출(subscriber_notify._trigger_delivery)은 이 헤더를 싣는다(#252) — 보통 묶음은 매시 :25
  // 정기 발송 몫이라 이 호출에서는 보통을 평가하지도 워터마크를 옮기지도 않는다. 헤더가 없으면 정기 발송으로 본다.
  const immediate = (req.headers.get('x-delivery') || '').trim().toLowerCase() === 'immediate';
  let sent = 0, failed = 0;

  try {
    // ── 수신 시각이 도래한 구독자 ──
    let q = sb.from('telegram_subscribers')
      // ⚠ select('*')가 아니라 **명시 목록**이다. 컬럼을 빠뜨리면 값이 undefined가 되어
      //   "전체 수신"으로 조용히 퇴화하고 타입 검사도 못 잡는다. 컬럼 추가 시 여기부터 고칠 것.
      .select('chat_id, days, topic_briefing, topic_urgent, topic_assembly, topic_kmcc, briefing_hour, end_hour, last_briefing_sent_date, last_urgent_sent_at, last_assembly_sent_at, last_kmcc_sent_at, tags, team_id, division, news_level, last_normal_sent_at, last_team_sent_at')
      // 수신 창: briefing_hour(오전 6~10) ≤ 지금 ≤ end_hour(오후 6~10).
      // end_hour는 종전에 코드에 박혀 있던 '23시 이후 무발송'을 구독자가 고르게 바꾼 것.
      // 창을 벗어난 시간대의 큐는 버리지 않는다 — 워터마크가 안 움직이므로 다음 날 시작 시각에 전달된다.
      .eq('active', true).lte('briefing_hour', hour).gte('end_hour', hour);
    if (!isWeekday) q = q.eq('days', 'daily');   // 주말은 '매일' 설정자만
    const subs = ((await q).data || []) as Sub[];
    if (!subs.length) {
      // 수신 창 밖(23~05시)에도 '돌았음'을 남긴다 (#199, 2026-09-24). 안 남기면 heartbeat가 22:25에서 멈춰
      // 워치독(임계 3h)이 매일 새벽 "4.7h 무갱신"을 낸다 — 발송은 정상인데 기록만 없는 오탐.
      await sb.from('system_health').upsert({
        key: 'last_subscriber_briefing_run',
        updated_at: new Date().toISOString(),
        note: `${date} ${hour}시 · 발송 0 · 수신 창 밖(대상 0)`,
      }, { onConflict: 'key' });
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
        `\n📊 <a href="${DASHBOARD_URL}?p=briefing">대시보드에서 전문 보기</a>`;
    }

    // ── 큐(긴급·법안·팀·보통) — 최근 72시간분을 한 번 읽고 구독자별로 시점 필터 ──
    // 페이지로 끝까지 읽는다(#252 — 받는 단위별·보통 행이 더해져 1,000행 상한에 닿을 수 있다. 종전엔 페이지가 없어
    // 1,000행에서 잘렸다). 순서는 (created_at, id) — 한 번에 벌크 insert된 행은 created_at이 같아 id로 순서를 고정한다.
    // 한 페이지라도 실패하면 큐 전체를 빈 것으로 본다(종전 조회 실패와 같은 동작 — 아무것도 안 보내고 워터마크도 그대로,
    // 다음 정각에 다시). 부분 목록으로 워터마크를 옮기면 같은 시각 행의 나머지가 영구 소실될 수 있다.
    const sinceIso = new Date(Date.now() - QUEUE_LOOKBACK_H * 3600 * 1000).toISOString();
    const { rows: queue, error: qerr } = await fetchAllPages<QueueRow>((from, to) =>
      sb.from('subscriber_queue')
        .select('id, topic, html, created_at, news_url, tags, audience, level').gte('created_at', sinceIso)
        .order('created_at').order('id').range(from, to));
    if (qerr) console.error('[구독자 큐 조회 실패 — 이번 실행은 큐 없이(브리핑만) 진행]', qerr);

    // ── 큐 선별 2단 분리 ── (규칙 본문은 _shared/subscriber_queue.ts planSubscriber)
    // 1단 eligible : 토픽 ON && 워터마크 이후 = **평가 대상**(태그 무관).
    //                워터마크는 이 집합 기준으로 전진한다 — 태그 필터로 발송이 0건이 되어도
    //                큐가 고이지 않아야 나중에 태그를 켜는 순간 72h 백로그가 쏟아지지 않는다(#44 재발 방지).
    // 2단 delivered: eligible ∩ 태그 매칭 = 실제 발송분 (matchTags).
    // 토픽이 OFF면 eligible도 비어야 한다 → 워터마크 전진 금지(껐다 켜면 그 사이 건을 받는 현행 유지).
    // 받는 단위: 공통 = topic 'urgent'(종전 식 그대로) / 팀·실장 = topic 'news'·'긴급'·audience 일치.
    const nowMs = Date.now();

    // ── 임시 보류(#256-보론, 2026-09-29, 운영자 요청 「운영자 봇으로 먼저 보고 ~10분 뒤 일반 이용자에게」) ──
    // app_config.subscriber_hold = {"minutes": 8, "until": "2026-09-29T17:00:00+09:00"} — until이 지나면 저절로 꺼진다(설정 삭제 불필요).
    // 켜져 있는 동안: ① 중요 행은 created_at이 minutes 이전인 것만 평가·발송(planSubscriber holdMs) ② 발송 직전에 공통 등급을
    // 다시 읽어 운영자가 대시보드에서 내린 기사(긴급 아님)·지운 기사는 발송분에서 뺀다(eligible엔 남겨 워터마크는 전진 → 큐에
    // 고이지 않음). 설정·재확인 조회가 실패하면 보류·취소 없이 종전대로(fail-open — 보내는 쪽).
    // 팀·실 행(10-05 S0): 공통값이 아니라 그 단위의 지금 알림 등급(alertTeamLevel·alertDivisionLevel)으로 본다 —
    // 종전엔 팀 규칙이 올린 팀 전용 긴급을 공통값(보통·참고)으로 보고 전부 뺐다. 규칙은 _shared/subscriber_hold.ts.
    let holdMs = 0;
    let holdNote = '';
    let dropKeys = new Set<string>();
    try {
      const { data: hc } = await sb.from('app_config').select('value').eq('key', 'subscriber_hold').maybeSingle();
      if (hc?.value) {
        const cfg = JSON.parse(String(hc.value));
        const until = cfg.until ? Date.parse(String(cfg.until)) : 0;
        const mins = Number(cfg.minutes) || 0;
        if (mins > 0 && until > nowMs) holdMs = mins * 60 * 1000;
      }
    } catch (e) {
      console.error('[보류 설정 읽기 실패 — 보류 없이 진행]', e);
    }
    if (holdMs > 0 && !qerr) {
      const recheck = holdRecheckRows(queue);
      const { lk, teamNote } = await loadHoldLookup(recheck);
      dropKeys = holdDropKeys(recheck, lk);
      // 「취소 N건」은 종전처럼 기사 수, 괄호 = 뺀 큐 행 열쇠 수(공통 1 + 단위마다 1)
      const dropUrlN = new Set([...dropKeys].map((k) => k.split('\u0000')[1])).size;
      holdNote = ` · 보류 ${Math.round(holdMs / 60000)}분 · 취소 ${dropUrlN}건(행 ${dropKeys.size})${teamNote}`;
    }

    for (const s of subs) {
      // 메시지에 reply_markup을 실을 수 있게 {text, extra} 쌍으로 든다 — 주요 뉴스 마지막
      // 조각에만 '더 보기' 버튼이 붙는다(2026-08-21).
      const msgs: Array<{ text: string; extra?: Record<string, unknown> }> = [];

      if (s.topic_briefing && briefingParts && s.last_briefing_sent_date !== date) {
        for (const p of briefingParts) msgs.push({ text: p });
      }
      // 1단(평가 대상 = 워터마크 전진의 근거)·2단(실제 발송분) — 법안 동향(assembly)·방미통위(kmcc)는 기사 단위
      // 개념이 없어 태그 필터를 적용하지 않는다. 보통은 「중요+보통」·주요 뉴스 켬·정기 발송일 때만 채워진다.
      const plan = planSubscriber(queue, s, { dayStartMs, nowMs, immediate, holdMs });
      const urgentEligible = plan.urgentEligible;
      // 보류 중 취소분(운영자가 내린·지운 기사, 팀·실 행은 그 단위 등급이 긴급 아님)은 발송분에서만 뺀다 — eligible은
      // 그대로라 워터마크가 넘어간다. 열쇠 = 공통 행 url / 단위 행 audience + url(holdKey)
      const urgent = dropKeys.size ? plan.urgent.filter((r) => !dropKeys.has(holdKey(r))) : plan.urgent;
      const assembly = plan.assemblyEligible;
      const kmcc = plan.kmccEligible;

      // 순서 = 브리핑(위) → 주요 뉴스 → 보통 → 국회·법률 → 방미통위 → 팀 채점 알림(#277)
      const groups: Array<{ topic: string; rows: QueueRow[] }> = [
        { topic: 'urgent', rows: urgent },
        { topic: 'normal', rows: plan.normal },
        { topic: 'assembly', rows: assembly },
        // kmcc 행은 첫 줄이 "📋 <b>방미통위 제N차 회의 의사일정 …</b>" 꼴이라 HEADER_COUNT_RE(숫자+건)에 안 걸리고
        // 줄은 '· ' 불릿뿐이라 mergeQueueBlocks 가 그대로 통과시킨다(assembly 와 같은 legacy 경로).
        { topic: 'kmcc', rows: kmcc },
        { topic: 'team', rows: plan.teamEligible },
      ];
      for (const { topic, rows: grp } of groups) {
        if (!grp.length) continue;
        // 팀 채점 알림(#277) — 완성 블록을 같은 글 한 번씩 잇기만(제목의 「20건」을 mergeQueueBlocks가 건수 머리로 오인하지 않게)
        if (topic === 'team') {
          const tb = renderTeamNotices(grp);
          if (tb.trim()) for (const c of splitByLines(tb)) msgs.push({ text: c });
          continue;
        }
        // ── 이중 경로 판별 ──
        //  news_url NOT NULL = 기사 단위 행 → 신규 렌더러(헤더 1회 + 번호 + 칩, 순수 append)
        //  news_url NULL     = 구버전 묶음 행(html에 제목이 이미 포함) → mergeQueueBlocks(존치)
        //  topic='assembly'  = 항상 legacy (법안 알림은 기사 단위가 아니다)
        //  topic='normal'    = 보통 묶음(#252) — renderNormalBatch만. mergeQueueBlocks를 거치지 않는다(topic 'news' 행은 news_url 필수)
        const isNews = topic === 'urgent';
        const isNormal = topic === 'normal';
        const modern = isNews ? grp.filter((r) => !!r.news_url) : [];
        const legacy = isNews ? grp.filter((r) => !r.news_url) : isNormal ? [] : grp;

        const parts: string[] = [];
        if (isNormal) parts.push(renderNormalBatch(grp, plan.normalFromMs, maxCreatedAt(plan.normalEligible)));
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
        const chunks = splitByLines(body);
        for (let ci = 0; ci < chunks.length; ci++) {
          // '더 보기'는 주요 뉴스의 **마지막 조각에만** 붙인다. 구간은 이 발송이 실제로 커버한
          // (from, to] — 워터마크 전진값과 같은 값이라 앞뒤 버튼의 구간이 빈틈없이 맞물린다.
          // 「중요+보통」을 고른 사람에게는 붙이지 않는다(#252 — 보통을 이미 묶음으로 받는다, plan.moreButton).
          const isLastNewsChunk = isNews && plan.moreButton && ci === chunks.length - 1;
          const extra = isLastNewsChunk
            ? moreButton(
                s.last_urgent_sent_at ? new Date(s.last_urgent_sent_at).getTime() : dayStartMs,
                maxCreatedAt(urgentEligible),
              )
            : undefined;
          msgs.push({ text: chunks[ci], extra });
        }
      }

      // ⚠ 여기서 `if (!msgs.length) continue`를 하면 안 된다.
      //   태그 필터로 발송이 0건이어도 워터마크는 전진해야 하므로 아래 patch 경로를 반드시 지난다.
      //   (보낼 게 없으면 아래 루프가 0회 돌 뿐이고, 텔레그램 호출도 발생하지 않는다.)
      let ok = true;
      for (const m of msgs) {
        const r = await sendTelegramHtml(BOT_TOKEN, s.chat_id, m.text, m.extra ?? {});
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
        // 워터마크는 delivered가 아니라 **eligible** 기준, nowIso가 아니라 **max(created_at)** — 칸 순서도 종전과 같다
        // (urgent → assembly → kmcc, 보통은 평가했을 때만 맨 뒤 last_normal_sent_at). 본문은 watermarkPatch.
        Object.assign(patch, watermarkPatch(plan));
        if (Object.keys(patch).length) await sb.from('telegram_subscribers').update(patch).eq('chat_id', s.chat_id);
        if (msgs.length) sent++;   // 실제로 보낸 사람만 집계 (워터마크만 전진한 경우는 제외)
      } else failed++;
    }

    await sb.from('system_health').upsert({
      key: 'last_subscriber_briefing_run',
      updated_at: new Date().toISOString(),
      // 큐 조회 실패는 note에 남긴다(리뷰 #252-6) — 종전엔 '큐 0'으로 정상처럼 보였다
      note: `${date} ${hour}시 · 발송 ${sent} · 실패 ${failed} · 대상후보 ${subs.length} · 큐 ${qerr ? '조회 실패' : queue.length}${holdNote}`,
    }, { onConflict: 'key' });

    return new Response(JSON.stringify({ ok: true, date, hour, sent, failed, queued: queue.length }), { headers: { 'Content-Type': 'application/json' } });
  } catch (e) {
    console.error('[구독자 정시 발송 실패]', e);
    return new Response(JSON.stringify({ ok: false, error: String(e) }), { status: 500, headers: { 'Content-Type': 'application/json' } });
  }
});
