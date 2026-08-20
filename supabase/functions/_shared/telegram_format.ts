// ============================================================================
//  공용: 텔레그램 HTML 포맷·발송 유틸 (telegram-webhook / send-subscriber-briefing 공용)
//  - 텔레그램 parse_mode:HTML은 <b> <i> <a> <code> <pre> 정도만 지원.
//  - 이스케이프 안 된 & < > 가 본문에 있으면 sendMessage가 400으로 전체 실패하므로
//    동적 텍스트는 반드시 escapeHtml을 거친다. 실패 시 plain 폴백은 sendTelegramHtml이 담당.
// ============================================================================

export function escapeHtml(s: string): string {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// HTML 태그 제거(plain 폴백용) + 엔티티 복원
export function stripTags(s: string): string {
  return (s || '').replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
}

// 긴 본문을 줄 경계에서 limit 이하 조각으로 분할 (태그는 줄을 넘지 않는 전제 — 아래 변환기들이 보장)
// maxParts 초과분은 버리고 마지막 조각에 잘림 안내를 붙인다 (알림 폭증 방지 — 배경역사 #44 취지)
export function splitByLines(text: string, limit = 3900, maxParts = 3): string[] {
  const lines = (text || '').split('\n');
  const parts: string[] = [];
  let buf = '';
  for (const line of lines) {
    if (buf && (buf.length + line.length + 1) > limit) {
      parts.push(buf);
      buf = line;
    } else {
      buf = buf ? buf + '\n' + line : line;
    }
    if (parts.length >= maxParts) break;
  }
  if (parts.length < maxParts && buf) parts.push(buf);
  else if (parts.length >= maxParts && buf) {
    parts[maxParts - 1] += '\n\n<i>...(분량 제한으로 이하 생략 — 전문은 대시보드 참조)</i>';
  }
  return parts;
}

// ── 모닝 브리핑 plain 텍스트 → 텔레그램 HTML ──
// morning_briefing.py의 _briefing_to_html(이메일용)과 같은 줄 단위 규칙을 텔레그램 문법으로 적용.
// 입력은 [ID:] 태그·SKT 영향 분석 줄이 이미 제거된 텍스트여야 한다(호출측 책임).
// • 제목 — 출처  /  선행 불릿·긴급도 이모지와 후행 " — 출처"는 링크 밖으로 뺀다
// 이모지는 문자클래스([🔴🟡🟢])로 쓰면 u 플래그 없이 서로게이트 페어가 쪼개져 깨진다 → 교대(|)로 표기
const BULLET_RE = /^(\s*[•·]\s*)((?:🔴|🟡|🟢)\s*)?(.+?)(\s+[—–\-]\s+[^—–]+)?$/;
const LINK_RE = /^\s*🔗\s*(https?:\S+)\s*$/;

export function briefingToTelegramHtml(text: string): string {
  const lines = (text || '').split('\n').map((l) => l.trimEnd());
  const skip = new Set<number>();
  const out: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    if (skip.has(i)) continue;
    const line = lines[i];
    const esc = escapeHtml(line);
    if (/^📡/.test(line)) { out.push('<b>' + esc + '</b>'); continue; }          // 헤더
    if (/^\[.+\]$/.test(line.trim())) { out.push('<b>' + esc + '</b>'); continue; } // [주요 뉴스] 등 섹션
    if (/^📢/.test(line)) { out.push('<b>' + esc + '</b>'); continue; }          // 입법예고 섹션

    const bulletM = line.match(BULLET_RE);
    if (bulletM && bulletM[3]) {
      // 제목 자체를 하이퍼링크로 — 뒤따르는 "🔗 URL" 줄을 찾아 흡수하고 그 줄은 출력하지 않는다
      // (별도 링크 줄이 화면을 잡아먹던 문제. URL은 요약(→) 줄 다음에 오므로 3줄까지 살펴본다)
      let url = '';
      for (let j = i + 1; j < Math.min(i + 4, lines.length); j++) {
        if (BULLET_RE.test(lines[j]) && lines[j].trim()) break;   // 다음 기사에 도달하면 중단
        const m = lines[j].match(LINK_RE);
        if (m) { url = m[1]; skip.add(j); break; }
      }
      const head = escapeHtml(bulletM[1]) + escapeHtml(bulletM[2] || '');
      const title = escapeHtml(bulletM[3]);
      const tail = escapeHtml(bulletM[4] || '');
      out.push(head + (url ? `<a href="${escapeHtml(url)}">${title}</a>` : `<b>${title}</b>`) + tail);
      continue;
    }

    const linkM = line.match(LINK_RE);   // 짝을 못 찾은 고아 링크 — 그때만 링크 줄로 남긴다
    if (linkM) { out.push('🔗 <a href="' + escapeHtml(linkM[1]) + '">기사 보기</a>'); continue; }

    out.push(esc);
  }
  return out.join('\n');
}

// ── 마크다운(자문 답변) → 텔레그램 HTML ──
// Sonnet 답변의 기본 마크다운만 변환: 헤더/굵게/링크/불릿. 표·코드블록 등은 그대로 둔다.
export function mdToTelegramHtml(md: string): string {
  const out: string[] = [];
  for (const raw of (md || '').split('\n')) {
    let line = escapeHtml(raw);
    const h = line.match(/^\s*#{1,6}\s+(.*)$/);
    if (h) { out.push('<b>' + h[1] + '</b>'); continue; }
    line = line.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
    line = line.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2">$1</a>');
    line = line.replace(/^(\s*)[-*]\s+/, '$1• ');
    out.push(line);
  }
  return out.join('\n');
}

// ── 발송: HTML 시도 → 400이면 plain 폴백 ──
// 반환: true=성공, false=실패, 'blocked'=사용자가 봇 차단(403 — 호출측에서 active=false 처리)
export async function sendTelegramHtml(
  token: string, chatId: number | string, html: string,
  extra: Record<string, unknown> = {},
): Promise<true | false | 'blocked'> {
  const url = `https://api.telegram.org/bot${token}/sendMessage`;
  const base = { chat_id: chatId, disable_web_page_preview: true, ...extra };
  let res = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...base, text: html, parse_mode: 'HTML' }),
  });
  if (res.ok) return true;
  if (res.status === 403) return 'blocked';
  if (res.status === 400) {
    // HTML 파싱 실패 가능성 — plain으로 재시도 (전체 발송 실패 방지, fail-open 원칙)
    res = await fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...base, text: stripTags(html) }),
    });
    if (res.ok) return true;
    if (res.status === 403) return 'blocked';
  }
  console.error('[텔레그램 발송 실패]', chatId, res.status, (await res.text()).slice(0, 200));
  return false;
}

export const DASHBOARD_URL = 'https://radio-policy.gitlab.io/';
