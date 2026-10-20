// ============================================================================
//  구독자 방 번호 옮기기 시험 (#322, 2026-10-20) — supabase/functions/_shared/subscriber_migrate.ts · telegram_format.ts
//  가짜 fetch(텔레그램)·가짜 DB(telegram_subscribers 한 표)만 쓴다 — 네트워크·실DB 0. 실행:
//    deno test --allow-read tests/subscriber_migrate.test.ts
//  (deno가 PATH에 없으면 npx --no-install deno test --allow-read tests/subscriber_migrate.test.ts)
//
//  핵심 보장: 옛 번호로 보내다 슈퍼그룹 전환 응답(400 + migrate_to_chat_id)을 받으면 **같은 실행 안에서** DB 번호가
//  새 번호로 바뀌고, 그 메시지와 나머지가 새 번호로 나간다. 새 번호 행이 이미 있으면 번호를 바꾸지 않고 옛 행만 끈다.
//  방 번호는 모두 지어낸 값이다(실제 구독자 번호를 적지 않는다).
// ============================================================================

import { deepStrictEqual, strictEqual, ok } from 'node:assert/strict';
import { migrateToChatId, sendTelegramHtml } from '../supabase/functions/_shared/telegram_format.ts';
import {
  type MigrateResult, deliverToSubscriber, migrateNotice, migrateSubscriberChat, migrationPair,
} from '../supabase/functions/_shared/subscriber_migrate.ts';

const OLD = -4000000001;          // 옛 그룹방(지어낸 값)
const NEW = -1009000000001;       // 슈퍼그룹 새 번호(지어낸 값)
const MIGRATE_BODY = (to: number) => JSON.stringify({
  ok: false, error_code: 400,
  description: 'Bad Request: group chat was upgraded to a supergroup chat',
  parameters: { migrate_to_chat_id: to },
});

// ── 가짜 DB: supabase-js 사슬 중 이 파일이 쓰는 것만 ───────────────────────────
type Row = Record<string, unknown> & { chat_id: number };
class FakeDb {
  rows = new Map<number, Row>();
  failUpdate: { code?: string; message: string } | null = null;   // 다음 update 하나를 이 오류로
  from(t: string) { strictEqual(t, 'telegram_subscribers'); return new FakeQuery(this); }
}
class FakeQuery {
  private op: 'select' | 'update' | null = null;
  private patch: Record<string, unknown> = {};
  private id: number | null = null;
  constructor(private db: FakeDb) {}
  update(p: Record<string, unknown>) { this.op = 'update'; this.patch = p; return this; }
  select(_cols: string) { if (!this.op) this.op = 'select'; return this; }
  eq(col: string, v: number) { strictEqual(col, 'chat_id'); this.id = v; return this; }
  maybeSingle() { return Promise.resolve(this.run(true)); }
  then<A, B>(res: (v: unknown) => A, rej?: (e: unknown) => B) { return Promise.resolve(this.run(false)).then(res, rej); }
  private run(single: boolean): { data: unknown; error: unknown } {
    const id = this.id as number;
    if (this.op === 'select') {
      const r = this.db.rows.get(id) ?? null;
      return { data: single ? r : (r ? [r] : []), error: null };
    }
    if (this.db.failUpdate) { const e = this.db.failUpdate; this.db.failUpdate = null; return { data: null, error: e }; }
    const r = this.db.rows.get(id);
    if (!r) return { data: [], error: null };
    const to = this.patch.chat_id as number | undefined;
    if (to !== undefined && to !== id && this.db.rows.has(to)) {
      return { data: null, error: { code: '23505', message: 'duplicate key value violates unique constraint "telegram_subscribers_pkey"' } };
    }
    const next = { ...r, ...this.patch } as Row;
    this.db.rows.delete(id);
    this.db.rows.set(next.chat_id, next);
    return { data: [next], error: null };
  }
}
function subRow(chatId: number, extra: Record<string, unknown> = {}): Row {
  return { chat_id: chatId, first_name: '시험 그룹', username: null, active: true, division: '시험실', team_id: null,
    ai_allowed: true, last_urgent_sent_at: '2026-10-18T00:00:00Z', ...extra };
}

// ── 가짜 텔레그램 ──────────────────────────────────────────────────────────────
interface Call { chat_id: number; text: string; parse_mode?: string; reply_markup?: unknown }
function fakeTelegram(opts: { migrated?: Record<number, number>; blocked?: number[]; badHtml?: boolean } = {}) {
  const calls: Call[] = [];
  const orig = globalThis.fetch;
  globalThis.fetch = ((_url: string | URL | Request, init?: RequestInit) => {
    const b = JSON.parse(String(init?.body)) as Call;
    calls.push(b);
    const to = opts.migrated?.[b.chat_id];
    if (to !== undefined) return Promise.resolve(new Response(MIGRATE_BODY(to), { status: 400 }));
    if (opts.blocked?.includes(b.chat_id)) {
      return Promise.resolve(new Response('{"ok":false,"error_code":403,"description":"Forbidden: bot was blocked by the user"}', { status: 403 }));
    }
    if (opts.badHtml && b.parse_mode === 'HTML') {
      return Promise.resolve(new Response('{"ok":false,"error_code":400,"description":"Bad Request: can\'t parse entities"}', { status: 400 }));
    }
    return Promise.resolve(new Response('{"ok":true,"result":{}}', { status: 200 }));
  }) as typeof fetch;
  return { calls, restore: () => { globalThis.fetch = orig; } };
}
// console.error를 잠시 막는다(실패 경로 시험의 로그가 결과를 덮지 않게)
async function quiet<T>(fn: () => Promise<T>): Promise<T> {
  const e = console.error; console.error = () => {};
  try { return await fn(); } finally { console.error = e; }
}

const MSGS = [
  { text: '📡 <b>모닝 브리핑</b>' },
  { text: '📡 <b>통신·전파 정책 주요 뉴스 1건</b>' },
  { text: '🏛️ 국회', extra: { reply_markup: { inline_keyboard: [[{ text: '더 보기', callback_data: 'm:1:2' }]] } } },
];

// ── 1. 응답 본문 읽기 ──────────────────────────────────────────────────────────
Deno.test('migrateToChatId: 전환 응답에서만 새 번호', () => {
  strictEqual(migrateToChatId(MIGRATE_BODY(NEW)), NEW);
  strictEqual(migrateToChatId('{"ok":false,"error_code":400,"description":"Bad Request: can\'t parse entities"}'), null);
  strictEqual(migrateToChatId('<html>502</html>'), null);
  strictEqual(migrateToChatId('{"parameters":{"migrate_to_chat_id":"-100"}}'), null);   // 숫자가 아니면 안 믿는다
  strictEqual(migrateToChatId('{"parameters":{"retry_after":5}}'), null);
});

// ── 2. sendTelegramHtml ─────────────────────────────────────────────────────────
Deno.test('sendTelegramHtml: 전환 응답이면 plain 재시도 없이 { migrateTo }', async () => {
  const tg = fakeTelegram({ migrated: { [OLD]: NEW } });
  try {
    const r = await sendTelegramHtml('T', OLD, '<b>x</b>');
    deepStrictEqual(r, { migrateTo: NEW });
    strictEqual(tg.calls.length, 1);   // 종전엔 태그 뺀 글로 한 번 더 보냈다 — 같은 400
  } finally { tg.restore(); }
});
Deno.test('sendTelegramHtml: HTML 파싱 400은 종전처럼 plain 재시도 → true', async () => {
  const tg = fakeTelegram({ badHtml: true });
  try {
    strictEqual(await sendTelegramHtml('T', 123, '<b>x</b>'), true);
    strictEqual(tg.calls.length, 2);
    strictEqual(tg.calls[1].parse_mode, undefined);
    strictEqual(tg.calls[1].text, 'x');
  } finally { tg.restore(); }
});
Deno.test('sendTelegramHtml: 403은 종전처럼 blocked', async () => {
  const tg = fakeTelegram({ blocked: [123] });
  try { strictEqual(await sendTelegramHtml('T', 123, 'x'), 'blocked'); } finally { tg.restore(); }
});

// ── 3. 정시 발송 루프(deliverToSubscriber) — 같은 실행 안에서 옮기고 새 번호로 ─────────
Deno.test('발송: 전환 응답 → DB 번호가 새 번호로, 그 메시지와 나머지가 새 번호로', async () => {
  const db = new FakeDb();
  db.rows.set(OLD, subRow(OLD));
  const tg = fakeTelegram({ migrated: { [OLD]: NEW } });
  const seen: MigrateResult[] = [];
  try {
    const d = await deliverToSubscriber(db, 'T', OLD, MSGS, { delayMs: 0, onMigrate: async (m) => { seen.push(m); } });
    strictEqual(d.ok, true);
    strictEqual(d.chatId, NEW);                       // 호출측은 이 번호로 워터마크를 쓴다
    deepStrictEqual(tg.calls.map((c) => c.chat_id), [OLD, NEW, NEW, NEW]);
    deepStrictEqual(tg.calls.slice(1).map((c) => c.text), MSGS.map((m) => m.text));
    deepStrictEqual(tg.calls[3].reply_markup, MSGS[2].extra?.reply_markup);   // '더 보기' 버튼도 그대로
    ok(!db.rows.has(OLD));
    const row = db.rows.get(NEW)!;
    strictEqual(row.division, '시험실');              // 실·권한·워터마크가 행째 따라간다
    strictEqual(row.ai_allowed, true);
    strictEqual(row.last_urgent_sent_at, '2026-10-18T00:00:00Z');
    strictEqual(row.active, true);
    strictEqual(seen.length, 1);
    strictEqual(seen[0].status, 'moved');
    const t = migrateNotice(seen[0], '정시 발송')!;
    ok(t.includes('🔀') && t.includes(`${OLD} → ${NEW}`) && t.includes('시험 그룹'));
  } finally { tg.restore(); }
});

Deno.test('발송: 웹훅이 먼저 옮긴 뒤(already) — 새 번호로 보내고 성공, 알림 없음', async () => {
  const db = new FakeDb();
  db.rows.set(NEW, subRow(NEW));                      // 발송 함수는 옮기기 전에 옛 번호를 읽었다(경합)
  const tg = fakeTelegram({ migrated: { [OLD]: NEW } });
  const seen: MigrateResult[] = [];
  try {
    const d = await deliverToSubscriber(db, 'T', OLD, MSGS.slice(0, 1), { delayMs: 0, onMigrate: async (m) => { seen.push(m); } });
    strictEqual(d.ok, true);
    strictEqual(d.chatId, NEW);
    deepStrictEqual(tg.calls.map((c) => c.chat_id), [OLD, NEW]);
    strictEqual(seen[0].status, 'already');
    strictEqual(migrateNotice(seen[0], '정시 발송'), null);
  } finally { tg.restore(); }
});

Deno.test('발송: 새 번호 행이 이미 있으면 번호는 그대로, 옛 행만 끄고 실패(새 번호로 안 보냄)', async () => {
  const db = new FakeDb();
  db.rows.set(OLD, subRow(OLD));
  db.rows.set(NEW, subRow(NEW, { division: null, first_name: '새 방' }));
  const tg = fakeTelegram({ migrated: { [OLD]: NEW } });
  const seen: MigrateResult[] = [];
  try {
    const d = await deliverToSubscriber(db, 'T', OLD, MSGS, { delayMs: 0, onMigrate: async (m) => { seen.push(m); } });
    strictEqual(d.ok, false);                         // 워터마크 안 올림(종전 규칙)
    strictEqual(d.chatId, OLD);
    deepStrictEqual(tg.calls.map((c) => c.chat_id), [OLD]);
    strictEqual(db.rows.get(OLD)!.active, false);     // 다음 정각부터 이 행은 대상이 아니다 — 매시 실패가 멈춘다
    strictEqual(db.rows.get(OLD)!.division, '시험실');
    strictEqual(db.rows.get(NEW)!.division, null);    // 새 행은 손대지 않는다
    strictEqual(db.rows.get(NEW)!.active, true);
    strictEqual(seen[0].status, 'conflict');
    strictEqual(seen[0].deactivated, true);
    const t = migrateNotice(seen[0], '정시 발송')!;
    ok(t.startsWith('⚠️') && t.includes('껐습니다') && t.includes('합쳐'));
  } finally { tg.restore(); }
});

Deno.test('발송: 두 번호 다 구독자가 아니면(absent) 실패, DB 무변경', async () => {
  const db = new FakeDb();
  const tg = fakeTelegram({ migrated: { [OLD]: NEW } });
  try {
    const d = await deliverToSubscriber(db, 'T', OLD, MSGS, { delayMs: 0 });
    strictEqual(d.ok, false);
    strictEqual(d.migration?.status, 'absent');
    strictEqual(db.rows.size, 0);
    strictEqual(tg.calls.length, 1);
  } finally { tg.restore(); }
});

Deno.test('발송: DB 오류(23505 아님)면 error — 실패로 멈추고 알림 없음(다음 정각에 다시)', async () => {
  const db = new FakeDb();
  db.rows.set(OLD, subRow(OLD));
  db.failUpdate = { code: '57014', message: 'canceling statement due to statement timeout' };
  const tg = fakeTelegram({ migrated: { [OLD]: NEW } });
  const seen: MigrateResult[] = [];
  try {
    const d = await quiet(() => deliverToSubscriber(db, 'T', OLD, MSGS, { delayMs: 0, onMigrate: async (m) => { seen.push(m); } }));
    strictEqual(d.ok, false);
    strictEqual(seen[0].status, 'error');
    strictEqual(migrateNotice(seen[0], '정시 발송'), null);
    ok(db.rows.has(OLD) && db.rows.get(OLD)!.active === true);
  } finally { tg.restore(); }
});

Deno.test('발송: 한 번만 옮긴다 — 새 번호도 전환 응답이면 실패', async () => {
  const NEWER = -1009000000002;
  const db = new FakeDb();
  db.rows.set(OLD, subRow(OLD));
  const tg = fakeTelegram({ migrated: { [OLD]: NEW, [NEW]: NEWER } });
  try {
    const d = await quiet(() => deliverToSubscriber(db, 'T', OLD, MSGS, { delayMs: 0 }));
    strictEqual(d.ok, false);
    deepStrictEqual(tg.calls.map((c) => c.chat_id), [OLD, NEW]);
    ok(db.rows.has(NEW) && !db.rows.has(NEWER));
  } finally { tg.restore(); }
});

Deno.test('발송: 옮긴 뒤 새 방에서 403이면 새 번호 행을 끈다', async () => {
  const db = new FakeDb();
  db.rows.set(OLD, subRow(OLD));
  const tg = fakeTelegram({ migrated: { [OLD]: NEW }, blocked: [NEW] });
  try {
    const d = await deliverToSubscriber(db, 'T', OLD, MSGS, { delayMs: 0 });
    strictEqual(d.ok, false);
    strictEqual(d.blocked, true);
    strictEqual(db.rows.get(NEW)!.active, false);
  } finally { tg.restore(); }
});

Deno.test('발송: 전환이 없으면 종전 루프와 같다 — 순서대로, 실패에서 멈춤', async () => {
  const db = new FakeDb();
  db.rows.set(77, subRow(77));
  let tg = fakeTelegram();
  try {
    const d = await deliverToSubscriber(db, 'T', 77, MSGS, { delayMs: 0 });
    deepStrictEqual(d, { ok: true, chatId: 77, blocked: false, migration: null });
    deepStrictEqual(tg.calls.map((c) => c.text), MSGS.map((m) => m.text));
  } finally { tg.restore(); }
  tg = fakeTelegram({ blocked: [77] });
  try {
    const d = await deliverToSubscriber(db, 'T', 77, MSGS, { delayMs: 0 });
    strictEqual(d.ok, false);
    strictEqual(tg.calls.length, 1);
    strictEqual(db.rows.get(77)!.active, false);
  } finally { tg.restore(); }
  const db2 = new FakeDb();
  const d2 = await deliverToSubscriber(db2, 'T', 77, [], { delayMs: 0 });   // 보낼 게 없어도 ok(워터마크 전진 경로)
  deepStrictEqual(d2, { ok: true, chatId: 77, blocked: false, migration: null });
});

// ── 4. 웹훅 서비스 메시지 ───────────────────────────────────────────────────────
Deno.test('migrationPair: 옛 방 migrate_to · 새 방 migrate_from · 보통 메시지는 null', () => {
  deepStrictEqual(migrationPair({ chat: { id: OLD }, migrate_to_chat_id: NEW }), { oldId: OLD, newId: NEW });
  deepStrictEqual(migrationPair({ chat: { id: NEW }, migrate_from_chat_id: OLD }), { oldId: OLD, newId: NEW });
  strictEqual(migrationPair({ chat: { id: OLD }, text: '/start' }), null);
  strictEqual(migrationPair(undefined), null);
  strictEqual(migrationPair({ migrate_to_chat_id: NEW }), null);   // 방 번호 없는 메시지
});

Deno.test('웹훅: 전환 알림 두 통(새 방 먼저) — 첫 통이 옮기고 둘째는 already, 운영자 알림은 한 번', async () => {
  const db = new FakeDb();
  db.rows.set(OLD, subRow(OLD));
  const notices: string[] = [];
  for (const msg of [{ chat: { id: NEW }, migrate_from_chat_id: OLD }, { chat: { id: OLD }, migrate_to_chat_id: NEW }]) {
    const p = migrationPair(msg)!;
    const r = await migrateSubscriberChat(db, p.oldId, p.newId);
    const t = migrateNotice(r, '전환 알림');
    if (t) notices.push(t);
  }
  strictEqual(notices.length, 1);
  ok(notices[0].includes('전환 알림'));
  ok(!db.rows.has(OLD) && db.rows.has(NEW));
});

Deno.test('migrateSubscriberChat: 같은 번호·0은 아무것도 안 함', async () => {
  const db = new FakeDb();
  db.rows.set(OLD, subRow(OLD));
  strictEqual((await migrateSubscriberChat(db, OLD, OLD)).status, 'absent');
  strictEqual((await migrateSubscriberChat(db, OLD, 0)).status, 'absent');
  ok(db.rows.has(OLD));
});

Deno.test('migrateNotice: 이름의 꺾쇠는 이스케이프', () => {
  const t = migrateNotice({ status: 'moved', oldId: OLD, newId: NEW, name: '<팀>&' }, '전환 알림')!;
  ok(t.includes('&lt;팀&gt;&amp;'));
});
