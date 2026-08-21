// ============================================================================
//  같은 사건 기사 묶기 — **원본: app.js:3462~3566 (_extractKeywords/_titleSimilarity/
//  _eventBigrams/_eventSimilarity/EVENT_SIM_THRESHOLD/_groupNews)**
//
//  ⚠️ 임계값과 계수 선택은 대시보드 쪽 주석에 실측 근거가 붙어 있다. 여기만 고치지 말 것 —
//  대시보드와 텔레그램이 같은 사건을 다르게 묶으면 그 자체가 신뢰를 깎는다. 고칠 일이 생기면
//  app.js와 이 파일을 **함께** 고치고 양쪽 주석을 갱신한다.
//
//  왜 event 완전일치가 아닌가(2026-08-21 실측): 선별이 35건씩 배치로 돌아 같은 사건이라도
//  배치가 다르면 라벨 표현이 어긋난다. 「SKT 3G 신규가입 중단…주파수 효율화」와
//  「SKT 3G 신규 가입 중단」이 같은 사건인데 문자열은 다르다. group by로는 하나도 안 묶인다.
//
//  ⚠️ 임계 0.45의 한계 — 전수 백테스트로 확인(2026-08-21, 보통·라벨 보유 675건 / 같은 날
//  23,297쌍). 초기에 "0.12~0.61 사이가 비어 있다"고 적었으나 그건 15건 표본의 착시였고,
//  실제 분포는 연속이다(0.40~0.45에 486쌍, ≥0.45에 5,300쌍). 알려진 두 모드:
//    · SKT↔KT 오병합(구조적): 라틴 'skt'가 bigram 'kt'를 품고 겹침 계수 분모가 짧은 쪽이라
//      짧은 「KT …」 라벨이 「SKT …」 라벨의 준부분집합이 된다. 둘 다 [spectrum] 태그라
//      태그 AND로도 안 걸러진다. 실측: 0.692~0.900.
//    · 과소분리: 같은 3G 사건 쌍이 0.389~0.444로 갈라지기도 한다.
//  그럼에도 0.45를 그대로 쓰는 이유는 **대시보드가 이미 같은 임계로 돌고 있어서**다. 여기만
//  바꾸면 두 화면의 묶음이 어긋난다. 통신사 가드는 별도 후속 작업(양쪽 동시 수정 조건).
// ============================================================================

export interface GroupableNews {
  title: string;
  event?: string | null;
  tags?: string[] | null;
  published_at?: string | null;
  created_at?: string | null;
}

export interface NewsGroup<T> {
  head: T;        // 화면에 보일 대표 기사 (가장 이른 published_at)
  related: number; // 대표를 뺀 나머지 수 → '(관련 보도 N건)'
}

// 라벨 유사도 임계. app.js의 EVENT_SIM_THRESHOLD와 같은 값이어야 한다.
const EVENT_SIM_THRESHOLD = 0.45;
// 라벨이 없을 때만 쓰는 제목 유사도 임계. app.js:3557과 같은 값.
const TITLE_SIM_THRESHOLD = 0.15;

const STOPWORDS = [
  '관련', '대한', '위한', '통해', '대해', '기반', '위해', '이후', '이전',
  '지난', '오는', '올해', '내년', '지금', '현재', '새로운', '이번', '해당', '추진',
  '강화한다', '강화하는', '나선다', '밝혔다', '위해서',
];

function extractKeywords(title: string): string[] {
  const words = String(title || '').match(/[가-힣]{2,}/g) || [];
  // 숫자+한글 혼합에서 조사 제거 (예: 6300개로 → 6300개)
  const mixed = (String(title || '').match(/[0-9]+[가-힣]+/g) || []).map((w) =>
    w.replace(/(으로|에서|부터|까지|로서|로는|로도|에는|에도|이나|이며|이고|로|을|를|이|가|은|는|의|에|과|와|도|만)$/, '')
  );
  // 지명 정규화: '제주도' → '제주', '서울시' → '서울'
  const normalized = words.map((w) => w.replace(/([가-힣]{2,})(도|시|군|구|광장)$/, '$1'));
  return normalized.concat(mixed).filter((w) => !STOPWORDS.includes(w) && w.length >= 2);
}

function titleSimilarity(t1: string, t2: string): number {
  const k1 = extractKeywords(t1);
  const k2 = extractKeywords(t2);
  if (!k1.length || !k2.length) return 0;
  const shared = k1.filter((w) => k2.includes(w));
  // 공유 키워드 1개만으로는 묶지 않는다 — '기지국' 같은 흔한 도메인 단어가 서로 다른
  // 주제를 한 그룹으로 잇는 오류 방지 (app.js:3485)
  if (shared.length < 2) return 0;
  return shared.length / Math.max(k1.length, k2.length);
}

function eventBigrams(s: string): string[] {
  const t = String(s || '').toLowerCase().replace(/[^0-9a-z가-힣]/g, '');
  const out: string[] = [];
  for (let i = 0; i + 1 < t.length; i++) out.push(t.slice(i, i + 2));
  return out;
}

// 겹침 계수(교집합 / 짧은 쪽 길이). Dice를 안 쓰는 이유는 app.js 주석 참조 —
// 같은 사건이라도 한쪽만 수치를 담아 길이가 벌어지면 Dice가 그걸 유사도 하락으로 계산한다.
function eventSimilarity(e1: string, e2: string): number {
  const a = eventBigrams(e1);
  const b = eventBigrams(e2);
  if (!a.length || !b.length) return 0;
  const bag: Record<string, number> = {};
  for (const g of b) bag[g] = (bag[g] || 0) + 1;
  let hit = 0;
  for (const g of a) {
    if (bag[g] > 0) { bag[g]--; hit++; }
  }
  return hit / Math.min(a.length, b.length);
}

function sameEvent(a: GroupableNews, b: GroupableNews): boolean {
  const ev1 = (a.event || '').trim();
  const ev2 = (b.event || '').trim();
  const simOk = (ev1 && ev2)
    ? eventSimilarity(ev1, ev2) >= EVENT_SIM_THRESHOLD
    : titleSimilarity(a.title, b.title) >= TITLE_SIM_THRESHOLD;
  if (!simOk) return false;
  // 분야 태그가 양쪽 다 있으면 겹치는 것만 묶는다 (app.js:3558)
  const ts = a.tags, tj = b.tags;
  if (Array.isArray(ts) && ts.length && Array.isArray(tj) && tj.length) {
    return ts.some((t) => tj.includes(t));
  }
  return true;
}

function pubMs(x: GroupableNews): number {
  const t = Date.parse(x.published_at || x.created_at || '');
  return Number.isNaN(t) ? Number.MAX_SAFE_INTEGER : t;
}

/** 같은 사건끼리 묶어 [대표 기사 + 관련 보도 수] 목록으로. 입력 순서를 그대로 따른다.
 *
 *  비교 상대는 **그룹 대표(첫 원소) 하나뿐**이다 — 그룹 안 아무하고나 비교하면 A~B, B~C로
 *  한 다리 건너 계속 이어붙어(연쇄 병합) 무관한 기사가 한 덩어리가 된다(app.js:3552 실측: 91건).
 *  app.js가 두는 '같은 날짜' 제한은 여기선 두지 않는다 — 발송 구간은 길어야 몇 시간이라
 *  자정을 걸친 구간에서 오히려 같은 사건을 갈라놓는다.
 */
export function groupBySameEvent<T extends GroupableNews>(items: T[]): Array<NewsGroup<T>> {
  const used = new Array(items.length).fill(false);
  const out: Array<NewsGroup<T>> = [];
  for (let i = 0; i < items.length; i++) {
    if (used[i]) continue;
    used[i] = true;
    const members: T[] = [items[i]];
    for (let j = i + 1; j < items.length; j++) {
      if (used[j]) continue;
      if (sameEvent(items[i], items[j])) { used[j] = true; members.push(items[j]); }
    }
    // 화면 대표는 가장 먼저 보도한 기사 — 비교 기준(members[0])과는 별개다.
    const head = members.reduce((a, b) => (pubMs(b) < pubMs(a) ? b : a), members[0]);
    out.push({ head, related: members.length - 1 });
  }
  return out;
}
