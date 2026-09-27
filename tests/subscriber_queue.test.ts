// ============================================================================
//  구독자 큐 고르기 시험 (#252, 2026-09-27) — supabase/functions/_shared/subscriber_queue.ts
//  DB·네트워크 0. 실행:
//    deno test --allow-read tests/subscriber_queue.test.ts
//  (deno가 PATH에 없으면 npx --no-install deno test --allow-read tests/subscriber_queue.test.ts)
//
//  핵심 보장: 팀·실이 없고 「중요만」인 공통 구독자는 **종전 send-subscriber-briefing과 같은 행을 고르고 같은
//  워터마크를 쓴다**(큐에 topic 'news' 행이 섞여도). 아래 oldPlan은 #252 직전 index.ts의 pickEligible·워터마크
//  식을 그대로 옮긴 것 — 고치지 말 것(대조 기준).
// ============================================================================

import { deepStrictEqual, strictEqual, ok } from 'node:assert/strict';
import {
  type QueueRow, type PickSub, audienceKey, maxCreatedAt, planSubscriber, watermarkPatch,
  renderNormalBatch, fetchAllPages, NORMAL_BATCH_MAX,
} from '../supabase/functions/_shared/subscriber_queue.ts';
import { matchTags } from '../supabase/functions/_shared/news_tags.ts';

// ── 종전 코드(#252 직전 index.ts 275~280·291~297·363~371행) 그대로 ─────────────────
function oldMaxCreatedAt(rows: QueueRow[]): string | null {
  let best: string | null = null;
  let bestMs = -Infinity;
  for (const r of rows) {
    const ms = new Date(r.created_at).getTime();
    if (ms > bestMs) { bestMs = ms; best = r.created_at; }
  }
  return best;
}
function oldPlan(queue: QueueRow[], s: PickSub, dayStartMs: number) {
  const pickEligible = (on: boolean, topic: string, lastSent: string | null): QueueRow[] => {
    if (!on) return [];
    const fromMs = lastSent ? new Date(lastSent).getTime() : dayStartMs;
    return queue.filter((r) => r.topic === topic && new Date(r.created_at).getTime() > fromMs);
  };
  const urgentEligible = pickEligible(s.topic_urgent, 'urgent', s.last_urgent_sent_at);
  const assemblyEligible = pickEligible(s.topic_assembly, 'assembly', s.last_assembly_sent_at);
  const kmccEligible = pickEligible(s.topic_kmcc, 'kmcc', s.last_kmcc_sent_at);
  const urgent = matchTags(urgentEligible, s.tags);
  const patch: Record<string, unknown> = {};
  const uMark = oldMaxCreatedAt(urgentEligible);
  const aMark = oldMaxCreatedAt(assemblyEligible);
  const kMark = oldMaxCreatedAt(kmccEligible);
  if (uMark) patch.last_urgent_sent_at = uMark;
  if (aMark) patch.last_assembly_sent_at = aMark;
  if (kMark) patch.last_kmcc_sent_at = kMark;
  return { urgentEligible, urgent, assembly: assemblyEligible, kmcc: kmccEligible, patch };
}
// ───────────────────────────────────────────────────────────────────────────────

// 기준 시각: 2026-09-27 11:25 KST (정기 발송), 오늘 0시 KST = 09-26 15:00Z
const NOW = Date.parse('2026-09-27T02:25:00Z');
const DAY0 = Date.parse('2026-09-26T15:00:00Z');
const H = 3600 * 1000;
// Postgres가 돌려주는 꼴(마이크로초 + +00:00)
const iso = (ms: number) => new Date(ms).toISOString().replace('Z', '') + '123+00:00';

let nextId = 1;
function row(topic: string, atMs: number, extra: Partial<QueueRow> = {}): QueueRow {
  const id = nextId++;
  const isNews = topic === 'news' || topic === 'urgent';
  return {
    id, topic, html: `<a href="https://n.example/${id}">기사 ${id}</a>\n   <i>매체</i>`,
    created_at: iso(atMs), news_url: isNews ? `https://n.example/${id}` : null, tags: null,
    audience: null, level: null, ...extra,
  };
}
const ids = (rows: QueueRow[]) => rows.map((r) => r.id);

function baseSub(over: Partial<PickSub> = {}): PickSub {
  return {
    topic_urgent: true, topic_assembly: true, topic_kmcc: true,
    last_urgent_sent_at: null, last_assembly_sent_at: null, last_kmcc_sent_at: null,
    last_normal_sent_at: null, team_id: null, division: null, news_level: 'urgent', tags: [],
    ...over,
  };
}

// 섞인 큐: 공통 urgent(태그·news_url 유무)·assembly·kmcc + 받는 단위 news 행(c/t:2/t:3/d:정책개발실 × 긴급/보통)
// + 같은 created_at(벌크 insert) 묶음 + 어제 행
function mixedQueue(): QueueRow[] {
  const q: QueueRow[] = [];
  const bulk = NOW - 3 * H;
  q.push(row('urgent', DAY0 - 5 * H));                                   // 어제(첫 발송 기준 밖)
  q.push(row('urgent', bulk, { tags: ['ai'] }), row('urgent', bulk, { tags: ['market'] }), row('urgent', bulk));
  q.push(row('urgent', NOW - 2 * H, { news_url: null }));                // 구버전 묶음 행
  q.push(row('assembly', NOW - 4 * H), row('kmcc', NOW - 90 * 60 * 1000));
  for (const aud of ['c', 't:2', 't:3', 'd:정책개발실']) {
    for (const lv of ['긴급', '보통']) {
      if (aud === 'c' && lv === '긴급') continue;                          // 공통 중요는 topic urgent(DB에 c·긴급 행 없음)
      q.push(row('news', NOW - 150 * 60 * 1000, { audience: aud, level: lv, tags: ['spectrum'] }));
      q.push(row('news', NOW - 40 * 60 * 1000, { audience: aud, level: lv }));
      q.push(row('news', NOW - 20 * 60 * 1000, { audience: aud, level: lv, tags: ['ai'] }));
    }
  }
  q.push(row('urgent', NOW - 10 * 60 * 1000));
  return q.sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at) || a.id - b.id);
}

function assertSameAsOld(queue: QueueRow[], s: PickSub, label: string) {
  for (const immediate of [false, true]) {
    const oldR = oldPlan(queue, s, DAY0);
    const oldNoNews = oldPlan(queue.filter((r) => r.topic !== 'news'), s, DAY0);   // news 행이 없던 시절과도 같다
    const p = planSubscriber(queue, s, { dayStartMs: DAY0, nowMs: NOW, immediate });
    const tag = `${label} immediate=${immediate}`;
    deepStrictEqual(ids(p.urgentEligible), ids(oldR.urgentEligible), tag + ' urgentEligible');
    deepStrictEqual(ids(p.urgent), ids(oldR.urgent), tag + ' urgent');
    deepStrictEqual(ids(p.assemblyEligible), ids(oldR.assembly), tag + ' assembly');
    deepStrictEqual(ids(p.kmccEligible), ids(oldR.kmcc), tag + ' kmcc');
    deepStrictEqual(ids(p.urgentEligible), ids(oldNoNews.urgentEligible), tag + ' urgentEligible(no news)');
    // 워터마크 — 값과 칸 순서까지(PATCH 본문 바이트 동일)
    strictEqual(JSON.stringify(watermarkPatch(p)), JSON.stringify(oldR.patch), tag + ' patch');
    strictEqual(maxCreatedAt(p.urgentEligible), oldMaxCreatedAt(oldR.urgentEligible), tag + " '더 보기' 끝");
    // 공통·중요만: 보통 없음, '더 보기' 그대로
    strictEqual(p.audience, null, tag + ' audience');
    strictEqual(p.normalOn, false, tag + ' normalOn');
    deepStrictEqual(p.normal, [], tag + ' normal');
    strictEqual(p.moreButton, true, tag + ' moreButton');
    ok(!('last_normal_sent_at' in watermarkPatch(p)), tag + ' no normal mark');
  }
}

Deno.test('audienceKey — 실 우선, 팀, 공통', () => {
  strictEqual(audienceKey({ team_id: null, division: null }), null);
  strictEqual(audienceKey({}), null);
  strictEqual(audienceKey({ team_id: 2, division: null }), 't:2');
  strictEqual(audienceKey({ team_id: null, division: '정책개발실' }), 'd:정책개발실');
  strictEqual(audienceKey({ team_id: 2, division: '정책개발실' }), 'd:정책개발실');   // DB CHECK로 불가, 그래도 실 우선
  strictEqual(audienceKey({ team_id: null, division: '' }), null);
});

Deno.test('공통 구독자(팀·실 없음·중요만) — 종전 코드와 같은 행·같은 워터마크', () => {
  const q = mixedQueue();
  const lastU = iso(NOW - 150 * 60 * 1000);
  const variants: Array<[string, Partial<PickSub>]> = [
    ['기본', {}],
    ['news_level 없음(undefined)', { news_level: undefined, team_id: undefined, division: undefined }],
    ['태그 ai', { tags: ['ai'] }],
    ['태그 market·security', { tags: ['market', 'security'] }],
    ['주요 뉴스 끔', { topic_urgent: false }],
    ['국회 끔·방미통위 끔', { topic_assembly: false, topic_kmcc: false }],
    ['워터마크 있음', { last_urgent_sent_at: lastU, last_assembly_sent_at: iso(NOW - 5 * H), last_kmcc_sent_at: iso(NOW) }],
    ['워터마크가 벌크 행과 같은 시각', { last_urgent_sent_at: iso(NOW - 3 * H) }],
    ['보통 워터마크만 있음(중요만)', { last_normal_sent_at: iso(NOW - 5 * H) }],
  ];
  for (const [label, over] of variants) assertSameAsOld(q, baseSub(over), label);
});

Deno.test('공통 구독자 — 무작위 큐 500벌 대조(시드 고정)', () => {
  let seed = 252;
  const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
  const pick = <T>(a: T[]) => a[Math.floor(rnd() * a.length)];
  const TAGS = [null, [], ['ai'], ['market'], ['spectrum', 'regulation'], ['security']];
  for (let n = 0; n < 500; n++) {
    const q: QueueRow[] = [];
    const len = Math.floor(rnd() * 40);
    for (let i = 0; i < len; i++) {
      const at = NOW - Math.floor(rnd() * 72) * H + (rnd() < 0.3 ? 0 : Math.floor(rnd() * H));
      const topic = pick(['urgent', 'urgent', 'assembly', 'kmcc', 'news', 'news']);
      const extra: Partial<QueueRow> = { tags: pick(TAGS) as string[] | null };
      if (topic === 'news') { extra.audience = pick(['c', 't:1', 't:2', 'd:사업협력실']); extra.level = pick(['긴급', '보통']); }
      if (topic === 'urgent' && rnd() < 0.2) extra.news_url = null;
      q.push(row(topic, at, extra));
    }
    q.sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at) || a.id - b.id);
    const mark = () => (rnd() < 0.4 ? null : iso(NOW - Math.floor(rnd() * 80) * H));
    const s = baseSub({
      topic_urgent: rnd() < 0.8, topic_assembly: rnd() < 0.7, topic_kmcc: rnd() < 0.7,
      last_urgent_sent_at: mark(), last_assembly_sent_at: mark(), last_kmcc_sent_at: mark(),
      last_normal_sent_at: mark(), tags: (pick(TAGS) as string[] | null) || [],
    });
    assertSameAsOld(q, s, `fuzz#${n}`);
  }
});

Deno.test('팀 구독자 — topic news·긴급·자기 단위 행만, 공통 urgent 행은 안 받는다', () => {
  const q = mixedQueue();
  const s = baseSub({ team_id: 2 });
  const p = planSubscriber(q, s, { dayStartMs: DAY0, nowMs: NOW, immediate: true });
  strictEqual(p.audience, 't:2');
  ok(p.urgentEligible.length === 3);
  for (const r of p.urgentEligible) {
    strictEqual(r.topic, 'news'); strictEqual(r.audience, 't:2'); strictEqual(r.level, '긴급');
  }
  deepStrictEqual(watermarkPatch(p).last_urgent_sent_at, maxCreatedAt(p.urgentEligible));
  strictEqual(p.moreButton, true);   // 중요만이면 '더 보기' 그대로
  // 워터마크 이후만
  const p2 = planSubscriber(q, baseSub({ team_id: 2, last_urgent_sent_at: iso(NOW - 40 * 60 * 1000) }),
    { dayStartMs: DAY0, nowMs: NOW, immediate: false });
  strictEqual(p2.urgentEligible.length, 1);
  // 태그 거름은 발송분에만, 워터마크는 평가 대상 기준
  const p3 = planSubscriber(q, baseSub({ team_id: 2, tags: ['market'] }), { dayStartMs: DAY0, nowMs: NOW, immediate: false });
  deepStrictEqual(p3.urgent.map((r) => r.tags), [null]);           // 태그 없는 행만 통과(fail-open), spectrum·ai는 빠짐
  strictEqual(watermarkPatch(p3).last_urgent_sent_at, maxCreatedAt(p3.urgentEligible));
  // 주요 뉴스를 끄면 팀 행도 없다
  const p4 = planSubscriber(q, baseSub({ team_id: 2, topic_urgent: false }), { dayStartMs: DAY0, nowMs: NOW, immediate: false });
  deepStrictEqual(p4.urgentEligible, []);
  ok(!('last_urgent_sent_at' in watermarkPatch(p4)));
  // 국회·방미통위는 팀과 무관하게 종전 그대로
  deepStrictEqual(ids(p.assemblyEligible), ids(oldPlan(q, s, DAY0).assembly));
  deepStrictEqual(ids(p.kmccEligible), ids(oldPlan(q, s, DAY0).kmcc));
});

Deno.test('실장 구독자 — d:<실> 행만', () => {
  const q = mixedQueue();
  const p = planSubscriber(q, baseSub({ division: '정책개발실' }), { dayStartMs: DAY0, nowMs: NOW, immediate: false });
  strictEqual(p.audience, 'd:정책개발실');
  strictEqual(p.urgentEligible.length, 3);
  ok(p.urgentEligible.every((r) => r.audience === 'd:정책개발실' && r.level === '긴급'));
});

Deno.test('보통 — 중요+보통·주요 뉴스 켬·정기 발송에서만, 첫 구간은 한 시간', () => {
  const q = mixedQueue();
  // 공통 + 중요+보통: 'c' 보통 행, 기록 없음 → max(0시, 지금−1h) 이후 = 40분 전·20분 전 2건
  const p = planSubscriber(q, baseSub({ news_level: 'normal' }), { dayStartMs: DAY0, nowMs: NOW, immediate: false });
  strictEqual(p.normalOn, true);
  strictEqual(p.normalFromMs, NOW - H);
  strictEqual(p.normalEligible.length, 2);
  ok(p.normalEligible.every((r) => r.topic === 'news' && r.audience === 'c' && r.level === '보통'));
  strictEqual(p.moreButton, false);                                 // 중요+보통이면 '더 보기' 없음
  // 중요는 공통 경로 그대로
  deepStrictEqual(ids(p.urgentEligible), ids(oldPlan(q, baseSub(), DAY0).urgentEligible));
  const patch = watermarkPatch(p);
  strictEqual(patch.last_normal_sent_at, maxCreatedAt(p.normalEligible));
  deepStrictEqual(Object.keys(patch), ['last_urgent_sent_at', 'last_assembly_sent_at', 'last_kmcc_sent_at', 'last_normal_sent_at']);

  // 즉시 호출: 보통은 평가도 워터마크도 없음 — 중요는 그대로
  const pi = planSubscriber(q, baseSub({ news_level: 'normal' }), { dayStartMs: DAY0, nowMs: NOW, immediate: true });
  strictEqual(pi.normalOn, false);
  deepStrictEqual(pi.normal, []);
  ok(!('last_normal_sent_at' in watermarkPatch(pi)));
  deepStrictEqual(ids(pi.urgentEligible), ids(p.urgentEligible));
  strictEqual(pi.moreButton, false);

  // 주요 뉴스 끔 → 보통도 없음
  const po = planSubscriber(q, baseSub({ news_level: 'normal', topic_urgent: false }), { dayStartMs: DAY0, nowMs: NOW, immediate: false });
  strictEqual(po.normalOn, false);
  deepStrictEqual(po.normalEligible, []);

  // 보통 워터마크가 있으면 거기서부터(한 시간 제한 없음 — 밤사이 쌓인 것도 다음 날 아침에 이어서)
  const pw = planSubscriber(q, baseSub({ news_level: 'normal', last_normal_sent_at: iso(NOW - 3 * H) }),
    { dayStartMs: DAY0, nowMs: NOW, immediate: false });
  strictEqual(pw.normalEligible.length, 3);

  // 0시 직후: 기록 없음이면 오늘 0시보다 앞으로 가지 않는다
  const early = DAY0 + 30 * 60 * 1000;
  const pe = planSubscriber([row('news', DAY0 - 10 * 60 * 1000, { audience: 'c', level: '보통' }),
    row('news', DAY0 + 10 * 60 * 1000, { audience: 'c', level: '보통' })],
    baseSub({ news_level: 'normal' }), { dayStartMs: DAY0, nowMs: early, immediate: false });
  strictEqual(pe.normalFromMs, DAY0);
  strictEqual(pe.normalEligible.length, 1);

  // 태그: 발송분만 거르고 워터마크는 평가 대상 기준
  const pt = planSubscriber(q, baseSub({ news_level: 'normal', tags: ['market'] }), { dayStartMs: DAY0, nowMs: NOW, immediate: false });
  strictEqual(pt.normalEligible.length, 2);
  strictEqual(pt.normal.length, 1);                                 // 태그 없는 40분 전 행만(20분 전은 ai)
  strictEqual(watermarkPatch(pt).last_normal_sent_at, maxCreatedAt(pt.normalEligible));

  // 팀 + 중요+보통: 't:2' 보통 행('c' 아님)
  const pteam = planSubscriber(q, baseSub({ team_id: 2, news_level: 'normal' }), { dayStartMs: DAY0, nowMs: NOW, immediate: false });
  ok(pteam.normalEligible.length === 2 && pteam.normalEligible.every((r) => r.audience === 't:2' && r.level === '보통'));
  ok(pteam.urgentEligible.every((r) => r.audience === 't:2' && r.level === '긴급'));
});

Deno.test('보통 — 같은 단위에 중요로도 들어간 기사는 보통 묶음에서 뺀다(워터마크 평가에는 남김)', () => {
  // 문장 판정 대기 기사: 수집 때 보통 채널 → 같은 실행 늦은 판정으로 긴급(즉시 발송) — :25 보통에서 또 가면 안 된다
  const url = 'https://n.example/late-1';
  const bo = row('news', NOW - 30 * 60 * 1000, { audience: 't:2', level: '보통', news_url: url });
  const gi = row('news', NOW - 29 * 60 * 1000, { audience: 't:2', level: '긴급', news_url: url });
  const other = row('news', NOW - 20 * 60 * 1000, { audience: 't:2', level: '보통' });
  const otherUnitUrgent = row('news', NOW - 25 * 60 * 1000, { audience: 't:3', level: '긴급', news_url: other.news_url });
  const p = planSubscriber([bo, gi, other, otherUnitUrgent], baseSub({ team_id: 2, news_level: 'normal' }),
    { dayStartMs: DAY0, nowMs: NOW, immediate: false });
  deepStrictEqual(ids(p.normalEligible), ids([bo, other]));        // 평가 대상(워터마크)은 둘 다
  deepStrictEqual(ids(p.normal), ids([other]));                    // 발송분에서는 긴급으로 간 기사만 빠짐(다른 단위의 긴급은 무관)
  strictEqual(watermarkPatch(p).last_normal_sent_at, other.created_at);
  // 공통 구독자: 공통 긴급(topic urgent) 행과 url이 같으면 'c' 보통에서 뺀다
  const cu = row('urgent', NOW - 50 * 60 * 1000, { news_url: url });
  const cb = row('news', NOW - 45 * 60 * 1000, { audience: 'c', level: '보통', news_url: url });
  const pc = planSubscriber([cu, cb], baseSub({ news_level: 'normal' }), { dayStartMs: DAY0, nowMs: NOW, immediate: false });
  deepStrictEqual(ids(pc.normalEligible), ids([cb]));
  deepStrictEqual(pc.normal, []);
});

Deno.test('renderNormalBatch — 머리줄·구간(KST)·번호·빈 줄·news_url 중복 제거', () => {
  const from = Date.parse('2026-09-27T01:25:00Z');   // 10:25 KST
  const a = row('news', from + 30 * 60 * 1000, { audience: 'c', level: '보통', html: '<a href="https://a">가 &amp; 나</a>\n   <i>매체A</i>' });
  const b = row('news', from + 55 * 60 * 1000, { audience: 'c', level: '보통', html: '<a href="https://b">다</a> <i>(관련 보도 2건)</i>\n   <i>매체B · 🏷 우리 팀 기준</i>' });
  const dup = { ...a, id: 999 };
  const out = renderNormalBatch([a, dup, b], from, b.created_at);
  strictEqual(out,
    '🟡 <b>보통 뉴스 2건</b> <i>(10:25~11:20)</i>\n\n' +
    '1. <a href="https://a">가 &amp; 나</a>\n   <i>매체A</i>\n\n' +
    '2. <a href="https://b">다</a> <i>(관련 보도 2건)</i>\n   <i>매체B · 🏷 우리 팀 기준</i>');
  // 날짜가 걸치면 날짜까지
  const overnight = renderNormalBatch([a], Date.parse('2026-09-26T09:25:00Z'), a.created_at);
  ok(overnight.startsWith('🟡 <b>보통 뉴스 1건</b> <i>(9/26 18:25~9/27 10:55)</i>\n\n1. '), overnight);
  // 줄 머리가 'N. '인 것은 번호 줄뿐(항목 안 둘째 줄은 들여쓰기)
  for (const line of out.split('\n')) ok(!/^\s*\d+\.\s/.test(line) || /^[12]\. <a /.test(line), line);
  strictEqual(renderNormalBatch([], from, null), '');
  strictEqual(renderNormalBatch([a], from, null), '🟡 <b>보통 뉴스 1건</b>\n\n1. ' + a.html);   // 구간을 모르면 생략
});

Deno.test('renderNormalBatch — 한 통 상한: 최근 NORMAL_BATCH_MAX건만, 앞선 몫은 건수 + 대시보드 링크', () => {
  const from = Date.parse('2026-09-27T01:25:00Z');
  const many = Array.from({ length: NORMAL_BATCH_MAX + 5 }, (_, i) =>
    row('news', from + (i + 1) * 1000, { id: 5000 + i, audience: 'c', level: '보통', news_url: `https://n/${i}`, html: `<a href="https://n/${i}">기사${i}</a>` }));
  const out = renderNormalBatch(many, from, many[many.length - 1].created_at);
  ok(out.startsWith(`🟡 <b>보통 뉴스 ${NORMAL_BATCH_MAX + 5}건</b>`), out.slice(0, 60));
  ok(!out.includes('>기사4<'), '가장 오래된 5건은 빠진다');
  ok(out.includes('>기사5<') && out.includes(`>기사${NORMAL_BATCH_MAX + 4}<`), '최근 상한 건수는 실린다');
  ok(out.endsWith('<i>… 앞선 5건은 대시보드에서 볼 수 있습니다</i> — <a href="https://radio-policy.github.io/?p=news">뉴스 보기</a>'), out.slice(-120));
  // 상한 이하면 꼬리 없음
  ok(!renderNormalBatch(many.slice(0, NORMAL_BATCH_MAX), from, null).includes('앞선'));
});

Deno.test('fetchAllPages — 1,000행 페이지 끝까지, 실패하면 통째로 빈 목록', async () => {
  const all = Array.from({ length: 2500 }, (_, i) => i);
  const calls: Array<[number, number]> = [];
  const r = await fetchAllPages<number>((from, to) => {
    calls.push([from, to]);
    return Promise.resolve({ data: all.slice(from, to + 1), error: null });
  });
  strictEqual(r.error, null);
  strictEqual(r.rows.length, 2500);
  deepStrictEqual(calls, [[0, 999], [1000, 1999], [2000, 2999]]);

  const exact = Array.from({ length: 1000 }, (_, i) => i);
  const calls2: number[] = [];
  const r2 = await fetchAllPages<number>((from, to) => { calls2.push(from); return Promise.resolve({ data: exact.slice(from, to + 1), error: null }); });
  strictEqual(r2.rows.length, 1000);
  deepStrictEqual(calls2, [0, 1000]);

  const r3 = await fetchAllPages<number>((from, to) =>
    Promise.resolve(from === 0 ? { data: all.slice(0, 1000), error: null } : { data: null, error: { message: 'timeout' } }));
  deepStrictEqual(r3.rows, []);
  deepStrictEqual(r3.error, { message: 'timeout' });

  const r4 = await fetchAllPages<number>(() => Promise.resolve({ data: null, error: null }));
  deepStrictEqual(r4, { rows: [], error: null });
});
