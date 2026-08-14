// ============================================================================
//  공용 : 국회 회의록 발언 검색 (국회회의록시스템 실시간 검색)
//
//  왜 실시간인가 — DB(assembly_speeches)는 22대·판정 통과분·요지만 담고 있어
//  "2019년 김성수 의원이 무선국 관련해 뭐라고 했나" 같은 질의에 답할 수 없다.
//  이 모듈은 국회 검색 API를 그대로 호출해 **20대(2016)~현재**를 훑는다. 축적 데이터 무관.
//
//  **검색 범위는 과방위(20대 전반기 미래창조과학방송통신위원회 포함)의 상임위·국정감사 회의록뿐이다**
//  (운영자 지시 2026-08-14). 본회의·타 상임위·예결위는 넣지 않는다 — 전파·통신 정책 문맥이 아니고,
//  같은 이름의 다른 의원 발언이 섞여 오답을 만든다.
//
//  텔레그램(/assem)과 대시보드(assembly-search 함수)가 **이 파일 하나**를 공유한다.
//  두 벌로 갈라지면 같은 질의가 경로에 따라 다른 결과를 낸다(배경역사 #88·#92의 재발 방지).
//
//  실측 주의사항 (2026-08-14):
//   - collection 은 'record2'(상임위)/'record5'(국정감사). 'record'로 보내면 HTTP 200 + 빈 {} 가
//     돌아와 '결과 없음'과 구분되지 않는다.
//   - CMIT_CD 는 대(代)마다 재배정된다. 20대 전반기 명칭 미래창조과학방송통신위원회(RN)를 빼면
//     2016~2018년이 통째로 빠진다.
//   - S_TH/E_TH 는 **검색폼 대수코드**(22=제20대, 24=제22대)로 열린국회 API의 DAE_NUM 과 다른 체계다.
//   - 본문 원문 검색이라 형태소 분석이 없다 — 회의록에 나온 낱말 그대로여야 잡힌다.
// ============================================================================

export const ASSEM_SEARCH_URL = 'https://record.assembly.go.kr/assembly/mnts/search/search.do';
export const ASSEM_VIEWER_URL = 'https://record.assembly.go.kr/assembly/viewer/minutes/xml.do?id=';
const ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages';

// 과방위 위원회 코드 — 상임위(class 2) + 국정감사(class 5), 20~22대. 23대 개원 시 두 줄 추가.
export const ASSEM_CMIT_CD = [
  '20-2-AB', '20-2-RN', '21-2-AF', '22-2-AF',           // 상임위 (20대 과방위·미방위 병기)
  '20-5-AB-0', '20-5-RN-0', '21-5-AK-0', '22-5-AG-0',   // 국정감사
].join(',');

export const ASSEM_S_TH = '22';   // 제20대
export const ASSEM_E_TH = '24';   // 제22대
const ASSEM_PAGE_SIZE = 10;       // 검색 응답 페이지 크기(서버 고정)
const ASSEM_MAX_PAGES = 12;       // '더 보기' 상한 — 120건까지 넘겨본다
const COLL_LABEL: Record<string, string> = { record2: '상임위', record5: '국정감사' };

export type AssemKind = '상임위' | '국정감사';

export type AssemQuery = {
  speaker: string;         // 의원명. '' 이면 발언자 무관
  query: string;           // 회의록 본문에서 찾을 낱말
  year?: number;           // 특정 연도로 좁힐 때
  dae?: number;            // 대수(20·21·22). "22대 국회에서…" 같은 표현을 범위 지정으로 받는다
  daeOut?: number;         // 지원 범위(20~22) 밖 대수. 검색어에서 걷어내되 "범위 밖"이라고 알리기 위해 남긴다
  kinds?: AssemKind[];     // 미지정이면 상임위+국정감사 모두
};

// 대수 → 검색폼 대수코드. 20대=22 … 22대=24 (Open API 의 DAE_NUM 과 다른 체계).
const DAE_TO_TH: Record<number, string> = { 20: '22', 21: '23', 22: '24' };

export type AssemHit = {
  date: string;        // 'YYYY.MM.DD'
  kind: string;        // '상임위' | '국정감사'
  committee: string;   // 위원회명(소위 포함)
  speaker: string;     // '김성수 위원'
  snippet: string;     // <!HS>…<!HE> 강조 마커가 남아 있는 원문 스니펫
  url: string;         // 회의록 뷰어 링크
  auditOrgs: string;   // 국감이면 피감기관
  context?: AssemBlock[];  // attachContext() 로 붙인 발언 전문 + 앞뒤 블록(정부측 답변 포함)
};

export type AssemResult = { total: number; hits: AssemHit[]; parsed: AssemQuery; retried?: boolean };

type Row = {
  MNTS_ID?: string; RDATE?: string; CMIT_NM?: string; SPK_NM?: string;
  SPK_CNTS?: string; AUDIT_NM?: string;
};

// ── 자연어 질의 파싱 ────────────────────────────────────────────
// "2019년 국정감사에서 김성수 의원이 무선국 관련해서 발언한 내용을 찾아줘"
//   → { speaker:'김성수', query:'무선국', year:2019, kinds:['국정감사'] }
// 규칙 파서를 **먼저** 돌리고, 핵심어를 못 뽑았을 때만 Haiku 를 부른다(대부분의 질의는 무료로 끝난다).

const ASSEM_STOPWORDS = [
  '관련해서', '관련해', '관련된', '관련', '대해서', '대해', '대한', '관하여', '관한', '관해',
  '발언한', '발언했던', '발언', '발언들', '내용을', '내용', '얘기', '얘기한', '이야기', '이야기한',
  '말한', '말씀', '하신', '언급한', '언급', '입장', '질의한', '질의', '답변한', '답변',
  '찾아줘', '찾아', '알려줘', '알려', '보여줘', '보여', '검색해줘', '검색', '조회',
  '무엇', '뭐라고', '어떤', '무슨', '해줘', '주세요', '좀', '그', '이', '저', '모두', '전부',
  '회의록', '회의', '국회', '과방위', '미방위', '위원회', '위원장', '소위', '논의', '나온', '있던',
  '에서', '에', '의', '을', '를', '은', '는', '이',
];
// 서술어 꼬리("했는지", "있었나", "말했나"…)는 어미로 걸러낸다 — 불용어 목록으로는 끝이 없다.
const ASSEM_PREDICATE_RE = /(했는지|하는지|한지|했나|하나요|했나요|있었나|있나|있는지|였는지|이었나|됐는지|되는지|드립니다|합니다|했어요|한다)$/;
// '발언된/언급한/논의된' 같은 활용형. 목록으로 하나씩 채우면 반드시 빠진다 —
// 실측: '발언한'은 있는데 '발언된'이 없어 "…발언된 내용을 찾아줘"가 통째로 0건이 됐다.
const ASSEM_VERBFORM_RE = /^(발언|언급|논의|질의|답변|제기|지적|말|얘기|이야기|말씀)(한|된|하신|했던|되었던|드린)$/;
// '관련' 계열은 활용형이 많아(관련되어·관련하여·관련한…) 목록으로 못 따라간다 — 어간으로 자른다.
const ASSEM_RELATED_RE = /^관련(되어|되었던|된|하여|한|해서|해|있는|있던)?$/;
// '의원'·'위원' 앞 낱말을 성명으로 볼 때 사람 이름일 수 없는 말들. 이게 없으면
// "…에 대해 의원들이"의 '대해'가 의원명이 돼 결과가 0건이 된다(2026-08-14 검증에서 확인).
// 인칭어 활용형("의원들이"·"위원님들이"·"위원장이"). 목록·한 글자 조사 절단으로는 못 잡는다 —
// 조사 목록에 '이'를 그냥 넣으면 '어린이'→'어린' 같은 새 사고가 나므로 **전용 패턴**으로 건다.
// 실측(2026-08-14 재검증): "의원님들이 언급한 전파 정책" → 검색어가 '의원님들이'가 돼 무관한 409건.
const ASSEM_PERSONWORD_RE = /^(국회)?(의원|위원|위원장|의장|장관|차관|참고인|증인)(님들|님|들)?(이|은|는|께서|도|과|와)?$/;
const ASSEM_NOT_NAME = new Set([
  '대해', '대한', '관해', '관한', '어떤', '무슨', '소속', '해당', '우리', '전체', '모든',
  '방송통신', '정보통신', '과학기술', '여야', '일부', '다른', '해당', '각',
  // "국회의원이 지적한…"의 '국회'가 의원명이 되던 것(2026-08-14 재검증 실측)
  '국회', '상임', '소속당', '야당', '여당',
]);

/** 규칙 기반 파싱. query 를 못 뽑으면 query='' 로 돌려준다(호출자가 Haiku 로 넘김). */
export function parseAssemQueryRule(text: string): AssemQuery {
  let rest = ' ' + (text || '').trim() + ' ';

  // ① 의원명 — "김성수 의원이/위원은" 형태만 인정.
  //   '위원회'·'의원들'을 걸러내지 않으면 "…에 대해 의원들이"의 '대해', "…방송통신위원회에서"의
  //   '방송통신'이 의원명이 돼 검색이 통째로 0건이 된다(2026-08-14 검증에서 실측).
  let speaker = '';
  const mName = rest.match(/([가-힣]{2,4})\s*(?:의원|위원)(?!회|들|님들)/);
  if (mName && !ASSEM_NOT_NAME.has(mName[1])) {
    speaker = mName[1];
    rest = rest.replace(mName[0], ' ');
  }

  // ② 연도 — '년'을 반드시 요구한다. 안 그러면 "1900MHz 대역"의 1900이 연도로 잡힌다(실측).
  let year: number | undefined;
  const mYear = rest.match(/(19|20)(\d{2})\s*년/);
  if (mYear) { year = Number(mYear[1] + mYear[2]); rest = rest.replace(mYear[0], ' '); }

  // ②' 대수 — "22대 국회에서 …" 는 **범위 지정**이지 검색어가 아니다.
  //    이걸 안 걷어내면 '22대'가 검색어로 나가 엉뚱한 193건이 잡힌다(2026-08-14 운영자 지적).
  let dae: number | undefined;
  let daeOut: number | undefined;
  const mDae = rest.match(/제?\s*(\d{1,2})\s*대(?:\s*국회)?/);
  if (mDae) {
    const n = Number(mDae[1]);
    // 범위 밖(19대 이하)이어도 **검색어로 남기지 않는다.** 종전엔 '제19대'가 그대로 나가
    // 무관한 192건이 잡혔다 — 대수 표기는 어느 값이든 범위 지정어이지 주제어가 아니다.
    if (DAE_TO_TH[n]) dae = n; else daeOut = n;
    rest = rest.replace(mDae[0], ' ');
  }

  // ③ 회의 구분
  const kinds: AssemKind[] = [];
  if (/국정감사|국감/.test(rest)) kinds.push('국정감사');
  if (/상임위|전체회의|법안소위|소위원회/.test(rest)) kinds.push('상임위');
  rest = rest.replace(/국정감사|국감|상임위원회|상임위|전체회의|법안소위|소위원회/g, ' ');

  // ④ 남은 어절에서 조사·불용어를 걷어내고 핵심어만
  const rawWords = rest.split(/[\s,·]+/).map((w) => w.replace(/[^가-힣A-Za-z0-9]/g, '')).filter(Boolean);
  const words = rawWords
    // 조사 절단은 보수적으로. 한 글자 조사를 무르게 떼면 명사 끝을 먹는다 —
    // 실측: '도매대가'→'도매대'(0건, 실제 92건), '평가'→'평'(소멸), '국가'→'국'.
    // ① 여러 글자 조사는 안전하게 절단 ② 한 글자는 '가·이·도·만·와·과'를 빼고,
    // 남는 어간이 2자 이상일 때만(즉 3자 이상 낱말) 절단한다.
    .map((w) => w.replace(/(에서는|에서도|에게서|에서|에게|으로|로써|로서|부터|까지|에는|에도|이나|라는)$/, ''))
    .map((w) => (w.length >= 3 ? w.replace(/(을|를|은|는|의|에)$/, '') : w))
    .filter((w) => w.length >= 2 && !ASSEM_STOPWORDS.includes(w)
      && !ASSEM_PREDICATE_RE.test(w) && !ASSEM_VERBFORM_RE.test(w) && !ASSEM_RELATED_RE.test(w)
      && !ASSEM_PERSONWORD_RE.test(w)
      // 위원회 이름은 검색어가 아니라 범위 지정어다. 통째로 검색어가 되면
      // "…위원회에서 5G 관련 발언"이 5G 를 버리고 위원회명 1,406건을 내놓는다(실측).
      && !/위원회$|소위원회$/.test(w));
  // 첫 낱말을 발언자로 승격하는 것은 **군더더기가 하나도 없는 두 낱말 입력**("김성수 무선국")뿐이다.
  // 조사·서술어가 붙은 문장이면 자연어 질의라는 뜻이고, 그때 승격하면
  // "주파수 재할당에 대해 어떤 얘기가 있었나"의 '주파수'가 의원명이 돼 0건이 된다(실측).
  if (!speaker && rawWords.length === 2 && words.length === 2 && /^[가-힣]{2,4}$/.test(words[0])) {
    speaker = words.shift() as string;
  }
  // 원문 문자열 AND 검색이라 낱말이 늘수록 0건 위험이 커진다 — 최대 2개까지만.
  return { speaker, query: words.slice(0, 2).join(' '), year, dae, daeOut,
           kinds: kinds.length ? kinds : undefined };
}

/** Haiku 보조 파싱 — 규칙 파서가 핵심어를 못 뽑았을 때만. 실패 시 규칙 결과를 그대로 쓴다(fail-open). */
export async function parseAssemQuery(text: string, apiKey?: string): Promise<AssemQuery> {
  const rule = parseAssemQueryRule(text);
  const key = (apiKey || '').trim();
  // 빈 입력에 Haiku 를 태우면 프롬프트의 스키마 예시("의원 성명", "핵심 낱말")를 그대로 돌려줘
  // 화면 조건 칩에 그 문구가 뜬다(실측). 애초에 부를 이유가 없다.
  if (rule.query || !key || !text.trim()) return rule;
  try {
    const res = await fetch(ANTHROPIC_URL, {
      method: 'POST',
      headers: {
        'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json',
      },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 200,
        messages: [{
          role: 'user',
          content: '아래 문장에서 국회 회의록 검색 조건을 뽑아 JSON만 출력하라.\n'
            + '{"speaker":"의원 성명(없으면 빈 문자열)","query":"회의록 본문에서 찾을 핵심 낱말 1~2개",'
            + '"year":연도숫자 또는 null,"kind":"국정감사"|"상임위"|null}\n'
            + '형태소 분석이 아니라 원문 문자열 검색이므로 query 는 회의록에 그대로 나올 법한 명사로 적어라.\n\n'
            + text,
        }],
      }),
      signal: AbortSignal.timeout(15_000),
    });
    const j = await res.json();
    let txt = '';
    for (const b of (j?.content || [])) if (b?.type === 'text') { txt = b.text || ''; break; }
    const m = txt.match(/\{[\s\S]*\}/);
    if (!m) return rule;
    const p = JSON.parse(m[0]) as { speaker?: string; query?: string; year?: number; kind?: string };
    return {
      speaker: (p.speaker || rule.speaker || '').trim(),
      query: (p.query || '').trim(),
      year: p.year || rule.year,
      // 대수는 Haiku에게 묻지 않는다(규칙 파서가 확실하다). 여기서 안 실어 주면 "22대 국회에서 어떤
      // 얘기가 있었나"처럼 Haiku로 넘어간 질의에서 대수 제한이 조용히 사라진다.
      dae: rule.dae,
      daeOut: rule.daeOut,
      kinds: p.kind === '국정감사' ? ['국정감사'] : p.kind === '상임위' ? ['상임위'] : rule.kinds,
    };
  } catch (_e) {
    return rule;
  }
}

// ── 검색 ────────────────────────────────────────────────────────

/**
 * 과방위(20대~현재) 상임위·국정감사 회의록 본문에서 발언을 찾는다.
 * @param limit 반환할 최대 발언 수(전체 건수 total 은 그대로 돌려준다).
 */
export async function searchAssemblySpeeches(
  q: AssemQuery, limit = 5, timeoutMs = 20_000, offset = 0,
): Promise<AssemResult> {
  const wantAudit = !q.kinds || q.kinds.includes('국정감사');
  const wantStanding = !q.kinds || q.kinds.includes('상임위');
  const colls: string[] = [];
  if (wantStanding) colls.push('record2');
  if (wantAudit) colls.push('record5');

  const mkBody = (page: number) => new URLSearchParams({
    query: q.query, searchField: 'SPK_CNTS', SPK_NM: q.speaker || '', SPKSAME: 'N', BILL_NO: '',
    sort: 'DATE/DESC',
    startDate: q.year ? `${q.year}-01-01` : '',
    endDate: q.year ? `${q.year}-12-31` : '',
    collection: colls.join(','),
    CLASS_CD: colls.map((c) => c.replace('record', '')).join(','),
    CMIT_CD: ASSEM_CMIT_CD,
    // 대수를 지정했으면 그 대(代)로 좁힌다. 안 하면 20~22대 전체가 대상.
    S_TH: q.dae ? DAE_TO_TH[q.dae] : ASSEM_S_TH,
    E_TH: q.dae ? DAE_TO_TH[q.dae] : ASSEM_E_TH,
    S_SESS: '345', E_SESS: '9999',
    startCount: String(page),
  });
  const call = async (page: number) => {
    const res = await fetch(ASSEM_SEARCH_URL, {
      method: 'POST', body: mkBody(page),
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          + '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Referer': 'https://record.assembly.go.kr/assembly/mnts/minutes/search.do',
      },
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!res.ok) throw new Error('국회 검색 응답 ' + res.status);
    const txt = await res.text();
    return (txt.trim() ? JSON.parse(txt) : {}) as
      Record<string, { totalCount?: number; resultList?: Row[] }>;
  };

  // '더 보기'를 위한 페이징. 서버 페이지는 컬렉션마다 10건 고정이라, offset+limit 을 덮을 만큼
  // 앞 페이지를 다 받아 와서 **날짜순으로 합친 뒤** 잘라낸다(컬렉션별로 따로 페이징하면
  // 상임위·국감이 뒤섞인 전체 시간순이 깨진다).
  const need = Math.max(1, Math.ceil((offset + limit) / ASSEM_PAGE_SIZE));
  let total = 0;
  const raw: { coll: string; row: Row }[] = [];
  const seen = new Set<string>();
  for (let page = 1; page <= Math.min(need, ASSEM_MAX_PAGES); page++) {
    const json = await call(page);
    let got = 0;
    for (const coll of colls) {
      const rec = json[coll];
      if (!rec) continue;
      if (page === 1) total += rec.totalCount || 0;
      for (const row of rec.resultList || []) {
        const key = `${coll}:${row.MNTS_ID}:${row.SPK_CNTS?.slice(0, 40)}`;
        if (seen.has(key)) continue;
        seen.add(key);
        raw.push({ coll, row });
        got++;
      }
    }
    if (!got) break;
  }
  raw.sort((a, b) => String(b.row.RDATE || '').localeCompare(String(a.row.RDATE || '')));

  const hits: AssemHit[] = raw.slice(offset, offset + limit).map(({ coll, row }) => {
    const d = String(row.RDATE || '');
    return {
      date: d.length === 8 ? `${d.slice(0, 4)}.${d.slice(4, 6)}.${d.slice(6)}` : d,
      kind: COLL_LABEL[coll] || '',
      committee: (row.CMIT_NM || '').trim(),
      speaker: (row.SPK_NM || '').trim(),
      snippet: (row.SPK_CNTS || '').replace(/\s+/g, ' ').trim(),
      url: row.MNTS_ID ? `${ASSEM_VIEWER_URL}${row.MNTS_ID}&type=view` : '',
      auditOrgs: (row.AUDIT_NM || '').trim(),
    };
  });
  return { total, hits, parsed: q };
}

// ── 발언 전문 + 앞뒤 문맥 (뷰어 원문) ──────────────────────────
// 검색 스니펫은 206자에서 잘리고, 발언자 필터 때문에 **정부측 답변이 빠진다**.
// "무선국 면허세는 행안부와 협의해 낮추겠다" 같은 그날의 실질 성과가 차관 발언이라 안 잡히는 식이다.
// 그래서 적중 발언의 뷰어 원문을 한 번 더 받아 **그 발언 전문 + 앞뒤 블록(답변 포함)**을 붙인다.
// 국회 사이트 fetch 뿐이라 AI 비용은 0. 다만 국감 회의록 HTML이 1.8MB라 상위 몇 건에만 적용한다.

export type AssemBlock = { seq: number; name: string; pos: string; text: string; isTarget: boolean };

const ENTITIES: Record<string, string> = {
  '&nbsp;': ' ', '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'",
};

function stripHtml(s: string): string {
  return s.replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '')
    .replace(/&nbsp;|&amp;|&lt;|&gt;|&quot;|&#39;/g, (m) => ENTITIES[m] || m)
    .replace(/[ \t]+/g, ' ').trim();
}

const norm = (s: string) => (s || '').replace(/\s+/g, '');

/**
 * 회의록 뷰어에서 발언 블록 전량을 뽑는다.
 * 마크업(2026-08-14 실측): <div id="spk_1779" class="… speaker …" data-name="김성수" data-pos="위원">
 *                          … <div class="talk"><div class="txt"><span class="spk_sub" …>본문</span>…
 * DOMParser 가 Edge 런타임 기본 제공이 아니라 외부 의존 없이 정규식으로 자른다.
 * 블록 경계는 다음 `<div id="spk_` 이므로 talk 영역이 다음 발언으로 새지 않는다.
 */
export async function fetchViewerBlocks(mntsId: string, timeoutMs = 25_000): Promise<AssemBlock[]> {
  const res = await fetch(`${ASSEM_VIEWER_URL}${mntsId}&type=view`, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        + '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
      'Accept-Language': 'ko-KR,ko;q=0.9',
    },
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) throw new Error('회의록 뷰어 응답 ' + res.status);
  const html = await res.text();
  const blocks: AssemBlock[] = [];
  for (const part of html.split(/<div id="spk_(?=\d)/).slice(1)) {
    const head = part.slice(0, 400);
    if (!/class="[^"]*speaker/.test(head)) continue;
    const name = (head.match(/data-name="([^"]*)"/) || [])[1] || '';
    const pos = (head.match(/data-pos="([^"]*)"/) || [])[1] || '';
    const talkAt = part.indexOf('<div class="talk">');
    if (!name || talkAt < 0) continue;
    const texts = [...part.slice(talkAt).matchAll(/<span class="spk_sub"[^>]*>([\s\S]*?)<\/span>/g)]
      .map((m) => stripHtml(m[1])).filter(Boolean);
    const text = texts.join('\n').trim();
    if (text) {
      blocks.push({ seq: Number((part.match(/^(\d+)"/) || [])[1] || 0), name, pos, text, isTarget: false });
    }
  }
  return blocks;
}

/**
 * 스니펫에 해당하는 블록을 찾아 앞뒤를 함께 돌려준다.
 * 스니펫은 **블록 첫머리가 아닐 수 있어**(실측: 검색이 매칭 구간부터 잘라 준다) 접두 비교로는 못 찾는다.
 * 공백을 지운 뒤 부분 문자열로 대조하고, 실패하면 '같은 발언자 + 검색어' 로 폴백한다.
 */
export function pickContext(
  blocks: AssemBlock[], speaker: string, snippet: string, keyword: string,
  before = 1, after = 3,
): AssemBlock[] {
  // 스니펫은 매칭 구간 여러 개를 '...'로 이어 붙인 형태일 수 있다. 그때는 앞 30자가 원문에
  // 통째로 존재하지 않아 대조가 실패한다 — 조각으로 쪼개 가장 긴 조각으로 찾는다(실측 10건 중 1건).
  const plain = (snippet || '').replace(/<!H[SE]>/g, '');
  const fragments = plain.split(/\s*(?:\.{3}|…)\s*/).map((s) => norm(s)).filter((s) => s.length >= 10)
    .sort((a, b) => b.length - a.length);
  const needles = [norm(plain).slice(0, 30), ...fragments.map((f) => f.slice(0, 30))]
    .filter((s) => s.length >= 10);
  const nameHit = (b: AssemBlock) => !speaker || b.name.includes(speaker) || speaker.includes(b.name);
  let idx = -1;
  for (const bare of needles) {
    idx = blocks.findIndex((b) => nameHit(b) && norm(b.text).includes(bare));
    if (idx >= 0) break;
  }
  if (idx < 0 && keyword) {
    const kw = keyword.split(/\s+/)[0];
    idx = blocks.findIndex((b) => nameHit(b) && b.text.includes(kw));
  }
  if (idx < 0) return [];
  return blocks.slice(Math.max(0, idx - before), Math.min(blocks.length, idx + after + 1))
    .map((b, i) => ({ ...b, isTarget: Math.max(0, idx - before) + i === idx }));
}

/** 상위 hit 에 발언 전문·앞뒤 문맥을 붙인다. 실패해도 검색 결과는 그대로 살린다(fail-open). */
export async function attachContext(
  result: AssemResult, count = 1, before = 1, after = 3, maxChars = 1200,
): Promise<AssemResult> {
  for (const h of result.hits.slice(0, count)) {
    const id = (h.url.match(/[?&]id=(\d+)/) || [])[1];
    if (!id) continue;
    try {
      const blocks = await fetchViewerBlocks(id);
      const ctx = pickContext(blocks, h.speaker.replace(/\s*(위원장|위원|의원)\s*$/, ''),
                              h.snippet, result.parsed.query, before, after);
      if (ctx.length) {
        h.context = ctx.map((b) => ({
          ...b, text: b.text.length > maxChars ? b.text.slice(0, maxChars) + '…' : b.text,
        }));
      }
    } catch (e) {
      console.error('[문맥 확보 실패(무시)]', String((e as Error)?.message ?? e).slice(0, 80));
    }
  }
  return result;
}

/**
 * 0건이면 **다른 해석으로 자동 재시도**한다.
 *
 * 한국어 질의를 규칙으로 완벽히 가르는 건 불가능하고, 규칙을 아무리 다듬어도 예외가 남는다.
 * 그런데 이 기능에서 가장 나쁜 실패는 오답이 아니라 **0건**이다 — 사용자는 그것을
 * "국회에 그런 발언이 없다"로 읽지 "파서가 헛짚었다"로 읽지 않는다(2026-08-14 검증에서
 * 실패 16건 중 최소 6건이 이 형태였다: '주파수 재할당'→0건, 실제 32건).
 * 그래서 규칙을 조이는 대신 **틀렸을 때 스스로 되돌아가게** 만든다. 국회 검색은 무료라
 * 재시도 비용은 왕복 0.3~1초뿐이다.
 *
 * 성공한 해석이 `parsed`로 돌아가므로 화면의 조건 칩은 **실제로 쓰인 해석**을 보여준다.
 */
export async function searchAssemblyWithFallback(
  q: AssemQuery, limit = 5, timeoutMs = 20_000, offset = 0,
): Promise<AssemResult> {
  // 이어보기(offset>0)는 이미 해석이 확정된 상태라 재시도 없이 그대로 페이지만 넘긴다.
  if (offset > 0) return searchAssemblySpeeches(q, limit, timeoutMs, offset);
  const parts = (q.query || '').split(/\s+/).filter(Boolean);
  // 낱말 하나만 남길 때는 **첫 낱말이 아니라 가장 긴 낱말**을 고른다.
  // 첫 낱말이 노이즈면("22대 무선국" → '22대') 재시도가 오히려 엉뚱한 결과를 부풀린다(실측 193건).
  const longest = parts.slice().sort((a, b) => b.length - a.length)[0] || '';
  const attempts: AssemQuery[] = [q];
  // ① 의원명으로 승격한 낱말이 사실 주제어였던 경우 — '주파수 재할당' → speaker='주파수'
  if (q.speaker && q.query) attempts.push({ ...q, speaker: '', query: `${q.speaker} ${q.query}` });
  // ② 두 낱말 AND 가 너무 좁은 경우 — 변별력이 큰 낱말 하나만 남긴다
  if (longest && longest !== q.query) attempts.push({ ...q, query: longest });
  // ③ 연도·회의구분 제약을 푼다 (연도 오인식·구분 오판 복구)
  if (q.year || q.kinds?.length) attempts.push({ ...q, year: undefined, kinds: undefined });

  let last: AssemResult | null = null;
  for (let i = 0; i < Math.min(attempts.length, 4); i++) {
    const r = await searchAssemblySpeeches(attempts[i], limit, timeoutMs);
    // 재시도로 해석이 바뀌었으면 그 사실을 호출자에게 알린다. 재시도는 0건을 피하려고
    // 조건을 푸는 동작이라 **그럴듯한 대량 오답**을 낼 수 있다("탄소중립 시멘트" → '탄소중립' 224건).
    // 건수만 보여주면 오히려 신뢰를 주므로 "다시 찾았다"는 표시가 반드시 함께 가야 한다.
    if (r.total > 0) return i > 0 ? { ...r, retried: true } : r;
    last = r;
  }
  return last as AssemResult;
}

/** 위원회명 축약 — 목록에서 한 줄에 들어가게. */
export function shortCommittee(name: string): string {
  return (name || '')
    .replace('과학기술정보방송통신위원회', '과방위')
    .replace('미래창조과학방송통신위원회', '미방위');
}
