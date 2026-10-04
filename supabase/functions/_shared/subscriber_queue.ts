// ============================================================================
//  구독자 큐 고르기 · 보통 묶음 렌더 — 순수 함수 (#252, 2026-09-27, ⚠️ Fable 재검토 대상)
//
//  send-subscriber-briefing/index.ts 는 최상위 Deno.serve 라 import하면 서버가 뜬다. 그래서 '누구에게 어떤 큐
//  행이 가고 워터마크가 어디까지 가는가'를 정하는 규칙만 여기 떼어 두고 tests/subscriber_queue.test.ts
//  (DB·네트워크 0)로 검증한다. 이 파일은 DB를 만지지 않는다 — 페이지 조회도 호출측이 준 함수로만 한다.
//
//  받는 단위(audience) — 크롤러(run_audience_alerts)와 같은 규칙:
//    division 있으면 'd:<실>', 아니면 team_id 있으면 't:<팀 id>', 둘 다 없으면 null(공통).
//  · 공통 구독자의 중요 = 기존 topic 'urgent' 행(audience null) — **종전 코드와 같은 식 그대로**(바이트 불변).
//  · 팀·실장의 중요   = topic 'news' · level '긴급' · audience == 키. 워터마크는 공통과 같은 last_urgent_sent_at.
//  · 보통(중요+보통을 고른 사람만) = topic 'news' · level '보통' · audience == (키 ?? 'c'), **정기 발송(:25)만** —
//    크롤러의 즉시 호출(`x-delivery: immediate`)에서는 평가도 워터마크 전진도 하지 않는다.
//  · 팀 채점 알림(#277 S3, 2026-10-04) = topic 'team' · audience 't:<팀 id>'(level·news_url null — DB CHECK) — 팀이 지정된
//    구독자만(실장 'd:'·공통은 안 받는다). 켜고 끄는 칸 없음. 워터마크 last_team_sent_at, 기록이 없으면 큐 조회 범위(72h) 전부 —
//    드문 알림이라 오늘 0시로 자르면 어제 저녁(수신 창 밖)에 만든 세트 알림을 영영 못 받는다. 크롤러는 즉시 호출하지 않는다.
// ============================================================================

import { matchTags } from './news_tags.ts';
import { formatRange } from './news_more.ts';
import { escapeHtml, DASHBOARD_URL } from './telegram_format.ts';

// news_url NOT NULL = 기사 단위 행(신규), NULL = 구버전 묶음 행·법안 알림
// audience·level = topic 'news' 행만 값이 있다(DB CHECK — 다른 topic은 둘 다 null)
export interface QueueRow {
  id: number; topic: string; html: string; created_at: string; news_url: string | null; tags: string[] | null;
  audience?: string | null; level?: string | null;
}

// 고르기에 필요한 구독자 칸만. send-subscriber-briefing의 명시 select 목록에 전부 있어야 한다
// (빠지면 undefined → 공통·중요만으로 조용히 퇴화).
export interface PickSub {
  topic_urgent: boolean; topic_assembly: boolean; topic_kmcc: boolean;
  last_urgent_sent_at: string | null;
  last_assembly_sent_at: string | null;
  last_kmcc_sent_at: string | null;
  last_normal_sent_at?: string | null;
  last_team_sent_at?: string | null;   // 팀 채점 알림(topic 'team') 워터마크(#277)
  team_id?: number | null;
  division?: string | null;
  news_level?: string | null;   // 'urgent'(기본) | 'normal'
  tags: string[];
}

export interface PickOpts {
  dayStartMs: number;    // 오늘 00:00 KST(ms) — 첫 발송(기록 없음)의 시작점
  nowMs: number;
  immediate: boolean;    // 크롤러 즉시 호출(x-delivery: immediate) — 보통은 건드리지 않는다
  holdMs?: number;       // 보류(#256-보론, 2026-09-29): 중요 행은 created_at ≤ now − holdMs 인 것만 평가·발송. 0/없음 = 종전 그대로
}

export interface SubPlan {
  audience: string | null;       // 받는 단위 키(null = 공통)
  urgentEligible: QueueRow[];    // 1단 — 평가 대상(워터마크 근거, 태그 무관)
  urgent: QueueRow[];            // 2단 — 실제 발송분(태그 거름)
  assemblyEligible: QueueRow[];
  kmccEligible: QueueRow[];
  normalOn: boolean;             // 이번 실행에서 보통을 평가하나
  normalFromMs: number;          // 보통 구간 시작(워터마크, 없으면 max(오늘 0시, 지금−1시간))
  normalEligible: QueueRow[];
  normal: QueueRow[];
  moreButton: boolean;           // 주요 뉴스 '더 보기' — 중요+보통 사람에게는 안 붙인다(보통을 이미 받는다)
  teamEligible: QueueRow[];      // 팀 채점 알림(#277) — 태그 거름 없음(평가 = 발송)
}

export const COMMON_NORMAL_AUDIENCE = 'c';
const HOUR_MS = 3600 * 1000;

/** 받는 단위 키. division 우선(DB CHECK로 둘이 함께 있을 수는 없다), 둘 다 없으면 null = 공통. */
export function audienceKey(s: { team_id?: number | null; division?: string | null }): string | null {
  if (s.division) return 'd:' + s.division;
  if (s.team_id !== null && s.team_id !== undefined) return 't:' + s.team_id;
  return null;
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

/**
 * 구독자 한 명의 큐 선별. 2단 분리 원칙은 종전과 같다 —
 *  1단 eligible : 토픽 ON && 워터마크 이후 = **평가 대상**(태그 무관). 워터마크는 이 집합 기준으로 전진한다
 *                 (태그 필터로 발송이 0건이어도 큐가 고이지 않아야 나중에 태그를 켜는 순간 72h 백로그가 쏟아지지 않는다, #44).
 *  2단 delivered: eligible ∩ 태그 매칭 = 실제 발송분. 국회·법률(assembly)·방미통위(kmcc)는 태그 필터 없음(호출측이 eligible 그대로 씀).
 * 토픽이 OFF면 eligible도 비어야 한다 → 워터마크 전진 금지(껐다 켜면 그 사이 건을 받는 현행 유지).
 */
export function planSubscriber(queue: QueueRow[], s: PickSub, o: PickOpts): SubPlan {
  // 종전 pickEligible 그대로(공통 경로 바이트 불변의 근거 — 테스트가 옛 식과 대조한다)
  const pickEligible = (on: boolean, topic: string, lastSent: string | null): QueueRow[] => {
    if (!on) return [];
    // 첫 발송(기록 없음)은 오늘 00:00(KST) 이후 건만 — 가입 직후 이틀치가 쏟아지는 것 방지
    const fromMs = lastSent ? new Date(lastSent).getTime() : o.dayStartMs;
    return queue.filter((r) => r.topic === topic && new Date(r.created_at).getTime() > fromMs);
  };
  // 받는 단위 행(topic 'news') — 등급·단위가 정확히 같은 행만
  const pickUnit = (on: boolean, audience: string, level: string, fromMs: number): QueueRow[] => {
    if (!on) return [];
    return queue.filter((r) => r.topic === 'news' && r.level === level && r.audience === audience
      && new Date(r.created_at).getTime() > fromMs);
  };

  const audience = audienceKey(s);
  // 보류(#256-보론): 너무 새 행은 **eligible에서도** 뺀다 — 워터마크가 그 행을 넘지 않아 다음 호출(크롤러 즉시 호출·:25)에서
  // 다시 평가된다. 그 사이 운영자가 대시보드에서 등급을 내리면 발송 측이 발송 직전 재확인으로 뺀다(index.ts). holdMs 0이면 항등.
  const holdCut = o.holdMs && o.holdMs > 0 ? o.nowMs - o.holdMs : Infinity;
  const notHeld = (r: QueueRow) => new Date(r.created_at).getTime() <= holdCut;
  const urgentEligible = (audience === null
    ? pickEligible(s.topic_urgent, 'urgent', s.last_urgent_sent_at)
    : pickUnit(s.topic_urgent, audience, '긴급',
        s.last_urgent_sent_at ? new Date(s.last_urgent_sent_at).getTime() : o.dayStartMs)).filter(notHeld);

  const isNormal = s.news_level === 'normal';
  const normalOn = isNormal && !!s.topic_urgent && !o.immediate;
  // 첫 보통(기록 없음)은 한 시간치만 — 오늘 0시부터면 켜는 순간 하루치가 한 통에 쏟아진다
  // (봇에서 중요만→중요+보통으로 바꾸면 웹훅이 last_normal_sent_at = 지금으로 둔다 — 이건 그 기록이 없을 때의 안전망)
  const normalFromMs = s.last_normal_sent_at
    ? new Date(s.last_normal_sent_at).getTime()
    : Math.max(o.dayStartMs, o.nowMs - HOUR_MS);
  const normalEligible = normalOn
    ? pickUnit(true, audience ?? COMMON_NORMAL_AUDIENCE, '보통', normalFromMs)
    : [];
  // 같은 단위에 **중요로도** 들어간 기사는 보통 묶음에서 뺀다(워터마크 평가에는 남긴다). 문장 판정 대기 기사는 수집 때
  // 뒤 규칙 값으로 보통 채널에 들어갔다가 같은 실행의 늦은 판정으로 긴급이 되어 즉시 한 번 더 간다 — 그러면 :25 보통
  // 묶음에서 같은 기사를 또 받는다(크롤러 갈래 보고, #252). 보통→중요 '다시 보냄'(B1)은 보통이 먼저 나간 뒤라 무관.
  const urgentUrls = new Set<string>();
  if (normalEligible.length) {
    for (const r of queue) {
      const isUnitUrgent = audience === null
        ? r.topic === 'urgent'
        : (r.topic === 'news' && r.level === '긴급' && r.audience === audience);
      const u = (r.news_url || '').trim();
      if (isUnitUrgent && u) urgentUrls.add(u);
    }
  }
  const normalDeliver = urgentUrls.size
    ? normalEligible.filter((r) => !urgentUrls.has((r.news_url || '').trim()))
    : normalEligible;
  // 팀 채점 알림 — 팀 단위('t:')만. 기록이 없으면 하한 없음(호출측 큐 조회가 이미 72h로 자른다)
  const teamFromMs = s.last_team_sent_at ? new Date(s.last_team_sent_at).getTime() : -Infinity;
  const teamEligible = audience !== null && audience.startsWith('t:')
    ? queue.filter((r) => r.topic === 'team' && r.audience === audience && new Date(r.created_at).getTime() > teamFromMs)
    : [];

  return {
    audience,
    urgentEligible,
    urgent: matchTags(urgentEligible, s.tags),
    assemblyEligible: pickEligible(s.topic_assembly, 'assembly', s.last_assembly_sent_at),
    kmccEligible: pickEligible(s.topic_kmcc, 'kmcc', s.last_kmcc_sent_at),
    normalOn,
    normalFromMs,
    normalEligible,
    normal: matchTags(normalDeliver, s.tags),
    moreButton: !isNormal,
    teamEligible,
  };
}

/**
 * 발송 성공 뒤 쓸 워터마크 칸(브리핑 날짜는 호출측이 앞에 넣는다 — 칸 순서까지 종전과 같게).
 * delivered가 아니라 **eligible** 기준, nowIso가 아니라 **max(created_at)**.
 * 보통은 평가했을 때만 — 중요만인 사람·즉시 호출은 last_normal_sent_at을 건드리지 않는다.
 * 팀 채점 알림은 맨 뒤(last_team_sent_at) — 팀 행이 없으면 칸이 없어 공통 구독자의 본문은 종전과 바이트 같다.
 */
export function watermarkPatch(p: SubPlan): Record<string, string> {
  const patch: Record<string, string> = {};
  const uMark = maxCreatedAt(p.urgentEligible);
  const aMark = maxCreatedAt(p.assemblyEligible);
  const kMark = maxCreatedAt(p.kmccEligible);
  const nMark = p.normalOn ? maxCreatedAt(p.normalEligible) : null;
  const tMark = maxCreatedAt(p.teamEligible || []);
  if (uMark) patch.last_urgent_sent_at = uMark;
  if (aMark) patch.last_assembly_sent_at = aMark;
  if (kMark) patch.last_kmcc_sent_at = kMark;
  if (nMark) patch.last_normal_sent_at = nMark;
  if (tMark) patch.last_team_sent_at = tMark;
  return patch;
}

/**
 * 팀 채점 알림 한 덩어리 — 행 html은 크롤러가 만든 완성 블록(제목·blockquote·링크, crawler._grading_notice_html)이라
 * 파싱하지 않고 같은 글은 한 번만, 구분선으로 잇는다. mergeQueueBlocks를 거치지 않는다(제목의 「20건」을 건수 머리로 오인).
 */
export function renderTeamNotices(rows: QueueRow[]): string {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const r of rows) {
    const h = (r.html || '').trim();
    if (!h || seen.has(h)) continue;
    seen.add(h);
    out.push(h);
  }
  return out.join('\n\n───\n\n');
}

/**
 * 보통 묶음 한 통 — `🟡 <b>보통 뉴스 N건</b> <i>(구간)</i>` + 빈 줄 + `1. html` 항목(빈 줄 구분).
 * 주요 뉴스(renderNewsItems)와 같은 꼴: **html은 파싱하지 않고 순수 append**, 중복 제거 키는 news_url,
 * N = 태그 거름·중복 제거 뒤 건수. mergeQueueBlocks를 거치지 않는다(`N. ` 오인 병합 경로 밖).
 * 구간(KST) = 보통 워터마크(fromMs) ~ 이번에 평가한 가장 늦은 행(toIso = 워터마크 전진값) — 다음 통의 구간과 맞물린다.
 * 같은 날이면 `HH:MM~HH:MM`, 날짜가 걸치면 `M/D HH:MM~M/D HH:MM`(news_more.formatRange — '더 보기'와 같은 표기).
 */
export function renderNormalBatch(rows: QueueRow[], fromMs: number, toIso: string | null): string {
  const seen = new Set<string>();
  const picked: QueueRow[] = [];
  for (const r of rows) {
    const k = (r.news_url || '').trim();
    if (k) { if (seen.has(k)) continue; seen.add(k); }
    picked.push(r);
  }
  if (!picked.length) return '';
  const toMs = toIso ? new Date(toIso).getTime() : NaN;
  const range = Number.isFinite(fromMs) && Number.isFinite(toMs) && fromMs < toMs
    ? ` <i>(${escapeHtml(formatRange(fromMs, toMs))})</i>`
    : '';
  // 한 통 상한 — splitByLines(기본 3조각 ≈11.7KB)가 뒤를 「이하 생략」으로 자르면 워터마크는 전부 넘어가 잘린 기사가
  // 영영 안 간다(리뷰 #252-1). 그래서 **가장 최근 NORMAL_BATCH_MAX건**만 싣고 앞선 몫은 건수 + 대시보드 링크로 알린다
  // (평소 한 시간치는 4~5건 — 넘는 것은 밤사이·재활성 뒤 같은 드문 경우).
  const shown = picked.length > NORMAL_BATCH_MAX ? picked.slice(picked.length - NORMAL_BATCH_MAX) : picked;
  const omitted = picked.length - shown.length;
  const body = shown.map((r, i) => `${i + 1}. ${r.html}`).join('\n\n');
  const tail = omitted
    ? `\n\n<i>… 앞선 ${omitted}건은 대시보드에서 볼 수 있습니다</i> — <a href="${DASHBOARD_URL}?p=news">뉴스 보기</a>`
    : '';
  return `🟡 <b>보통 뉴스 ${picked.length}건</b>${range}\n\n${body}${tail}`;
}

export const NORMAL_BATCH_MAX = 40;

/**
 * PostgREST 1,000행 상한을 넘는 목록 읽기 — 호출측이 `.order(created_at).order(id).range(from, to)`를 건 조회를
 * fetchPage로 넘긴다. 한 페이지라도 실패하면 {rows: [], error} — 부분 목록으로 워터마크가 앞 페이지 끝까지만
 * 전진하면 같은 created_at(한 번에 벌크 insert된 행은 시각이 같다)의 나머지 행이 영구 소실될 수 있어서다.
 */
export async function fetchAllPages<T>(
  fetchPage: (from: number, to: number) => PromiseLike<{ data: T[] | null; error: unknown }>,
  pageSize = 1000,
  maxPages = 50,
): Promise<{ rows: T[]; error: unknown }> {
  const rows: T[] = [];
  for (let p = 0; p < maxPages; p++) {
    const from = p * pageSize;
    const { data, error } = await fetchPage(from, from + pageSize - 1);
    if (error) return { rows: [], error };
    const got = data || [];
    rows.push(...got);
    if (got.length < pageSize) return { rows, error: null };
  }
  return { rows: [], error: new Error(`페이지 상한 ${maxPages} 초과`) };
}
