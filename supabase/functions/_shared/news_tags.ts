// ============================================================================
//  뉴스 관심분야 태그 — **단일 원본**
//
//  이 목록은 3곳이 동시에 알아야 한다: ①Haiku 태그 판정 프롬프트(crawler.py) ②구독 설정
//  버튼(telegram-webhook) ③발송 칩(send-subscriber-briefing). 한 곳만 DB로 빼면 드리프트만
//  생기므로 app_config로 옮기지 않는다. Python 쪽은 이 파일의 사본 + 상호 참조 주석.
//
//  slug는 ASCII(LLM 토큰 절약·비교 안정), 화면 문구는 한글.
//  label = 설정 버튼용(무엇을 켜는지), chip = 기사 줄용(짧게).
//  '국회·입법' 태그는 두지 않는다(2026-08-03 운영자 판단). 이유 셋:
//   ① 국회 정보는 topic_assembly(법안 동향)가 국회 API에서 직접 받아 더 정확하고 빠르다.
//   ② 뉴스는 '경로'가 아니라 '주제'로 분류해야 쓸모가 있다 — 「단통법 폐지 후속 입법」의 실질은
//      단말 유통 규제이고, 그 기사가 필요한 사람은 대관이 아니라 요금·유통 담당이다.
//   ③ 실측에서 30건 표본 0건, 실운영에서는 정부·업계 간담회 기사에 오태깅됐다.
//  순수 국회 절차 기사는 어느 태그에도 안 걸려 전원에게 간다(fail-open) — 손실 없음.
// ============================================================================

export interface NewsTag { slug: string; label: string; chip: string }

export const NEWS_TAGS: NewsTag[] = [
  { slug: 'spectrum',    label: '주파수·네트워크', chip: '주파수·망' },
  { slug: 'market',      label: '요금·시장',       chip: '요금·시장' },
  { slug: 'regulation',  label: '규제·제재',       chip: '규제·제재' },
  { slug: 'security',    label: '보안·개인정보',   chip: '보안·정보' },
  { slug: 'ai',          label: 'AI 정책',         chip: 'AI' },
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
