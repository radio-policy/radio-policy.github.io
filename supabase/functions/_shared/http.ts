// 대시보드가 부르는 Edge 함수 공용 CORS (2026-09-25, #217 — 개선안 §4-2-12 단계 C).
// claude-proxy·verify-citations·news-archive-search·operator-webhook 4곳에 같은 목록·함수가 복사돼 있었다.
// 목록 밖 origin(또는 origin 없음)에는 첫 항목(GitLab)을 돌려준다 — 브라우저가 거부하므로 사실상 차단.
// assembly-search 는 공개 조회 중계라 '*'를 일부러 유지한다(여기 쓰지 않음).
// 대시보드 정본(GitHub Pages) + 예비(GitLab Pages) + 로컬 검증용.
// ★ 두 Pages는 같은 커밋에서 상시 동일하게 유지되므로 둘 다 허용해야 한다. GitHub 주소가 빠져
//   있던 동안 그쪽으로 접속하면 preflight만 통과하고 POST가 막혀 AI 기능 전체가 죽었다
//   (증상은 화면에 "Failed to fetch" 한 줄뿐이라 원인 찾기가 어렵다). 2026-08-26 발견·수정.
//   목록이 4벌이던 시절엔 한 곳만 고치면 그 주소에서 기능이 조용히 죽었다 — 이제 여기 한 곳만 고친다.
export const ALLOWED_ORIGINS = [
  'https://radio-policy.gitlab.io',
  'https://radio-policy.github.io',
  'http://localhost:8000',
  'http://127.0.0.1:8000',
];

/** extraHeaders: 함수별로 더 받는 요청 헤더(예: claude-proxy의 'x-site'). */
export function corsHeaders(origin: string | null, extraHeaders: string[] = []): Record<string, string> {
  const allow = origin && ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    'Access-Control-Allow-Origin': allow,
    'Access-Control-Allow-Headers': ['authorization', 'content-type', ...extraHeaders].join(', '),
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Vary': 'Origin',
  };
}
