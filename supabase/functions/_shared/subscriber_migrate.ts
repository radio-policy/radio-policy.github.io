// ============================================================================
//  공용: 구독자 방 번호 옮기기 (#322, 2026-10-20) — send-subscriber-briefing / telegram-webhook 공용
//
//  텔레그램 그룹방이 슈퍼그룹으로 바뀌면 방 번호(chat_id)가 새로 생기고, 옛 번호로 보낸 sendMessage는 영원히
//  400 「group chat was upgraded to a supergroup chat」 + parameters.migrate_to_chat_id(새 번호)로 실패한다.
//  발송 함수는 실패하면 워터마크를 안 올려 다음 정각에 다시 시도하므로, 번호를 옮기지 않으면 그 방은 한 통도 못 받은 채
//  매시 「실패 1」만 쌓인다(10-18~10-20 실 단위 구독 그룹 방 하나, 이틀 넘게).
//
//  옮기는 법: telegram_subscribers의 chat_id(기본키, 다른 표가 외래키로 물지 않음)를 새 번호로 바꾼다 — 팀·실·권한·
//  워터마크가 행째 따라간다. 사용 기록(telegram_usage·chat_logs·answer_feedback)의 옛 번호는 이력이라 그대로 둔다.
//  새 번호 행이 이미 있으면(새 방에서 /start를 먼저 눌렀다 등) 번호는 바꾸지 않고 옛 행만 끈다(active=false) —
//  옛 번호로는 다시 보낼 수 없으니 켜 두면 매시 실패만 되풀이한다. 두 행을 합치는 일은 운영자가 한다(알림 한 줄).
//  기본키 충돌(23505)로 「이미 있음」을 가리므로 미리 읽고 쓰는 사이의 경합이 없다.
// ============================================================================

import { escapeHtml, sendTelegramHtml } from './telegram_format.ts';

const T = 'telegram_subscribers';
const COLS = 'chat_id, first_name, username';

// supabase-js 클라이언트(또는 시험용 가짜) — 쓰는 사슬은 update().eq().select() · select().eq().maybeSingle() · update().eq()
// deno-lint-ignore no-explicit-any
export type Db = { from: (table: string) => any };

// moved = 이번에 옮김 / already = 이미 새 번호 행만 있음(웹훅이 먼저 옮겼거나 전환 알림 두 통 중 둘째) /
// conflict = 두 번호 행이 다 있어 못 옮김(옛 행은 끔) / absent = 두 번호 다 구독자 아님 / error = DB 오류(다음에 다시)
export type MigrateStatus = 'moved' | 'already' | 'conflict' | 'absent' | 'error';
export interface MigrateResult {
  status: MigrateStatus;
  oldId: number;
  newId: number;
  name: string;
  deactivated?: boolean;   // conflict일 때 옛 행을 껐는지
  error?: unknown;
}

function subName(r: { first_name?: string | null; username?: string | null } | null | undefined): string {
  return (r?.first_name || (r?.username ? '@' + r.username : '') || '').trim();
}

export async function migrateSubscriberChat(db: Db, oldId: number, newId: number): Promise<MigrateResult> {
  const base = { oldId, newId, name: '' };
  if (!oldId || !newId || oldId === newId) return { ...base, status: 'absent' };
  const now = new Date().toISOString();
  const { data, error } = await db.from(T).update({ chat_id: newId, updated_at: now }).eq('chat_id', oldId).select(COLS);
  if (!error) {
    const rows = (data || []) as Array<{ first_name?: string | null; username?: string | null }>;
    if (rows.length) return { ...base, status: 'moved', name: subName(rows[0]) };
    // 옛 행이 없다 — 이미 옮겨졌는지 새 번호로 확인
    const { data: cur, error: e2 } = await db.from(T).select(COLS).eq('chat_id', newId).maybeSingle();
    if (e2) return { ...base, status: 'error', error: e2 };
    return cur ? { ...base, status: 'already', name: subName(cur) } : { ...base, status: 'absent' };
  }
  if ((error as { code?: string }).code === '23505') {
    const { data: off, error: e3 } = await db.from(T).update({ active: false, updated_at: now }).eq('chat_id', oldId).select(COLS);
    const offRows = (off || []) as Array<{ first_name?: string | null; username?: string | null }>;
    return { ...base, status: 'conflict', name: subName(offRows[0]), deactivated: !e3 && offRows.length > 0 };
  }
  return { ...base, status: 'error', error };
}

// 운영자 봇에 보낼 한 줄(옮겼을 때·못 옮겼을 때만). already·absent·error는 null — error는 다음 발송이 다시 시도하고
// 하트비트 「실패 N」으로 보이므로 매시 알림을 쌓지 않는다.
export function migrateNotice(r: MigrateResult, where: string): string | null {
  const who = escapeHtml(r.name || '(이름 없음)');
  if (r.status === 'moved') {
    return `🔀 구독자 방 번호 옮김(슈퍼그룹 전환 · ${escapeHtml(where)}): ${who} ${r.oldId} → ${r.newId}`;
  }
  if (r.status === 'conflict') {
    return `⚠️ 구독자 방 번호 못 옮김(슈퍼그룹 전환 · ${escapeHtml(where)}): ${who} ${r.oldId} → ${r.newId}\n` +
      `새 번호 행이 이미 있어 번호는 그대로 두고, 옛 행은 ${r.deactivated ? '껐습니다(active=false)' : '끄지도 못했습니다'}. ` +
      '팀·실·권한을 확인해 한 행으로 합쳐 주세요.';
  }
  return null;
}

// 웹훅 서비스 메시지 → (옛 번호, 새 번호). 옛 방에는 migrate_to_chat_id, 새 방에는 migrate_from_chat_id가 온다
// (둘 다 글자 없는 메시지, allowed_updates 'message'로 들어온다 — 10-18 01:11 실측 두 통, 1초 간격).
export function migrationPair(msg: unknown): { oldId: number; newId: number } | null {
  const m = msg as { chat?: { id?: unknown }; migrate_to_chat_id?: unknown; migrate_from_chat_id?: unknown } | null | undefined;
  const here = m?.chat?.id;
  if (typeof here !== 'number') return null;
  if (typeof m?.migrate_to_chat_id === 'number') return { oldId: here, newId: m.migrate_to_chat_id };
  if (typeof m?.migrate_from_chat_id === 'number') return { oldId: m.migrate_from_chat_id, newId: here };
  return null;
}

// ── 한 구독자에게 메시지 묶음 보내기(send-subscriber-briefing 발송 루프) ──
// 종전 루프와 같다: 순서대로 보내고 하나라도 실패하면 멈춘다(호출측은 ok일 때만 워터마크 전진), 403 차단은 active=false.
// 더한 것(#322): 전환 응답을 받으면 번호를 옮기고(moved·already) 같은 메시지를 새 번호로 다시 보낸 뒤 나머지도 새 번호로.
// 한 번만 옮긴다 — 새 번호가 또 전환 응답이면 실패로 멈춘다. 호출측은 돌려준 chatId로 워터마크를 쓴다.
export interface DeliverMsg { text: string; extra?: Record<string, unknown> }
export interface DeliverResult { ok: boolean; chatId: number; blocked: boolean; migration: MigrateResult | null }

export async function deliverToSubscriber(
  db: Db, token: string, chatId: number, msgs: DeliverMsg[],
  opts: { delayMs?: number; onMigrate?: (r: MigrateResult) => Promise<void> } = {},
): Promise<DeliverResult> {
  const delayMs = opts.delayMs ?? 50;   // 텔레그램 레이트리밋 여유
  let cur = chatId;
  let migration: MigrateResult | null = null;
  for (const m of msgs) {
    let r = await sendTelegramHtml(token, cur, m.text, m.extra ?? {});
    if (typeof r === 'object' && !migration) {
      migration = await migrateSubscriberChat(db, cur, r.migrateTo);
      if (migration.status === 'error') console.error('[구독자 방 번호 옮기기 실패 — 다음 발송에 다시]', cur, r.migrateTo, migration.error);
      try { await opts.onMigrate?.(migration); } catch (e) { console.error('[방 번호 옮김 알림 실패(무시)]', e); }
      if (migration.status !== 'moved' && migration.status !== 'already') return { ok: false, chatId: cur, blocked: false, migration };
      cur = r.migrateTo;
      r = await sendTelegramHtml(token, cur, m.text, m.extra ?? {});
    }
    if (r === 'blocked') {
      await db.from(T).update({ active: false }).eq('chat_id', cur);
      return { ok: false, chatId: cur, blocked: true, migration };
    }
    if (r !== true) return { ok: false, chatId: cur, blocked: false, migration };
    if (delayMs > 0) await new Promise((res) => setTimeout(res, delayMs));
  }
  return { ok: true, chatId: cur, blocked: false, migration };
}
