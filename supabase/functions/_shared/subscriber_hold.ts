// ============================================================================
//  발송 보류 재확인 — 순수 함수 (#256-보론 → 팀·실 등급, 2026-10-05 S0 · 설계 local_docs/팀채점_설계_261004.md §8 ⓑ)
//
//  app_config.subscriber_hold가 켜져 있으면 send-subscriber-briefing이 발송 직전 큐의 중요 행을 **지금 등급**으로 다시 보고,
//  긴급이 아니게 된 기사(운영자가 내린 것)·지워진 기사를 발송분에서 뺀다(eligible에는 남겨 워터마크는 넘어간다).
//
//  종전 구멍: 받는 단위 행(topic 'news' · level '긴급' · audience 't:<팀>'|'d:<실>')도 **공통값(news_feed.urgency)만** 보아,
//  팀 규칙이 올린 팀 전용 긴급(공통은 보통·참고)을 보류 기간 내내 전부 뺐다 — 09-30~10-01 「유령 공공와이파이」 3건 ×
//  팀2·사업협력실 6행(팀2 rule_260927 set 긴급). 이제 단위 행은 크롤러 알림(run_audience_alerts)과 **같은 함수**
//  — urgency_rules.js alertTeamLevel·alertDivisionLevel(= Python alert_team_level·alert_division_level, 케이스
//  tests/fixtures/urgency_team_cases.json) — 로 그 단위의 지금 알림 등급을 계산해 긴급이 아닐 때만 뺀다.
//  공통 행(topic 'urgent')은 종전 식 그대로(공통값 ≠ 긴급이면 뺌). 조회 실패 = 빼지 않음(fail-open — 보내는 쪽).
//
//  subscriber_queue.ts에 두지 않은 이유: 그 파일은 admin-daily-report도 import한다 — 매처를 끌어들이면 그 함수까지
//  재배포 대상이 된다. 이 파일은 send-subscriber-briefing만 쓴다. 시험: tests/subscriber_hold.test.ts(DB·네트워크 0).
// ============================================================================

import type { QueueRow } from './subscriber_queue.ts';
// 팀 층 매처(#250·#252) — 브라우저·node·크롤러(Python 판)와 같은 파일이라 globalThis로 받는다(rag.ts의 rag_core.js와 같은 방식)
import './urgency_rules.js';
// deno-lint-ignore no-explicit-any
const UrgencyRules = (globalThis as any).UrgencyRules;

/** team_urgency 행 — alertTeamLevel이 읽는 칸만 */
export interface HoldTeamRow {
  news_id: string; team_id: number; urgency: string; source: string; rule_id: string | null;
}

export interface HoldLookup {
  /** url → 지금 공통값·기사 id. **null = 조회 실패 → 아무것도 빼지 않는다**. 없는 url = 지워진 기사 → 뺀다(종전과 같다) */
  news: Map<string, { id: string; urgency: string }> | null;
  /** 기사 id → {팀 id: 행}. null = 조회 실패 → 단위 행은 빼지 않는다 */
  teamRows: Map<string, Record<number, HoldTeamRow>> | null;
  /** 팀 규칙 {id: 행}(꺼진 것 포함 — alertTeamLevel이 enabled·team_id를 본다). null = 조회 실패 → 단위 행은 빼지 않는다 */
  rulesById: Record<string, unknown> | null;
  /** 실 → 팀 id(teams sort_order·id 순 — 크롤러 _alert_units와 같다). null = 조회 실패 → 실장 행은 빼지 않는다 */
  divTeams: Record<string, number[]> | null;
}

/** 재확인할 행 — 공통 중요(topic 'urgent')와 단위 중요(topic 'news' · '긴급'), news_url 있는 것만(종전 조건 그대로) */
export function holdRecheckRows(queue: QueueRow[]): QueueRow[] {
  return queue.filter((r) => (r.topic === 'urgent' || (r.topic === 'news' && r.level === '긴급')) && !!(r.news_url || '').trim());
}

/** 뺄지 정하는 열쇠 — 공통 행은 url만, 단위 행은 단위 + url(같은 기사도 팀마다 등급이 다르다) */
export function holdKey(r: QueueRow): string {
  return (r.topic === 'news' ? (r.audience || '') : '') + '\u0000' + (r.news_url || '').trim();
}

/** team_urgency를 읽어야 할 팀 id — 't:<팀>' + 'd:<실>'의 팀들(divTeams가 없으면 실은 빼고). 오름차순 */
export function holdTeamsNeeded(rows: QueueRow[], divTeams: Record<string, number[]> | null): number[] {
  const out = new Set<number>();
  for (const r of rows) {
    if (r.topic !== 'news') continue;
    const aud = r.audience || '';
    const mt = /^t:(\d+)$/.exec(aud);
    if (mt) out.add(Number(mt[1]));
    else if (aud.startsWith('d:') && divTeams) for (const t of divTeams[aud.slice(2)] || []) out.add(Number(t));
  }
  return [...out].sort((a, b) => a - b);
}

/** 뺄 행의 열쇠(holdKey) 집합. 조회 실패 갈래는 HoldLookup 주석 그대로 */
export function holdDropKeys(rows: QueueRow[], lk: HoldLookup): Set<string> {
  const drop = new Set<string>();
  if (!lk.news) return drop;
  for (const r of holdRecheckRows(rows)) {
    const key = holdKey(r);
    const g = lk.news.get((r.news_url || '').trim());
    if (!g) { drop.add(key); continue; }                       // 지워진 기사 — 공통·단위 모두 뺀다(종전과 같다)
    if (r.topic === 'urgent') { if (g.urgency !== '긴급') drop.add(key); continue; }
    const aud = r.audience || '';
    const mt = /^t:(\d+)$/.exec(aud);
    let level: string;
    if (mt || aud.startsWith('d:')) {
      if (!lk.teamRows || !lk.rulesById) continue;              // 팀 층을 모른다 — 빼지 않음
      const byTeam = lk.teamRows.get(g.id) || {};
      if (mt) {
        const tid = Number(mt[1]);
        level = UrgencyRules.alertTeamLevel(g.urgency, byTeam[tid] ?? null, lk.rulesById);
      } else {
        if (!lk.divTeams) continue;                              // 실의 팀 목록을 모른다 — 빼지 않음
        level = UrgencyRules.alertDivisionLevel(g.urgency, byTeam, lk.rulesById, lk.divTeams[aud.slice(2)] || []).level;
      }
    } else {
      level = g.urgency;                                         // 모르는 단위 꼴(없어야 한다) — 종전처럼 공통값
    }
    if (level !== '긴급') drop.add(key);
  }
  return drop;
}
