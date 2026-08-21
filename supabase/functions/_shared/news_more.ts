// ============================================================================
//  '더 보기' 버튼 규약 — 발송(send-subscriber-briefing)이 굽고 웹훅(telegram-webhook)이 읽는다.
//
//  인코딩과 디코딩이 **한 파일에 같이 있어야 한다.** 두 함수에 흩어 두면 한쪽만 고쳤을 때
//  버튼이 조용히 '만료된 버튼'으로만 응답한다(에러도 안 난다).
//
//  callback_data는 텔레그램 **64바이트 상한**이다. epoch '분' 정수 2개 + offset이라
//  `mn|29245680|29245740|0` ≈ 22바이트로 여유가 크다. 같은 상한을 assemCallbackData가
//  이미 같은 방식(| 구분 + 길이 검사)으로 다루고 있다(telegram-webhook/index.ts).
//
//  버튼은 **눌린 시각이 아니라 각인된 구간**을 보여준다. 그래서 구간을 버튼 문구와 결과
//  헤더 양쪽에 실제 시각(KST)으로 적는다 — 2시간 전 메시지의 버튼을 누른 사람이 옛날 기사를
//  보고 고장으로 오해하는 걸 막는 유일한 장치다.
// ============================================================================

const KST_OFFSET_MS = 9 * 3600 * 1000;
export const MORE_PAGE_SIZE = 8;

export interface MoreQuery { fromMs: number; toMs: number; offset: number }

/** (from, to] 구간 + offset → callback_data. 구간이 유효하지 않으면 null(=버튼 생략). */
export function encodeMoreCallback(fromMs: number, toMs: number, offset = 0): string | null {
  if (!Number.isFinite(fromMs) || !Number.isFinite(toMs) || fromMs >= toMs) return null;
  const d = `mn|${Math.floor(fromMs / 60000)}|${Math.floor(toMs / 60000)}|${Math.max(0, offset)}`;
  return new TextEncoder().encode(d).length <= 64 ? d : null;
}

export function parseMoreCallback(data: string): MoreQuery | null {
  const p = (data || '').split('|');
  if (p[0] !== 'mn' || p.length < 4) return null;
  const f = Number(p[1]), t = Number(p[2]), o = Number(p[3]);
  if (!Number.isFinite(f) || !Number.isFinite(t) || f >= t) return null;
  return { fromMs: f * 60000, toMs: t * 60000, offset: Number.isFinite(o) ? Math.max(0, o) : 0 };
}

function kstParts(ms: number) {
  const d = new Date(ms + KST_OFFSET_MS);
  return {
    day: d.toISOString().slice(0, 10),
    hhmm: d.toISOString().slice(11, 16),
    md: `${d.getUTCMonth() + 1}/${d.getUTCDate()}`,
  };
}

/** 구간 표기. 같은 날이면 `12:54~13:53`, 날짜가 걸치면 `8/19 18:54~8/20 06:54`. */
export function formatRange(fromMs: number, toMs: number): string {
  const a = kstParts(fromMs), b = kstParts(toMs);
  return a.day === b.day
    ? `${a.hhmm}~${b.hhmm}`
    : `${a.md} ${a.hhmm}~${b.md} ${b.hhmm}`;
}

/** 버튼 문구. 날짜가 걸치는 구간은 길어지므로 시각을 빼고 결과 헤더에만 전체를 적는다. */
export function moreButtonText(fromMs: number, toMs: number): string {
  const a = kstParts(fromMs), b = kstParts(toMs);
  return a.day === b.day
    ? `🟡 ${a.hhmm}~${b.hhmm} 뉴스 더 보기`
    : '🟡 이전 구간 뉴스 더 보기';
}

/** 주요 뉴스 마지막 조각에 실을 reply_markup. 구간이 유효하지 않으면 undefined(버튼 생략). */
export function moreButton(fromMs: number, toIso: string | null): Record<string, unknown> | undefined {
  if (!toIso) return undefined;
  const toMs = new Date(toIso).getTime();
  const data = encodeMoreCallback(fromMs, toMs, 0);
  if (!data) return undefined;
  return {
    reply_markup: {
      inline_keyboard: [[{ text: moreButtonText(fromMs, toMs), callback_data: data }]],
    },
  };
}
