// ============================================================================
//  발송 보류 재확인 시험 (10-05 S0) — supabase/functions/_shared/subscriber_hold.ts
//  DB·네트워크 0. 실행:
//    deno test --allow-read tests/subscriber_hold.test.ts
//  (deno가 PATH에 없으면 npx --no-install deno test --allow-read tests/subscriber_hold.test.ts)
//
//  케이스 = tests/fixtures/subscriber_hold_cases.json. 끝의 재연은 실DB 값(2026-10-04 조회) — 09-30~10-01
//  「유령 공공와이파이」 3건이 팀2·사업협력실 단위에 긴급으로 큐에 들어갔고(팀2 rule_260927 set 긴급), 공통값은 보통·참고였다.
//  종전 재확인(공통값만)은 6행을 모두 뺐다 — 새 재확인은 하나도 빼지 않아야 한다(설계 §14 실데이터 항목).
// ============================================================================

import { deepStrictEqual } from 'node:assert/strict';
import type { QueueRow } from '../supabase/functions/_shared/subscriber_queue.ts';
import {
  type HoldLookup, type HoldTeamRow, holdDropKeys, holdKey, holdRecheckRows, holdTeamsNeeded,
} from '../supabase/functions/_shared/subscriber_hold.ts';

const FIX = JSON.parse(await Deno.readTextFile(new URL('./fixtures/subscriber_hold_cases.json', import.meta.url)));

let nextId = 1;
function qrow(r: { topic: string; audience?: string; level?: string; news_url?: string | null }): QueueRow {
  return {
    id: nextId++, topic: r.topic, html: 'x', created_at: '2026-10-04T00:00:00Z',
    news_url: r.news_url ?? null, tags: null, audience: r.audience ?? null, level: r.level ?? null,
  };
}
// 'aud|url' — 공통 행은 '|url'
const keyStr = (k: string) => k.replace('\u0000', '|');

// deno-lint-ignore no-explicit-any
function lookupOf(c: any): HoldLookup {
  const news = c.news === null ? null : new Map(Object.entries(c.news) as Array<[string, { id: string; urgency: string }]>);
  let teamRows: Map<string, Record<number, HoldTeamRow>> | null = null;
  if (c.teamRows !== null) {
    teamRows = new Map();
    for (const [nid, rows] of Object.entries(c.teamRows as Record<string, HoldTeamRow[]>)) {
      const m: Record<number, HoldTeamRow> = {};
      for (const r of rows) m[r.team_id] = { ...r, news_id: nid };
      teamRows.set(nid, m);
    }
  }
  return {
    news, teamRows,
    rulesById: c.rulesNull ? null : FIX.rules,
    divTeams: c.divTeamsNull ? null : FIX.divTeams,
  };
}

for (const c of FIX.cases) {
  Deno.test(`보류 재확인 — ${c.name}`, () => {
    const rows = (c.rows as Array<Parameters<typeof qrow>[0]>).map(qrow);
    const got = [...holdDropKeys(rows, lookupOf(c))].map(keyStr).sort();
    deepStrictEqual(got, [...c.drop].sort());
  });
}

Deno.test('holdKey — 공통 행은 url만, 단위 행은 단위+url, 공백은 다듬음', () => {
  deepStrictEqual(keyStr(holdKey(qrow({ topic: 'urgent', news_url: ' u1 ' }))), '|u1');
  deepStrictEqual(keyStr(holdKey(qrow({ topic: 'news', audience: 't:2', level: '긴급', news_url: 'u1' }))), 't:2|u1');
});

Deno.test('holdRecheckRows — 공통 중요·단위 긴급(url 있음)만', () => {
  const rows = [
    qrow({ topic: 'urgent', news_url: 'a' }), qrow({ topic: 'urgent', news_url: null }),
    qrow({ topic: 'news', audience: 't:2', level: '긴급', news_url: 'b' }),
    qrow({ topic: 'news', audience: 't:2', level: '보통', news_url: 'c' }),
    qrow({ topic: 'assembly' }), qrow({ topic: 'kmcc' }),
  ];
  deepStrictEqual(holdRecheckRows(rows).map((r) => r.news_url), ['a', 'b']);
});

Deno.test('holdTeamsNeeded — 팀 + 실의 팀(팀 목록 실패면 실은 뺌), 오름차순·중복 없음', () => {
  const rows = [
    qrow({ topic: 'news', audience: 't:5', level: '긴급', news_url: 'a' }),
    qrow({ topic: 'news', audience: 'd:사업협력실', level: '긴급', news_url: 'a' }),
    qrow({ topic: 'news', audience: 't:2', level: '긴급', news_url: 'b' }),
    qrow({ topic: 'urgent', news_url: 'a' }),
  ];
  deepStrictEqual(holdTeamsNeeded(rows, FIX.divTeams), [1, 2, 3, 5]);
  deepStrictEqual(holdTeamsNeeded(rows, null), [2, 5]);
  deepStrictEqual(holdTeamsNeeded(rows, { '사업협력실': [] }), [2, 5]);
});

// ── 실데이터 재연(2026-10-04 조회: subscriber_queue 1118·1119·1254·1255·1343·1344, team_urgency 3행, 팀 규칙 2개) ──
const REPLAY = {
  rows: [
    { topic: 'news', audience: 'd:사업협력실', level: '긴급', news_url: 'https://n.news.naver.com/mnews/article/666/0000125442?sid=101' },
    { topic: 'news', audience: 't:2', level: '긴급', news_url: 'https://n.news.naver.com/mnews/article/666/0000125442?sid=101' },
    { topic: 'news', audience: 'd:사업협력실', level: '긴급', news_url: 'https://www.idomin.com/news/articleView.html?idxno=2016035' },
    { topic: 'news', audience: 't:2', level: '긴급', news_url: 'https://www.idomin.com/news/articleView.html?idxno=2016035' },
    { topic: 'news', audience: 'd:사업협력실', level: '긴급', news_url: 'https://www.kbsm.net/news/view.php?idx=536074' },
    { topic: 'news', audience: 't:2', level: '긴급', news_url: 'https://www.kbsm.net/news/view.php?idx=536074' },
  ],
  news: {
    'https://n.news.naver.com/mnews/article/666/0000125442?sid=101': { id: 'e517c9ac-5366-4b3e-a642-e006d175cb78', urgency: '보통' },
    'https://www.idomin.com/news/articleView.html?idxno=2016035': { id: '1132a597-b51f-4d48-984c-877066423757', urgency: '참고' },
    'https://www.kbsm.net/news/view.php?idx=536074': { id: '79723ddb-3c0f-40b0-82b0-5a6487be2957', urgency: '보통' },
  } as Record<string, { id: string; urgency: string }>,
  teamRows: ['e517c9ac-5366-4b3e-a642-e006d175cb78', '1132a597-b51f-4d48-984c-877066423757', '79723ddb-3c0f-40b0-82b0-5a6487be2957']
    .map((nid) => ({ news_id: nid, team_id: 2, urgency: '긴급', source: 'rule', rule_id: 'rule_260927' })),
  rules: {
    rule_260927: { id: 'rule_260927', team_id: 2, enabled: true, mode: 'set', level: '긴급' },
    spectrum_policy: { id: 'spectrum_policy', team_id: 2, enabled: true, mode: 'min', level: '긴급' },
  },
  divTeams: { '정책개발실': [4, 5, 6, 7], '사업협력실': [1, 2, 3], '대외지원실': [8, 9, 10, 11] },
};

Deno.test('재연 — 유령 공공와이파이 3건 × 팀2·사업협력실: 종전 6행 모두 뺌 → 이제 0행', () => {
  const rows = REPLAY.rows.map(qrow);
  // 종전 식(index.ts 10-04 판): 공통값 ≠ 긴급이면 url로 뺐다
  const oldDrop = rows.filter((r) => REPLAY.news[(r.news_url || '').trim()]?.urgency !== '긴급');
  deepStrictEqual(oldDrop.length, 6);
  const teamRows = new Map<string, Record<number, HoldTeamRow>>();
  for (const t of REPLAY.teamRows) teamRows.set(t.news_id, { [t.team_id]: t });
  const lk: HoldLookup = { news: new Map(Object.entries(REPLAY.news)), teamRows, rulesById: REPLAY.rules, divTeams: REPLAY.divTeams };
  deepStrictEqual([...holdDropKeys(rows, lk)], []);
  // 운영자가 그 사이 팀 규칙을 끄면 다시 빠진다(공통값 보통·참고)
  const off = { ...REPLAY.rules, rule_260927: { ...REPLAY.rules.rule_260927, enabled: false } };
  deepStrictEqual(holdDropKeys(rows, { ...lk, rulesById: off }).size, 6);
});
