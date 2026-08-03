// ============================================================================
//  뉴스 관심분야 태그 — **단일 원본**
//
//  이 목록은 3곳이 동시에 알아야 한다: ①Haiku 태그 판정 프롬프트(crawler.py) ②구독 설정
//  버튼(telegram-webhook) ③발송 칩(send-subscriber-briefing). 한 곳만 DB로 빼면 드리프트만
//  생기므로 app_config로 옮기지 않는다. Python 쪽은 이 파일의 사본 + 상호 참조 주석.
//
//  slug는 ASCII(LLM 토큰 절약·비교 안정), 화면 문구는 한글.
//  label = 설정 버튼용(무엇을 켜는지), chip = 기사 줄용(짧게).
//  `legislation`은 일부러 `assembly`가 아니다 — 기존 topic_assembly(법안 동향 토픽)와 이름이
//  겹치면 "토픽"과 "관심분야"가 섞인다.
// ============================================================================

export interface NewsTag { slug: string; label: string; chip: string }

export const NEWS_TAGS: NewsTag[] = [
  { slug: 'spectrum',    label: '주파수·네트워크', chip: '주파수·망' },
  { slug: 'market',      label: '요금·시장',       chip: '요금·시장' },
  { slug: 'regulation',  label: '규제·제재',       chip: '규제·제재' },
  { slug: 'security',    label: '보안·개인정보',   chip: '보안·정보' },
  { slug: 'ai',          label: 'AI 정책',         chip: 'AI' },
  { slug: 'legislation', label: '국회·입법',       chip: '국회·입법' },
];

export const TAG_SLUGS: string[] = NEWS_TAGS.map((t) => t.slug);
const CHIP = new Map(NEWS_TAGS.map((t) => [t.slug, t.chip] as const));

// 기사에 붙은 태그 중 **구독자 관심분야와 겹치는 것만** 최대 max개의 칩 문구로.
// 구독자가 '전체 수신'(빈 배열)이면 기사 태그 순서 그대로. 미등록 slug는 조용히 버린다.
export function pickChips(articleTags: string[] | null, subTags: string[] | null, max = 2): string[] {
  const a = (articleTags || []).filter((t) => CHIP.has(t));
  const s = (subTags || []).filter((t) => CHIP.has(t));
  const picked = s.length ? a.filter((t) => s.includes(t)) : a;
  return picked.slice(0, max).map((t) => CHIP.get(t)!);
}
