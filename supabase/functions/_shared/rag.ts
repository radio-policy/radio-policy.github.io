// ============================================================================
//  공용: AI 자문 RAG 파이프라인 (app.js 자문 경로의 서버판 — telegram-webhook에서 사용)
//
//  대시보드 app.js의 3중 하이브리드(키워드확장+ilike / trgm / 시맨틱)와 kb 요약 검색을
//  핵심 경로만 TS로 이식했다. v1 단순화로 제외한 것(대시보드에만 있음):
//  별표(annex) 추적 / 시행예정(pending) / custom_knowledge / 뉴스 컨텍스트 / law_graph·lawmap.
//  임계값·가중치는 app.js와 동일하게 유지한다 (융합은 RRF — 종전 #23 합산식에서 교체.
//  RRF·행위 표제어 가중·법령 위계 동점 규칙을 고치면 app.js searchKeywords/searchLawArticles도 같이).
//
//  키: ANTHROPIC_API_KEY·VOYAGE_API_KEY는 Edge Function Secrets에서만 읽는다.
//  app_config(claude_key, anon 노출)를 서버에서 재사용하지 말 것 — 지침 do-not.
// ============================================================================

import type { SupabaseClient } from 'jsr:@supabase/supabase-js@2';

const ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages';
const VOYAGE_URL = 'https://api.voyageai.com/v1/embeddings';

// env는 반드시 trim — 콘솔 붙여넣기로 들어간 줄바꿈이 API 키에 남으면 헤더가 깨진다
const env = (k: string) => (Deno.env.get(k) || '').trim();

// ── app.js extractKeywords 이식 (한국어 조사·불용어 제거, 법령 키워드 우선) ──
function extractKeywords(text: string): string[] {
  const stopwords = ['이','가','은','는','을','를','의','에','에서','으로','로','과','와','도',
    '만','그','이것','저것','그것','있다','없다','하다','되다','이다','어떻게','어떤',
    '무엇','언제','어디','왜','누가','대해','관해','통해','위해','따라','대한','관한',
    '통한','위한','있는','없는','하는','되는','인','이란','이라는','라는','라고',
    '이고','이며','하고','이나','또는','그리고','하지만','그러나','따라서'];
  const josa = /(에서는|으로는|에서의|이라는|에서도|에서|에는|으로|로는|보다|부터|까지|처럼|마다|조차|밖에|은|는|이|가|을|를|의|에|와|과|도|만)$/;
  const words = text.split(/[\s,.·()[\]「」『』<>:;!?]+/)
    .map((w) => w.replace(/[^가-힣a-zA-Z0-9.]/g, '').trim())
    .map((w) => { const s = w.replace(josa, ''); return s.length >= 2 ? s : w; })
    .filter((w) => w.length >= 2 && !stopwords.includes(w));
  const pri = words.filter((w) =>
    /제\d+조|주파수|할당|재할당|전자파|ITU|5G|6G|EMC|SAR|고시|시행령|시행규칙|적합성|기술기준|무선국|면허|허가|신청|승인|폐업|폐지|이용기간/.test(w));
  const all = pri.concat(words.filter((w) => !pri.includes(w)));
  return all.filter((v, i, a) => a.indexOf(v) === i).slice(0, 5);
}

// ── Haiku 쿼리 확장 (실패 시 빈 배열 → 기본 키워드만) ──
async function expandQueryKeywords(apiKey: string, query: string): Promise<string[]> {
  try {
    const res = await fetch(ANTHROPIC_URL, {
      method: 'POST',
      headers: { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 200,
        system: '당신은 한국 전파·통신 법령 검색 전문가입니다. 사용자 질문을 법령·고시 원문에서 실제 쓰이는 공식 용어로 확장합니다.',
        messages: [{ role: 'user', content: '다음 질문을 법령·고시 문서 검색용 키워드로 확장해줘. 질문 표현과 다른 동의어, 법령 공식 용어, 관련 조문 주제어 위주로 6~8개. 쉼표로만 구분해 한 줄로 출력하고 설명은 금지:\n\n' + query }],
      }),
    });
    if (!res.ok) return [];
    const data = await res.json();
    const text = (data.content?.find((b: { type: string }) => b.type === 'text')?.text) || '';
    return text.split(',')
      .map((w: string) => w.trim().replace(/^["'\d.)\s]+|["'\s]+$/g, ''))
      .filter((w: string) => w.length >= 2 && w.length <= 25)
      .slice(0, 8);
  } catch (e) { console.warn('쿼리 확장 실패(기본 키워드로 진행):', e); return []; }
}

// ── Voyage 임베딩 (voyage-embed 함수와 동일 호출을 인라인 — 같은 프로젝트 Secret 사용) ──
async function getQueryEmbedding(query: string, model = 'voyage-4-lite'): Promise<number[] | null> {
  const key = env('VOYAGE_API_KEY');
  if (!key) return null;
  try {
    const res = await fetch(VOYAGE_URL, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${key}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ model, input: [query], input_type: 'query' }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.data?.[0]?.embedding || null;
  } catch (e) { console.warn('임베딩 실패(폴백):', e); return null; }
}

interface Chunk {
  id: number; doc_name: string; doc_category?: string; content: string;
  notice_no?: string; article_no?: string; effective_date?: string;
  trgm_score?: number; similarity?: number;
  _score?: number; _trgm_score?: number; _semantic_score?: number; _hybrid_score?: number;
}

// 문서당 청크 상한 (doc_category별 차등 — app.js searchKeywords와 동일 유지, 한쪽만 고치면 봇/대시보드 답이 갈라진다):
// '추가지식' = 운영자가 일부러 넣은 논문·근거메모 → 8청크까지 깊게 참고 (일괄 3에서는 표지·방법론만
// 잡히고 핵심 결론이 컷 밖으로 밀리는 실측). 그 외(보도자료·뉴스·회의록 등) = 3 (한 문서 독식 방지).
const PERDOC_LIMIT: Record<string, number> = { '추가지식': 8, 'default': 3 };
// 전체 상위 컷 12→15: 추가지식 1편이 8을 차지해도 다른 문서 몫이 7 남게 (종전 최악 9에서 소폭 감소에 그침).
const TOTAL_CHUNK_CUT = 15;

// ── 3중 하이브리드 조문 검색 (app.js searchKeywords 이식, 상위 15개) ──
async function searchChunks(sb: SupabaseClient, apiKey: string, query: string): Promise<Chunk[]> {
  const baseKeywords = extractKeywords(query);
  const expanded = await expandQueryKeywords(apiKey, query);
  // 기본 → 법령 표제어(LAW_SYNONYMS) → LLM 확장 순 (app.js searchKeywords와 동일 유지)
  const keywords: string[] = [];
  const seenKw = new Set<string>();
  for (const w of baseKeywords.concat(lawSynonymKeywords(query)).concat(expanded)) {
    const norm = w.replace(/\s+/g, '').toLowerCase();
    if (norm.length >= 2 && !seenKw.has(norm)) { seenKw.add(norm); keywords.push(w); }
  }
  if (!keywords.length) return [];

  // only_current 명시 — 기본값에 기대면 status 필터 없는 오버로드로 조용히 해석될 수 있음(배경역사 #31 후속)
  const trgmP = sb.rpc('search_chunks_trgm', { query_text: query, match_threshold: 0.12, match_count: 8, only_current: true })
    .then((r) => r.data || []).catch(() => []);
  const semP = getQueryEmbedding(query).then((emb) => {
    if (!emb) return [];
    return sb.rpc('match_chunks_semantic', { query_embedding: emb, match_threshold: 0.45, match_count: 8, only_current: true })
      .then((r) => r.data || []).catch(() => []);
  });
  const kwP = Promise.all(keywords.slice(0, 10).map((kw) =>
    sb.from('document_chunks')
      .select('id, doc_name, doc_category, chunk_index, content, notice_no, article_no, effective_date')
      .eq('is_approved', true).eq('status', 'current')
      .ilike('content', '%' + kw + '%').limit(4)
      .then((r) => r.data || []).catch(() => [])));

  const seen = new Set<number>();
  const results: Chunk[] = [];
  for (const rows of await kwP) {
    for (const row of rows as Chunk[]) {
      if (!seen.has(row.id)) { seen.add(row.id); results.push(row); }
    }
  }
  const merge = (rows: Chunk[], field: '_trgm_score' | '_semantic_score', src: 'trgm_score' | 'similarity') => {
    for (const row of rows) {
      const val = (row[src] as number) || 0;
      const ex = results.find((r) => r.id === row.id);
      if (ex) {
        ex[field] = val;
        if (!ex.article_no && row.article_no) ex.article_no = row.article_no;
        if (!ex.notice_no && row.notice_no) ex.notice_no = row.notice_no;
        if (!ex.effective_date && row.effective_date) ex.effective_date = row.effective_date;
      } else { seen.add(row.id); row[field] = val; results.push(row); }
    }
  };
  merge(await trgmP as Chunk[], '_trgm_score', 'trgm_score');
  merge(await semP as Chunk[], '_semantic_score', 'similarity');

  // ── RRF(Reciprocal Rank Fusion) 융합 (app.js searchKeywords와 동일 유지) ──
  // 종전에는 키워드 정규화(0~1)+trgm+시맨틱×2를 그대로 합산해 척도가 다른 점수끼리 싸웠다
  // (시맨틱 상위=논문이어도 합산 우승). 각 검색을 '순위'로 환산해 1/(K+순위) 합으로 융합하면
  // 척도 문제가 사라진다(K=60 관례) — "몇 개의 검색에서 얼마나 상위였나"가 결정한다.
  const synNormSet = new Set(lawSynonymKeywords(query).map((s) => s.toLowerCase()));
  for (const r of results) {
    let score = 0;
    for (const kw of keywords.slice(0, 10)) {
      const w = baseKeywords.includes(kw) ? 2 : 1;
      const k = kw.toLowerCase();
      if ((r.content || '').toLowerCase().includes(k)) score += w;
      if ((r.doc_name || '').toLowerCase().includes(k)) score += w;
      // 조문 표제어 일치 가점 — 질문 상투어('절차' 등)는 제외, LAW_SYNONYMS 출신 행위어는 가중
      if ((r.article_no || '').toLowerCase().includes(k) && !GENERIC_QUERY_WORDS.includes(kw)) {
        score += synNormSet.has(k) ? 4 : w * 2;
      }
    }
    r._score = score;          // RRF 순위 산출용 (절대값은 융합에 안 쓴다)
    r._hybrid_score = 0;
  }
  const RRF_K = 60;
  const addRrf = (list: Chunk[]) => {
    list.forEach((r, idx) => { r._hybrid_score = (r._hybrid_score || 0) + 1 / (RRF_K + idx + 1); });
  };
  addRrf(results.filter((r) => (r._score || 0) > 0).slice().sort((a, b) => (b._score || 0) - (a._score || 0)));
  addRrf(results.filter((r) => (r._trgm_score || 0) > 0).slice().sort((a, b) => (b._trgm_score || 0) - (a._trgm_score || 0)));
  addRrf(results.filter((r) => (r._semantic_score || 0) > 0).slice().sort((a, b) => (b._semantic_score || 0) - (a._semantic_score || 0)));
  // 일반 가점·감점: 파일 확장자 문서(논문·계획서류) 감점 + **article_no 종류별 등급**(#90).
  // 크기 0.5/(K+1) = 목록 1개 1위 기여의 절반 — 논문이 조문을 이기려면 한 목록 상위만큼 더 필요.
  // 종전에는 article_no가 있으면 종류 불문 같은 가점이었다. 그런데 실DB에서 article_no 보유
  // 18,349개 중 **조문은 41%(7,587)뿐**이고 별표 5,538·부칙 1,704·별지 1,421·붙임 1,191·
  // 서식 908이 조문과 동급 가점을 받고 있었다 — 「주파수 재할당 대가」 15자리를 별표 7개가
  // 먹고(그중 전자파적합성 별표 5는 가정용 전기기기라 완전 무관), 「개인정보 유출」은 부칙이
  // 2자리를 차지했다. 등급을 나눈 A/B 실측: 75자리 중 8자리 교체, **악화 사례 0건**.
  // 별표·붙임은 **배제가 아니라 가점만 뗀다**(#88과 같은 원칙) — 진짜 정본인 별표
  // (전파법 시행령 별표 2·3 = 주파수할당대가 산정기준)는 시맨틱·키워드 점수로 여전히 올라온다.
  const FILE_DOC_RE = /\.(pdf|md|docx|hwp)$/i;
  const UNIT = 0.5 / (RRF_K + 1);
  const articleBonus = (art?: string): number => {
    if (!art) return 0;                                   // 보도자료·회의록 — 가점 없음(감점도 없음)
    if (/^\d+조/.test(art)) return UNIT;                  // 조문
    if (/^(별표|붙임)/.test(art)) return 0;                // 표·부속 — 중립
    if (/^(부칙|서식|별지)/.test(art)) return -UNIT;       // 개정 이력·서식 — 운영자: "우선순위가 아니다"
    return 0;
  };
  for (const r of results) {
    r._hybrid_score = (r._hybrid_score || 0) + articleBonus(r.article_no);
    if (FILE_DOC_RE.test(r.doc_name || '')) r._hybrid_score = (r._hybrid_score || 0) - UNIT;
  }
  results.sort((a, b) => (b._hybrid_score || 0) - (a._hybrid_score || 0));
  // 문서당 청크 상한 — doc_category별 차등 (PERDOC_LIMIT): 추가지식 ≤8, 그 외 ≤3 (독식 방지)
  const perDoc: Record<string, number> = {};
  const picked: Chunk[] = [];
  for (const r of results) {
    if (picked.length >= TOTAL_CHUNK_CUT) break;
    const dn = r.doc_name || '';
    const cap = PERDOC_LIMIT[r.doc_category || ''] || PERDOC_LIMIT['default'];
    perDoc[dn] = (perDoc[dn] || 0) + 1;
    if (perDoc[dn] <= cap) picked.push(r);
  }
  return picked;
}

// ── kb 요약 검색 (app.js searchKbSummaries 이식: trgm×5 + 시맨틱(law-2)×10 융합, 상위 5) ──
interface KbRow { doc_id: string; chunk_idx: number; title?: string; content?: string; law_type?: string; law_number?: string; enforcement_date?: string; trgm_score?: number; similarity?: number; _score?: number; }
async function searchKbSummaries(sb: SupabaseClient, query: string): Promise<KbRow[]> {
  try {
    const trgmP = sb.rpc('search_kb_chunks_trgm', { query_text: query, match_threshold: 0.10, match_count: 6, only_current: true })
      .then((r) => r.data || []).catch(() => []);
    const semP = getQueryEmbedding(query, 'voyage-law-2').then((emb) => {
      if (!emb) return [];
      return sb.rpc('match_kb_chunks_semantic', { query_embedding: emb, match_threshold: 0.35, match_count: 6, only_current: true })
        .then((r) => r.data || []).catch(() => []);
    });
    const trgm = await trgmP as KbRow[], sem = await semP as KbRow[];
    const seen: Record<string, KbRow> = {};
    const out: KbRow[] = [];
    const key = (r: KbRow) => r.doc_id + ':' + r.chunk_idx;
    for (const r of sem) { r._score = (r.similarity || 0) * 10; out.push(r); seen[key(r)] = r; }
    for (const r of trgm) {
      const k = key(r);
      if (seen[k]) seen[k]._score = (seen[k]._score || 0) + (r.trgm_score || 0) * 5;
      else { r._score = (r.trgm_score || 0) * 5; out.push(r); seen[k] = r; }
    }
    out.sort((a, b) => (b._score || 0) - (a._score || 0));
    return out.slice(0, 5);
  } catch { return []; }
}

// ── 컨텍스트 조립 (app.js buildRagContext / buildKbContext 이식) ──
function buildRagContext(chunks: Chunk[]): string {
  if (!chunks.length) return '';
  const items = chunks.map((c, i) => {
    const meta: string[] = [];
    if (c.article_no) meta.push('조항: ' + c.article_no);
    if (c.notice_no) meta.push('고시번호: ' + c.notice_no);
    if (c.effective_date) meta.push('시행일: ' + c.effective_date);
    const metaStr = meta.length ? ' [' + meta.join(' | ') + ']' : '';
    return `[참조 ${i + 1}] 출처: ${c.doc_name} (${c.doc_category || ''})${metaStr}\n${c.content}`;
  });
  return '\n\n---\n\n[RAG 검색 결과 — 질문과 관련된 실제 법령·고시 원문]\n아래 내용은 질문과 의미적으로 유사한 문서 청크를 검색한 결과입니다. 반드시 아래 원문을 최우선으로 인용하고, 조항 번호와 내용이 일치하는지 확인하여 답변하세요:\n\n' + items.join('\n\n---\n\n');
}
// ── 별표 동반 인출 (app.js buildAnnexContext 이식 — #90) ─────────────────────
// 법령 조문은 실제 숫자를 안 담고 별표로 넘긴다: 전파법 시행령 제14조는 "별표 3에 따라
// 산정한다"고만 하고 산식은 별표 3에 있다. 조문만 근거로 주면 봇은 「별표 3에 따라
// 산정합니다」로 끝나고 정작 물어본 금액·요율·기준을 답하지 못한다.
// 대시보드에는 이 경로가 있었는데(315개 별표가 이 경로로 닿는다) **봇에는 아예 없었다.**
// app.js와 동일 유지 — 한쪽만 고치지 말 것. 상한 값도 같게 둔다.
const ANNEX_MAX_UNITS = 2;     // 질문당 별표 개수
const ANNEX_MAX_CHUNKS = 6;    // 별표당 청크 (별표 하나가 최대 812청크라 상한 필수)

interface AnnexRow { chunk_index: number; article_no?: string; content?: string }

async function buildAnnexContext(sb: SupabaseClient, chunks: Chunk[], question: string): Promise<{ text: string; sources: string[] }> {
  const sources: string[] = [];
  if (!chunks || !chunks.length) return { text: '', sources };
  try {
    // 1) 검색된 '조문' 청크에서 별표 인용을 뽑는다. 별표·별지 청크 자신은 제외(자기 참조 방지).
    //    「다른 법령」 별표 N 형태는 건너뛴다 — 같은 문서의 같은 번호 별표를 붙이면
    //    엉뚱한 표가 들어간다(전체 인용 978건 중 90건이 타 법령 인용).
    const wanted: Array<{ doc_name: string; no: string }> = [];
    const seen = new Set<string>();
    const reCite = /(「[^」]{2,40}」[^\n]{0,20}?)?별표\s*제?\s*(\d+(?:의\d+)?)/g;
    for (const c of chunks) {
      if (/^(별표|별지)/.test(c.article_no || '')) continue;
      reCite.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = reCite.exec(String(c.content || '')))) {
        if (m[1]) continue;                       // 타 법령 인용 — 건너뜀
        const key = c.doc_name + '|' + m[2];
        if (seen.has(key)) continue;
        seen.add(key);
        wanted.push({ doc_name: c.doc_name, no: m[2] });
      }
    }
    // 인용이 없어도 그냥 끝내면 안 된다 — 아래 2)의 '표 머리 보충'이 필요한 경우가
    // 바로 이 경우다(별표 조각만 검색되고 조문은 안 잡힌 질문).
    const units = wanted.slice(0, ANNEX_MAX_UNITS);   // chunks가 순위순이라 앞쪽이 상위 조문

    const qWords = extractKeywords(question || '');
    const blocks: string[] = [];
    for (const w of units) {
      const r = await sb.from('document_chunks')
        .select('chunk_index,article_no,content')
        .eq('doc_name', w.doc_name).eq('status', 'current')
        .like('article_no', '별표 ' + w.no + '(%')
        .order('chunk_index', { ascending: true });
      const all = (r.data || []) as AnnexRow[];
      if (r.error || !all.length) continue;

      // 첫 청크는 무조건 넣는다 — 표의 열 이름이 여기에만 있어서,
      // 가운데 청크만 넣으면 '1만원 │― │―'처럼 무슨 숫자인지 알 수 없다.
      const picked: AnnexRow[] = [all[0]];
      const rest = all.slice(1)
        .map((c) => ({ c, hit: qWords.reduce((a, kw) => a + (String(c.content || '').includes(kw) ? 1 : 0), 0) }))
        .sort((a, b) => (b.hit !== a.hit ? b.hit - a.hit : a.c.chunk_index - b.c.chunk_index));
      for (const x of rest.slice(0, ANNEX_MAX_CHUNKS - 1)) picked.push(x.c);
      picked.sort((a, b) => a.chunk_index - b.chunk_index);

      const title = all[0].article_no || ('별표 ' + w.no);
      const omitted = all.length - picked.length;
      blocks.push('[' + w.doc_name + ' ' + title + ']'
        + (omitted > 0 ? `\n※ 이 별표는 전체 ${all.length}개 조각 중 질문과 가까운 ${picked.length}개만 실었습니다. 표의 일부만 보이면 그렇게 밝히세요.` : '')
        + '\n' + picked.map((c) => c.content || '').join('\n'));
      sources.push(w.doc_name.split('(')[0].trim() + ' ' + title.split('(')[0].trim());
    }

    // 2) 별표 청크가 검색으로 직접 잡혔는데 '첫 조각'이 빠진 경우 그것만 보충한다.
    //    표의 열 이름은 첫 조각에만 있어서, 가운데 조각만 들어가면 모델은
    //    '│1만원 │― │―│' 같은 숫자열만 보고 무슨 항목인지 모른다.
    //    대상은 **검색 상위 5위 안에 든 별표**로 좁힌다(하위권은 어차피 근거로 안 쓰인다).
    //    '첫 조각이 빠진 것'만 먼저 추린 뒤에 개수 상한을 건다 — 먼저 자르면 이미 충족된
    //    별표가 자리를 차지해 정작 필요한 것이 잘린다.
    const needHead = new Map<string, Chunk>();
    for (const c of chunks.slice(0, 5)) {
      if (!/^별표/.test(c.article_no || '')) continue;
      const k = c.doc_name + '|' + String(c.article_no).split('(')[0];
      if (!needHead.has(k)) needHead.set(k, c);
    }
    const headBlocks: string[] = [];
    for (const hc of needHead.values()) {
      if (headBlocks.length >= 2) break;
      const prefix = String(hc.article_no).split('(')[0];
      const hr = await sb.from('document_chunks')
        .select('chunk_index,article_no,content')
        .eq('doc_name', hc.doc_name).eq('status', 'current')
        .like('article_no', prefix + '(%')
        .order('chunk_index', { ascending: true }).limit(1);
      const rows = (hr.data || []) as AnnexRow[];
      if (hr.error || !rows.length) continue;
      const first = rows[0];
      // 이미 검색 결과에 첫 조각이 들어 있으면 중복이므로 건너뛴다
      if (chunks.some((c) => c.doc_name === hc.doc_name && c.chunk_index === first.chunk_index)) continue;
      // 1)에서 이 별표를 통째로 실었다면 머리도 이미 들어갔다
      if (sources.includes(hc.doc_name.split('(')[0].trim() + ' ' + prefix)) continue;
      headBlocks.push('[' + hc.doc_name + ' ' + (first.article_no || prefix) + ' — 표 머리(열 이름)]\n' + (first.content || ''));
      sources.push(hc.doc_name.split('(')[0].trim() + ' ' + prefix + ' 머리');
    }
    if (headBlocks.length) {
      blocks.push('※ 아래는 위 검색 결과에 열 이름 없이 일부만 실린 표의 머리 부분입니다. 숫자가 어느 항목인지 여기서 확인하세요.\n\n'
        + headBlocks.join('\n\n'));
    }

    if (!blocks.length) return { text: '', sources: [] };
    return {
      text: '\n\n---\n\n[인용 조문이 가리키는 별표 원문]\n'
        + '위 조문이 "별표 N에 따른다"고 한 그 별표를 함께 싣습니다. **금액·기준·요율은 조문이 아니라 이 별표가 정본**이므로 여기서 인용하세요. '
        + '단, 질문이 묻는 항목이 이 별표에 없으면 없다고 답하고 임의로 유추하지 마세요.\n\n'
        + blocks.join('\n\n---\n\n'),
      sources,
    };
  } catch (e) {
    console.warn('별표 동반 인출 실패(건너뜀):', e);
    return { text: '', sources: [] };
  }
}

function buildKbContext(rows: KbRow[]): string {
  if (!rows.length) return '';
  const items = rows.map((r, i) => {
    const meta: string[] = [];
    if (r.law_type) meta.push(r.law_type);
    if (r.law_number) meta.push('법령번호: ' + r.law_number);
    if (r.enforcement_date) meta.push('시행일: ' + r.enforcement_date);
    const metaStr = meta.length ? ' [' + meta.join(' | ') + ']' : '';
    return `[법령요약 ${i + 1}] ${r.title || ''}${metaStr}\n${r.content || ''}`;
  });
  return '\n\n---\n\n[법령·규제 요약 지식베이스 — 현행 법령·고시·훈령 요약/실무]\n정확한 조문 번호·문구 인용은 위 RAG 조문 원문을 최우선으로 하고, 이 요약은 실무 맥락 보강용으로 쓰세요:\n\n' + items.join('\n\n---\n\n');
}

// ── Sonnet 호출: 스트리밍으로 받아 서버에서 누적 ──
// (스트리밍 유지 이유: 비스트리밍 회귀 금지 가드레일과 일관 + Sonnet5 적응형 추론의
//  content[0]=thinking 함정 회피 — 스트림에서는 text_delta만 골라 누적하면 안전)
// system은 문자열 또는 블록 배열을 그대로 API에 전달 (블록 배열 = 프롬프트 캐싱용, answerAdvisory 참조)
type SystemBlock = { type: 'text'; text: string; cache_control?: { type: 'ephemeral' } };
// 웹 검색 인용 — 스트림의 citations_delta에서 수집한 실제 근거 URL.
// (2026-08-03 이전에는 text_delta만 담고 인용을 버려서, 웹에서 온 수치·현황의 출처가
//  어디에도 안 남았다 — footer에는 내부 RAG 문서명만 나열돼 "참고가 전부 법령" 사고.)
export interface WebRef { url: string; title: string }
async function callSonnet(apiKey: string, system: string | SystemBlock[], question: string): Promise<{ text: string; webRefs: WebRef[] }> {
  const res = await fetch(ANTHROPIC_URL, {
    method: 'POST',
    headers: { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
    body: JSON.stringify({
      model: 'claude-sonnet-5',
      max_tokens: 5000,   // 제도(조문)+동향(기사)을 함께 답하게 했으므로 여유를 조금 더 줌   // 텔레그램 답변용 — 대시보드(24000)와 달리 3메시지 한도에 맞춤
      stream: true,
      system,
      tools: [{ type: 'web_search_20250305', name: 'web_search', max_uses: 3 }],
      messages: [{ role: 'user', content: question }],
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { error?: { message?: string } }).error?.message || `Anthropic HTTP ${res.status}`);
  }
  let text = '';
  const webRefs: WebRef[] = [];
  const seenUrls = new Set<string>();
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const events = buf.split('\n\n');
    buf = events.pop() || '';
    for (const ev of events) {
      for (const line of ev.split('\n')) {
        if (!line.startsWith('data:')) continue;
        try {
          const d = JSON.parse(line.slice(5).trim());
          if (d.type === 'content_block_delta' && d.delta?.type === 'text_delta') text += d.delta.text;
          // 웹 검색 인용 수집 — 모델이 본문에 실제로 갖다 쓴 웹 문서만 citation으로 온다
          // (검색만 하고 안 쓴 결과는 안 옴 = "실제 근거"의 목록으로 신뢰 가능)
          else if (d.type === 'content_block_delta' && d.delta?.type === 'citations_delta') {
            const c = d.delta.citation;
            if (c?.url && !seenUrls.has(c.url)) {
              seenUrls.add(c.url);
              webRefs.push({ url: c.url, title: (c.title || '').trim() || c.url });
            }
          }
        } catch { /* keep-alive 등 무시 */ }
      }
    }
  }
  return { text, webRefs };
}

// ── /law 키워드 검색 전용 (LLM 답변 없이 조문만 찾아 준다) ──
// 실측(2026-08-01): "3G 종료를 하는 방법"에 trgm 단독은 흔한 단어 '방법'에 끌려 개인정보·위치정보
// 시행령만 반환하고, 시맨틱을 더해도 못 잡는다(질문 어휘 "3G 종료" ≠ 법령 어휘 "휴지·폐지").
// ① Haiku 확장으로 어휘 간극을 메우고 ② 조문번호 있는 청크만 봐서 논문·보도자료를 배제하면
// 최상위가 '전파법 25조의2(무선국의 폐지 및 운용 휴지)'로 정확히 잡힌다.
// (article_no로 거르는 이유: doc_category '기타'에 고시와 박사논문이 섞여 카테고리로는 못 거른다)
export interface LawHit { id: number; doc_name: string; article_no?: string; content: string; _hits: number }

// 정책 어휘 → 법령 조문 표제어 대응표.
// LLM 확장만으로는 이 간극을 못 넘는다(실측: Haiku·Sonnet 모두 "3G 종료"에서 '휴업·폐업'을 못 냄).
// 법은 '서비스 종료'라 쓰지 않는다 — 전기통신사업법은 '휴업·폐업', 전파법은 '폐지·운용휴지'다.
// 이 표만 더해도 전파법 시행령 51조·전파법 25조의2가 최상위로 올라온다(실측).
const LAW_SYNONYMS: Record<string, string[]> = {
  '종료': ['휴업', '폐업', '폐지', '휴지', '운용휴지'],
  '중단': ['휴업', '휴지', '정지', '중지'],
  '폐지': ['폐업', '폐지', '휴지'],
  '개시': ['개설', '허가', '등록', '신고'],
  '시작': ['개설', '허가', '등록'],
  '변경': ['변경허가', '변경등록', '변경신고'],
  '취소': ['취소', '정지', '철회'],
  '반납': ['반납', '회수', '재할당'],
};

// 질문에 정책 동사가 있으면 대응하는 법령 표제어를 돌려준다 (app.js lawSynonymKeywords와 동일 유지)
function lawSynonymKeywords(query: string): string[] {
  const out: string[] = [];
  for (const [k, syns] of Object.entries(LAW_SYNONYMS)) {
    if (query.includes(k)) for (const s of syns) if (!out.includes(s)) out.push(s);
  }
  for (const [re, terms] of PRACTICE_TERMS) {
    if (re.test(query)) for (const t of terms) if (!out.includes(t)) out.push(t);
  }
  return out;
}

// ── 실무 용어 → 법령 용어 (2026-08-04, #83) ──────────────────────────────────
//  임베딩 모델은 한국어 법령으로 학습돼 **업계에서만 쓰는 외래어를 조문에 연결하지 못한다.**
//  실측(match_law_articles_semantic, voyage-4-lite):
//    "리파밍 관련 법 조항이 어떤게 있지?" → 1위 약관규제법 제30조 0.441 (전부 잡음)
//    "주파수 회수 또는 주파수 재배치"      → 1위 전파법 제6조의2   0.543 (정답)
//  즉 검색 엔진은 멀쩡한데 **질문의 어휘가 법령에 없는 것**이 원인이다. 「5G 커버리지 맵」이
//  안 잡히던 사건(#79)과 같은 계열 — 실무 용어와 법령 용어의 간극은 글자·의미 어느 쪽으로도
//  못 넘는다. 그래서 **검색 전에 질의 문자열 자체를 법령 용어로 보강**한다.
//  · 확신하는 대응만 넣는다. 틀린 대응은 엉뚱한 조문을 1위로 올려 없는 것보다 나쁘다.
//  · 원 질의는 지우지 않고 뒤에 덧붙인다(원 표현이 맞는 경우를 잃지 않도록).
const PRACTICE_TERMS: Array<[RegExp, string[]]> = [
  [/리파밍|리파-밍|re-?farming/i,      ['주파수회수', '주파수재배치', '주파수 회수', '주파수 재배치']],
  [/커버리지|coverage/i,               ['이용가능 지역', '서비스 제공 지역']],
  [/주파수\s*경매|경매/,               ['대가에 의한 주파수할당', '주파수할당']],
  [/알뜰폰|MVNO/i,                     ['도매제공', '도매제공의무사업자']],
  [/재할당/,                           ['주파수할당', '이용기간']],
];

/** 의미 검색용 질의 — 실무 용어가 있으면 법령 용어를 덧붙인다. 없으면 원문 그대로. */
export function expandQueryForSemantic(query: string): string {
  const add: string[] = [];
  for (const [re, terms] of PRACTICE_TERMS) {
    if (re.test(query)) for (const t of terms) if (!add.includes(t)) add.push(t);
  }
  return add.length ? `${query} ${add.join(' ')}` : query;
}
// 질문 상투어 — 조문 제목 가점·주제 매칭에서 제외 ('절차'가 「규제심사 절차」 같은
// 무관 조문 제목에 걸려 상위를 차지하는 것 방지. app.js GENERIC_QUERY_WORDS와 동일 유지)
const GENERIC_QUERY_WORDS = ['방법', '방안', '절차', '하는', '관련', '대한'];
// 법령 위계 (동점 정렬용): 법률 > 대통령령 > 부령·총리령 > 고시·훈령 등 — app.js lawRank와 동일 유지
function lawRank(docName: string | undefined): number {
  const d = docName || '';
  if (/\(법률\)/.test(d)) return 4;
  if (/\(대통령령\)/.test(d)) return 3;
  if (/(부령|총리령)\)/.test(d)) return 2;
  return 1;
}
// 도메인 사전확률: 이 KB는 전파·통신 정책용이라, 행위·주제 점수가 같으면 전파·통신 계열
// 법령이 국가재정법·위치정보법 같은 부수 수록 문서보다 근거일 확률이 높다 (질문과 무관한 상수 가점)
const DOMAIN_DOC_RE = /전파|통신|무선|주파수/;

export async function searchLawArticles(sb: SupabaseClient, query: string, limit = 5): Promise<LawHit[]> {
  const apiKey = env('ANTHROPIC_API_KEY');
  const base = extractKeywords(query);
  const expanded = apiKey ? await expandQueryKeywords(apiKey, query) : [];   // 키 없으면 기본 키워드만(페일소프트)

  const seen = new Map<string, boolean>();
  const keywords: string[] = [];
  const push = (w: string) => {
    const norm = w.replace(/\s+/g, '').toLowerCase();
    if (norm.length >= 2 && !seen.has(norm)) { seen.set(norm, true); keywords.push(w); }
  };
  // 기본 → 법령 표제어(LAW_SYNONYMS) → LLM 확장 순 — 표제어가 아래 slice(0,10) 상한에서
  // 확장어에 밀려 잘리면 안 된다(어휘 간극은 LLM이 못 메운다). app.js searchLawArticles와 동일 순서.
  base.forEach(push);
  lawSynonymKeywords(query).forEach(push);
  expanded.forEach(push);
  if (!keywords.length) return [];

  // .pdf/.md 등 파일 문서 제외 — '실행계획(안).pdf'도 '6조'라는 article_no를 갖고 있어
  // 조문번호 유무만으로는 못 거른다(실측). 법령·고시 문서명은 확장자로 끝나지 않는다.
  const FILE_SUFFIX = ['%.pdf', '%.md', '%.docx', '%.hwp'];
  const hit = (col: string, kw: string, take: number) => {
    let q = sb.from('document_chunks')
      .select('id, doc_name, article_no, content')
      .eq('is_approved', true).eq('status', 'current')
      .not('article_no', 'is', null)
      .ilike(col, '%' + kw + '%');
    for (const f of FILE_SUFFIX) q = q.not('doc_name', 'ilike', f);
    return q.limit(take).then((r) => (r.data || []) as LawHit[]).catch(() => [] as LawHit[]);
  };

  // 점수는 '행위'와 '주제'를 분리해 매긴다(실측으로 도달한 구조).
  //   행위 = 폐업·휴지 같은 조문 표제어 → 조문 제목에 걸리면 결정적(×5)
  //   주제 = 기간통신사업·무선국 같은 대상 → 문서명·조문제목에 걸리면 가산
  // 둘을 합치지 않고 나누는 이유: 주제만 맞는 문서(기간통신사업 양수·합병 고시)가
  // 행위가 맞는 조문(전기통신사업법 19조 사업의 휴업·폐업)을 밀어내는 일이 있었다.
  //
  // ★ limit을 작게 주면 안 된다: PostgREST는 정렬 없이 임의의 N건을 돌려주므로
  //   '폐업'으로 6건만 받으면 위치정보법·지방세법이 자리를 채우고 정작 전기통신사업법 19조가
  //   빠진다(실측 — limit 6에서 누락, 40에서 포함).
  const acc = new Map<number, LawHit & { _act: number; _top: number }>();
  const put = (r: LawHit, act: number) => {
    const cur = acc.get(r.id);
    if (cur) cur._act = Math.max(cur._act, act);
    else acc.set(r.id, { ...r, _hits: 0, _act: act, _top: 0 });
  };
  // 행위 가중은 어휘의 출처로 차등한다: LAW_SYNONYMS 출신(정책어→법령표제어로 '번역'된 말,
  // 예: 종료→휴업·폐업)은 7, 그 외(질문 원어·LLM 확장)는 5. 원어가 조문 제목에 우연히
  // 있는 경우('조난통신 종료 통보')는 대개 다른 제도라, 번역된 표제어보다 낮게 본다.
  // (실측: 이 차등이 없으면 "3G 종료"에서 선박국 운용종료·조난통신 조문이
  //  전기통신사업법 19조(사업의 휴업·폐업)·전파법 25조의2를 밀어낸다)
  const synNorms = new Set(lawSynonymKeywords(query).map((s) => s.replace(/\s+/g, '').toLowerCase()));
  const jobs: Promise<void>[] = [];
  for (const kw of keywords.slice(0, 10)) {
    const act = synNorms.has(kw.replace(/\s+/g, '').toLowerCase()) ? 7 : 5;
    jobs.push(hit('article_no', kw, 40).then((rows) => rows.forEach((r) => put(r, act))));
    jobs.push(hit('content', kw, 10).then((rows) => rows.forEach((r) => put(r, 0))));
  }
  await Promise.all(jobs);

  // 주제 일치는 부분문자열로 본다 — '기간통신사업'과 '전기통신사업법'은 앞글자가 달라
  // 접두 비교로는 안 잡히고 '통신사업'이라는 공통 조각으로만 이어진다.
  const topics = (query.match(/[가-힣A-Za-z0-9]{2,}/g) || [])
    .filter((t) => !GENERIC_QUERY_WORDS.includes(t));
  for (const h of acc.values()) {
    const hay = h.doc_name + ' ' + (h.article_no || '');
    let best = 0;
    for (const t of topics) {
      if (t.length <= 3) { if (hay.includes(t)) best = Math.max(best, t.length); continue; }
      for (let i = 0; i < t.length; i++) {
        for (let j = t.length; j - i >= 4; j--) {
          if (hay.includes(t.slice(i, j))) { best = Math.max(best, j - i); break; }
        }
      }
    }
    h._top = best;
    // 행위를 우선하되 주제로 갈래를 좁히고, 동점은 도메인(전파·통신 계열) 문서를 앞세운다
    h._hits = h._act * 2 + best + (DOMAIN_DOC_RE.test(h.doc_name) ? 1 : 0);
  }
  // 정렬: 점수 → (동점이면) 법령 위계(법률>대통령령>부령>고시) → 문서명·조문번호(결정적 순서).
  // 위계 동점 처리는 특정 법 우대가 아니라 일반 규칙 — 같은 점수면 상위 법령의 조문이 근거로 더 낫다.
  const sorted = [...acc.values()].sort((a, b) => {
    if (b._hits !== a._hits) return b._hits - a._hits;
    const lr = lawRank(b.doc_name) - lawRank(a.doc_name);
    if (lr !== 0) return lr;
    if (a.doc_name !== b.doc_name) return a.doc_name < b.doc_name ? -1 : 1;
    return (a.article_no || '') < (b.article_no || '') ? -1 : 1;
  });
  // 같은 조문이 여러 청크로 쪼개져 있으면 대표 1건만 — 목록이 중복으로 채워지는 것 방지
  const byArticle = new Map<string, LawHit>();
  for (const h of sorted) {
    const key = h.doc_name + '|' + (h.article_no || '');
    if (!byArticle.has(key)) byArticle.set(key, h);
  }
  return [...byArticle.values()].slice(0, limit);
}

// ── /law 자연어 모드 — 법령 한정 답변 (2026-08-03) ──
// "궁금한 사항이 어떤 법과 관련돼 있는지"가 팀의 실제 질문 형태(운영자)라, 조문번호 즉답과
// 별개로 자연어 질의를 받는다. /ask와의 경계: **법령 내용만** — 뉴스·국회동향·웹검색·시사점을
// 넣지 않는다(그건 /ask의 몫). 그래서 answerAdvisory를 재사용하지 않고 조문 검색 + 요약층만
// 모아 Haiku(법령 나열·관련 이유 설명은 좁은 일이라 Sonnet 불필요, 건당 ~$0.01)로 답한다.
export async function answerLawQuery(sb: SupabaseClient, query: string): Promise<string | null> {
  const apiKey = env('ANTHROPIC_API_KEY');
  if (!apiKey) return null;
  // 조문 검색을 **세 갈래**로 돌린다 (2026-08-03 사고에서 도달한 구조).
  //  ① 키워드(searchLawArticles) — 질문 어휘가 조문에 그대로 있을 때 정확하다.
  //  ② 의미(match_law_articles_semantic) — 어휘가 어긋나도 뜻으로 찾는다. **조문만** 대상.
  //  ③ 요약층 다리 — 요약층(voyage-law-2)이 짚은 법령의 조문을 이름으로 확정 조회.
  // 발단: "5G 커버리지 맵 공개" 질문에서 「전기통신역무 선택에 필요한 정보 제공 기준」을 통째로
  // 놓쳤다. 그 고시는 '커버리지'라는 말을 한 번도 쓰지 않고 '이용가능 지역'·'지도 등의 형태'라고
  // 쓴다 — 실무 용어와 법령 용어의 간극은 글자 일치로 절대 못 넘는다. 그런데 ②만 더해도 안 됐고,
  // 임베딩 모델을 voyage-law-2로 바꿔도 7위까지만 올라왔다(실측 A/B). 진짜 원인은 **검색 대상**
  // 이었다 — 부칙·별표·서식이 상위를 독식하고 있었다. ②를 조문 전용으로 좁혀 대부분 해결되고,
  // 남는 사각지대는 ③이 덮는다.
  const [hits, semantic, kb] = await Promise.all([
    searchLawArticles(sb, query, 8),
    // /law 전용 의미 검색 — 조문만 대상(match_law_articles_semantic). 범용 searchChunks를
    // 쓰면 검색 공간의 2/3가 조문이 아니라(보도자료·회의록·논문 40.6%, 별표 17.9%, 부칙 5.5%,
    // 서식 2.9%) 조문이 밀려난다. 실측: 이 RPC로 바꾸자 "기지국 개설 허가 절차"의 정답
    // (전파법 21조)이 5위→1위, "개인정보 유출 신고"가 시행령 40조·법 34조로 1·2위가 됐다.
    // 질의를 법령 용어로 보강해 임베딩한다(#83) — 「리파밍」처럼 조문에 없는 업계 용어는
    // 원문 그대로 넣으면 유사도가 잡음 수준(0.44)에 묻힌다. expandQueryForSemantic 주석 참조.
    getQueryEmbedding(expandQueryForSemantic(query)).then((emb) => emb
      ? sb.rpc('match_law_articles_semantic', { query_embedding: emb, match_threshold: 0.0, match_count: 8, only_current: true })
          .then((r) => (r.data || []) as Chunk[])
      : [] as Chunk[]).catch(() => [] as Chunk[]),
    searchKbSummaries(sb, expandQueryForSemantic(query)).catch(() => [] as KbRow[]),
  ]);

  // 의미 검색분에서 **조문만** 남긴다 — article_no가 없는 것(보도자료 등)과 파일 문서(논문·계획서)는
  // /law의 답이 아니다. 그 필터는 searchLawArticles가 쓰는 기준과 같게 유지한다.
  const haveIds = new Set(hits.map((h) => h.id));
  const semExtra: LawHit[] = (semantic || [])
    .filter((c) => c.article_no && !haveIds.has(c.id) && !/\.(pdf|md|docx|hwp)$/i.test(c.doc_name || ''))
    .slice(0, 6)
    .map((c) => ({ id: c.id, doc_name: c.doc_name, article_no: c.article_no, content: c.content, _hits: 0 }));
  semExtra.forEach((h) => haveIds.add(h.id));

  // ③ 요약층 다리 — 요약층(kb)이 짚은 법령의 **실제 조문**을 이름으로 직접 끌어온다.
  // 왜 필요한가(2026-08-03 실측): 조문 원문 임베딩은 voyage-4-lite인데 한국어 법령에서 변별력이
  // 약하다. "5G 커버리지 맵 공개"에서 정답인 「전기통신역무 선택에 필요한 정보 제공 기준」 제5조는
  // 유사도 0.418로, 무관한 별표·부칙(0.50~0.54) 수십 건에 밀려 40위 밖이었다. 반면 요약층은
  // 법률 특화 voyage-law-2를 써서 같은 질문에 이 고시를 정확히 짚었다.
  // → 잘 맞히는 검색이 지목한 법령의 조문을 확정적으로 가져오면, 검색 운에 기대지 않아도 된다.
  // (HNSW는 ef_search 기본값 탓에 300건을 요청해도 ~40건만 훑는다 — 임계·건수를 올려도 못 넘는다.)
  const kbTitles = [...new Set(kb.map((r) => (r.title || '').trim()))].filter((t) => t.length >= 4).slice(0, 3);
  const bridged: LawHit[] = [];
  if (kbTitles.length) {
    const qWords = extractKeywords(query).map((w) => w.toLowerCase());
    const perTitle = await Promise.all(kbTitles.map((t) =>
      sb.from('document_chunks')
        .select('id, doc_name, article_no, content')
        .eq('is_approved', true).eq('status', 'current')
        .not('article_no', 'is', null)
        .ilike('doc_name', t + '%')     // 요약 제목은 정식 법령명의 앞부분 (뒤에 (부처)(호수)(시행일)이 붙는다)
        .limit(40)
        .then((r) => (r.data || []) as LawHit[]).catch(() => [] as LawHit[])));
    const BRIDGE_TOTAL_CAP = 14;   // 전체 상한 — 프롬프트 폭주 방지 (조문당 800자 → 최대 ~11K자)
    for (const rows of perTitle) {
      const fresh = rows.filter((r) => !haveIds.has(r.id) && !/^(부칙|별표|서식)/.test(r.article_no || ''));
      // 조문이 적은 고시·훈령이면 **통째로** 넣는다. 점수로 4개만 고르다가 정작 핵심인
      // 제6조(지도 형태로 홈페이지 게시)가 5순위로 잘렸다 — '목적'·'정의' 같은 상투 조문이
      // 전기통신·정보·제공 같은 흔한 단어로 점수를 먼저 가져가기 때문이다(실측).
      // 요약층이 이미 "이 법령이 답"이라고 지목한 뒤이므로, 작은 법령은 고르지 말고 다 보여준다.
      const picked = fresh.length <= 10
        ? fresh
        : fresh.map((r) => {
            const hay = ((r.article_no || '') + ' ' + (r.content || '')).toLowerCase();
            let s = 0;
            for (const w of qWords) if (w.length >= 2 && hay.includes(w)) s++;
            return { r, s };
          }).sort((a, b) => b.s - a.s).slice(0, 5).map((x) => x.r);
      for (const r of picked) {
        if (bridged.length >= BRIDGE_TOTAL_CAP) break;
        haveIds.add(r.id); bridged.push(r);
      }
    }
  }

  const merged = hits.concat(semExtra, bridged);
  if (!merged.length && !kb.length) return null;   // 검색 0건 — 호출자가 미등재 안내

  // 프롬프트에 넣는 순서를 **법 위계 순**(법률>대통령령>부령>고시)으로 맞춘다. 검색 점수 순으로
  // 넣으면 시행령이 앞서고 상위 법률이 뒤로 밀려, 모델이 시행령만 인용하고 근거 법률을 빠뜨린다
  // (2026-08-03 실측: "개인정보 유출 신고 기한" 답변에 시행령 40·39조만 나오고 법 34조 누락).
  // 같은 위계 안에서는 원래 순서(검색 관련도)를 유지 — 안정 정렬.
  merged.sort((a, b) => lawRank(b.doc_name) - lawRank(a.doc_name));

  const ctxParts: string[] = [];
  if (merged.length) {
    // 문서명·시행일·조항을 **분리 표기**한다(#87 후속).
    // 종전에는 `전파법(법률)(제21065호)(20260102) 부칙 제20067호(20240123)` 한 줄이라,
    // 모델이 doc_name 괄호 속 시행일과 부칙 제목의 날짜를 구분하지 못하고
    // 「전파법 시행일은?」에 부칙의 2024.7.23을 답했다(실제 현행 시행일은 2026.1.2).
    // 자문 경로(buildRagContext)는 이미 「시행일: …」을 별도 항목으로 빼고 있었는데
    // /law만 자체 포맷을 써서 그 정보가 통째로 없었다. 형식을 맞춘다.
    ctxParts.push('[검색된 조문]\n' + merged.map((h, i) => {
      const m = /^(.+?)\((법률|대통령령|[^)]*령|[^)]*고시|[^)]*훈령|[^)]*예규|[^)]*규칙)\)(?:\(([^)]*)\))?(?:\((\d{8})\))?/.exec(h.doc_name || '');
      const name = m ? m[1].trim() : (h.doc_name || '');
      const meta: string[] = [];
      if (m?.[2]) meta.push(m[2]);
      if (m?.[3]) meta.push(m[3]);
      if (m?.[4]) meta.push(`시행일 ${m[4].slice(0, 4)}-${m[4].slice(4, 6)}-${m[4].slice(6, 8)}`);
      const head = meta.length ? `${name} [${meta.join(' | ')}]` : (h.doc_name || '');
      return `[조문 ${i + 1}] ${head}${h.article_no ? '\n조항: ' + h.article_no : ''}\n${(h.content || '').slice(0, 800)}`;
    }).join('\n\n---\n\n'));
  }
  if (kb.length) {
    ctxParts.push('[법령 요약(실무 맥락 보강용 — 조문 인용은 위 원문 우선)]\n' + kb.slice(0, 3).map((r) =>
      `· ${(r.title || '').trim()}\n${(r.content || '').slice(0, 500)}`
    ).join('\n\n'));
  }

  const system =
    '당신은 한국 전파·통신 분야 법령 검색 도우미입니다. 아래 검색 결과만 근거로, 질문이 어떤 법령·조항과 관련되는지 정리하세요.\n\n' +
    '형식:\n' +
    '- 관련도 높은 순으로 3~6개 항목. 각 항목은 **법령명 제N조(제목)** 한 줄 + 왜 이 질문과 관련되는지 1~2문장. 필요하면 조문 핵심 문구를 짧게 직접 인용.\n' +
    '- 마지막에 한 줄 요약(어느 법이 중심인지)을 붙여도 좋습니다.\n\n' +
    '규칙:\n' +
    '- **위임 관계를 반드시 밝히세요.** 한국 법령은 기한·금액·요건 같은 구체적 기준을 시행령·시행규칙·고시에 위임하는 구조가 기본입니다. 검색 결과에 상위 법률 조문과 하위법령 조문이 함께 있으면 **둘 다** 제시하고, "법률은 「지체 없이」라고만 정하고 시행령이 이를 72시간으로 구체화한다"처럼 관계를 한 줄로 설명하세요. 하위법령만 인용하면 근거가 반쪽이 되어 보고서에 그대로 쓸 수 없습니다.\n' +
    '- 검색 결과에 있는 관련 조문을 임의로 빼지 마세요. 특히 질문의 답이 되는 상위 법률 조항은 생략 금지입니다.\n' +
    '- 기관명을 임의로 묶지 마세요. "보호위원회 또는 전문기관(한국인터넷진흥원)"처럼 법문이 선택적으로 정한 것을 "보호위원회(한국인터넷진흥원)"로 적으면 두 기관이 같은 곳으로 읽힙니다.\n' +
    '- 법 체계 순서로 제시하세요(법률 → 시행령 → 시행규칙 → 고시). 같은 위계면 조문 번호 순.\n' +
    // 2026-08-05 실사용 오답(#87 후속): 「전파법 시행일은 언제인가」에 부칙 제20067호(2024.1.23 공포)를
    // 집어 "2024.7.23 시행"이라 답했다. 실제 현행 시행일은 2026.1.2다.
    // 원인 — 전파법 문서 하나에 부칙 청크가 19개 있다(역대 개정 이력). 그중 하나의 시행일을
    // 법 전체의 시행일로 착각한 것. 정답은 각 청크 머리의 「시행일: …」 메타(effective_date)에 이미 있다.
    // /law가 부칙을 배제하던 때는 이 질문에 "못 찾음"이라 답했는데, 가중치로 열자 **자신 있게 틀린 답**이
    // 됐다. 검색 범위를 넓히면 프롬프트도 함께 좁혀 줘야 한다는 사례.
    '- **「시행일」을 물으면 각 항목 머리의 「시행일: YYYYMMDD」 메타를 근거로 답하세요.** 그것이 그 법령의 현행 시행일입니다.\n' +
    '  부칙은 **과거 개정 하나하나의 이력**이며 한 법령에 수십 개가 있습니다. 부칙에 적힌 "공포 후 N개월" 같은 문구는 **그 개정분의 시행 시점**일 뿐, 법 전체의 현행 시행일이 아닙니다. 부칙 시행일을 법의 시행일로 제시하지 마세요.\n' +
    '  특정 개정(예: 「제20067호 개정은 언제부터인가」)을 물은 경우에만 해당 부칙을 근거로 답하고, 어느 개정의 것인지 반드시 밝히세요.\n' +
    '- 검색 결과에 없는 법령명·조항 번호를 만들어내지 마세요. 검색 결과가 질문과 맞지 않으면 "등재 법령에서 직접 관련 조문을 찾지 못했습니다"라고 말하고, 걸린 것 중 가까운 것만 언급하세요.\n' +
    '- 시사점·전략 제언·최신 동향·뉴스·해외 사례는 쓰지 마세요 — 법령 내용만 다룹니다(그런 질문은 /ask 몫).\n' +
    '- 텔레그램 전송용: 표·코드블록 금지, 굵게(**)와 불릿(-)만, 전체 1,800자 이내.\n\n' +
    '---\n\n' + ctxParts.join('\n\n---\n\n');

  const res = await fetch(ANTHROPIC_URL, {
    method: 'POST',
    headers: { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
    body: JSON.stringify({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 1500,
      system,
      messages: [{ role: 'user', content: query }],
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { error?: { message?: string } }).error?.message || `Anthropic HTTP ${res.status}`);
  }
  const data = await res.json() as { content?: { type: string; text?: string }[] };
  // content[0]이 text가 아닐 수 있으므로 find로 고른다 (Sonnet5 적응형 추론에서 실제로 겪은 함정 — Haiku도 같은 방어)
  const text = (data.content || []).find((b) => b.type === 'text')?.text || '';
  return text.trim() || null;
}

// ── 뉴스 컨텍스트 (app.js fetchRecentNewsContext 이식) ──
// 조문만 보면 "휴지·폐지 절차는 이렇다"에서 끝난다. "3G 종료" 질문의 답 절반은
// 정부가 이용자 보호로 신중하고 IoT 회선이 변수라는 최신 동향이고, 그건 news_feed에 있다.
// 키워드 추출은 법령용(extractKeywords)과 분리 — 법령 불용어를 쓰면 '통신사·영향' 같은
// 저변별력 단어가 살아남아 엉뚱한 기사를 끌어온다(app.js와 동일 원칙).
function extractNewsKeywords(text: string): string[] {
  const stop = ['같은','같이','최대','최소','정도','이유','영향','분석','차이','통신사','통신','관련',
    '현황','상황','내용','문제','방안','대응','전망','의미','비교','평가','수준','규모','최근','요즘',
    '지금','현재','올해','작년','국내','해외','업계','우리','회사','부분','경우','전체','해줘','알려줘',
    '설명','정리','작성','검토','어떻게','어떤','무엇','언제','어디','왜','있다','없다','하다','되다',
    '이다','대해','관해','통해','위해','따라','대한','관한','그리고','하지만','방법','방안'];
  const tail = /(이라는데|이라는|이라며|이라고|인데도|에서는|으로는|에서의|에서도|라는데|인데|인가|인지|라며|라고|는데|에서|에는|으로|로는|보다|부터|까지|처럼|마다|조차|밖에|이나|은|는|이|가|을|를|의|에|와|과|도|만)$/;
  const domain = /주파수|대역|백홀|기지국|중계기|와이파이|5G|6G|3G|2G|LTE|위성|전파|간섭|재할당|할당|요금|보조금|단말|로밍|알뜰폰|망중립|과징금|국회|고시|시행령|입법예고|종료|폐지|휴지|IoT/i;
  const words = text.split(/[\s,.·()[\]「」『』<>:;!?"']+/)
    .map((w) => w.replace(/[^가-힣a-zA-Z0-9]/g, '').trim())
    .map((w) => { const s = w.replace(tail, ''); return domain.test(s) ? s : (domain.test(w) ? w : (s.length >= 2 ? s : w)); })
    .filter((w) => w.length >= 2 && !stop.includes(w));
  const uniq = words.filter((v, i, a) => a.indexOf(v) === i);
  return uniq.filter((w) => domain.test(w)).concat(uniq.filter((w) => !domain.test(w))).slice(0, 6);
}

interface NewsRow { title: string; source?: string; published_at?: string; content?: string }

async function buildNewsContext(sb: SupabaseClient, query: string): Promise<{ text: string; sources: string[] }> {
  try {
    const cutoff = new Date(Date.now() - 60 * 86400 * 1000).toISOString().slice(0, 10);   // 최근 60일
    const listP = sb.from('news_feed').select('title, source, published_at')
      .or('published_at.gte.' + cutoff + ',locked.eq.true')
      .not('title', 'ilike', '[업데이트]%')
      .order('published_at', { ascending: false }).limit(30)
      .then((r) => (r.data || []) as NewsRow[]).catch(() => [] as NewsRow[]);

    // 질문 키워드로 관련 기사 선별 — 제목 일치(가중 3) + 본문 일치(가중 1).
    // 최신순 상위 N건으로 뽑으면 특정 이슈가 폭주한 날 무관한 기사가 자리를 다 차지한다(배경역사 #35).
    const kws = extractNewsKeywords(query);
    const qs: Promise<{ w: number; rows: NewsRow[] }>[] = [];
    for (const kw of kws) {
      const esc = kw.replace(/[%_,]/g, ' ').trim();
      if (esc.length < 2) continue;
      qs.push(sb.from('news_feed').select('title, source, published_at, content')
        .or('published_at.gte.' + cutoff + ',locked.eq.true')
        .ilike('title', '%' + esc + '%').order('published_at', { ascending: false }).limit(10)
        .then((r) => ({ w: 3, rows: (r.data || []) as NewsRow[] })).catch(() => ({ w: 3, rows: [] as NewsRow[] })));
      qs.push(sb.from('news_feed').select('title, source, published_at, content')
        .or('published_at.gte.' + cutoff + ',locked.eq.true')
        .ilike('content', '%' + esc + '%').not('content', 'is', null)
        .order('published_at', { ascending: false }).limit(10)
        .then((r) => ({ w: 1, rows: (r.data || []) as NewsRow[] })).catch(() => ({ w: 1, rows: [] as NewsRow[] })));
    }
    const cand = new Map<string, { row: NewsRow; score: number }>();
    for (const p of await Promise.all(qs)) {
      for (const n of p.rows) {
        if (!n?.content) continue;                     // 본문 없으면 발췌 불가
        const c = cand.get(n.title) || { row: n, score: 0 };
        c.score += p.w;
        cand.set(n.title, c);
      }
    }
    const ranked = [...cand.values()].sort((a, b) =>
      b.score !== a.score ? b.score - a.score
        : String(b.row.published_at || '').localeCompare(String(a.row.published_at || '')));
    // 2점 미만(키워드 하나만 스친 기사)은 '질문 관련'으로 보기 어렵다 → 강한 후보가 없을 때만 완화
    const strong = ranked.filter((c) => c.score >= 2);
    const body = (strong.length ? strong.slice(0, 3) : ranked.slice(0, 2)).map((c) => c.row);

    const titles = await listP;
    const lines: string[] = [];
    if (body.length) {
      lines.push('[질문 관련 최신 기사]');
      // 1위는 거의 전문, 2·3위는 요지만 — 일괄로 짧게 자르면 기사 후반의 최신 상황이 날아간다(#35)
      body.forEach((n, i) => {
        const lim = i === 0 ? 1800 : 700;
        const full = n.content || '';
        lines.push('■ [' + String(n.published_at || '').slice(0, 10) + '] ' + n.title + ' (' + (n.source || '') + ')');
        if (full) lines.push('  → ' + full.slice(0, lim).trim() + (full.length > lim ? '...' : ''));
      });
    }
    if (titles.length) {
      lines.push('\n[최근 수집 뉴스 동향]');
      for (const n of titles) {
        lines.push('  · [' + String(n.published_at || '').slice(0, 10) + '] ' + n.title + ' (' + (n.source || '') + ')');
      }
    }
    if (!lines.length) return { text: '', sources: [] };

    return {
      text: '\n\n---\n\n[수집 뉴스 — 최신 정책 동향]\n' +
        '아래는 이 시스템이 수집한 실제 기사입니다. 정책 추진 단계·정부 입장·수치는 법령 조문이 아니라 ' +
        '이 기사들을 근거로 답하세요. 조문은 "제도가 어떻게 되어 있는지", 기사는 "지금 어떻게 돌아가는지"입니다.\n\n' +
        lines.join('\n'),
      // 본문 발췌로 실제 반영된 기사만 출처로 남긴다(제목 목록 30건은 근거가 아님 — 거짓 표기 방지)
      sources: body.map((n) => '[뉴스] ' + n.title + ' (' + (n.source || '출처미상') + ', ' + String(n.published_at || '').slice(0, 10) + ')'),
    };
  } catch (e) { console.warn('뉴스 컨텍스트 실패(건너뜀):', e); return { text: '', sources: [] }; }
}

// ── 국회 동향 컨텍스트 (app.js fetchAssemblyTrendContext 이식 — 대시보드와 동일 규칙 유지) ──
//
// 조문·기사가 '근거' 층이라면 이건 '배경' 층이다. 운영자 요구는 "국회에서 이런 논의도
// 진행되고 있다" 정도의 참고 정보이므로, 컨텍스트 맨 뒤에 소량만 붙이고 프롬프트에서
// 확정 법령처럼 서술하지 못하게 막는다(app_config.system_prompt [국회 동향 활용 원칙]).
//
// 비용 0 — 질의 임베딩을 추가로 만들지 않는다. assembly_speeches(~1.1천건)·assembly_bills(~230건)는
// 규모가 작고 summary가 정제돼 있어 ilike만으로 상위 적중이 나온다(실측). 점수 규칙 3가지는
// app.js 주석 참조(topic 태그 역방향 +3 / 희소 topic 앵커 / 법안 strong→fallback).
const ASM_RARE_MAX = 40;   // assembly_speeches 약 1,100건 기준 희소어 상한(≈4%)

interface SpeechRow {
  speaker?: string; position?: string; meeting_date?: string;
  agenda?: string; topic?: string; summary?: string;
}
interface BillRow {
  bill_name?: string; proposer?: string; committee?: string; proc_result?: string;
  propose_dt?: string | null; summary?: string; notice_end_dt?: string | null;
}

async function buildAssemblyTrendContext(sb: SupabaseClient, query: string): Promise<string> {
  try {
    const kws = extractNewsKeywords(query).slice(0, 5)
      .map((k) => String(k).replace(/[%_,.*()]/g, ' ').trim())
      .filter((k) => k.length >= 2);
    if (!kws.length) return '';
    const qLower = query.toLowerCase();

    const spRes = await Promise.all(kws.map((k) =>
      sb.from('assembly_speeches')
        .select('speaker,position,meeting_date,agenda,topic,summary', { count: 'exact' })
        .or('topic.ilike.*' + k + '*,agenda.ilike.*' + k + '*,summary.ilike.*' + k + '*')
        .order('meeting_date', { ascending: false }).limit(25)
        .then((r) => ({ kw: k, rows: (r.data || []) as SpeechRow[], total: r.count || 0 }))
        .catch(() => ({ kw: k, rows: [] as SpeechRow[], total: 0 }))));
    const blRes = await Promise.all(kws.map((k) =>
      sb.from('assembly_bills')
        .select('bill_name,proposer,committee,proc_result,propose_dt,summary,notice_end_dt')
        .or('bill_name.ilike.*' + k + '*,summary.ilike.*' + k + '*')
        .order('propose_dt', { ascending: false, nullsFirst: true }).limit(15)
        .then((r) => ({ kw: k, rows: (r.data || []) as BillRow[] }))
        .catch(() => ({ kw: k, rows: [] as BillRow[] }))));

    const rare: Record<string, number> = {};
    for (const r of spRes) rare[r.kw] = r.total;

    const spMap = new Map<string, SpeechRow>();
    for (const r of spRes) for (const s of r.rows) {
      const key = (s.meeting_date || '') + '|' + (s.speaker || '') + '|' + String(s.summary || '').slice(0, 40);
      if (!spMap.has(key)) spMap.set(key, s);
    }
    const speeches = [...spMap.values()].map((s) => {
      // ilike는 대소문자 무시라 JS 재검증도 소문자로 맞춘다('AI' 질의가 0점이 되는 것 방지)
      const topic = String(s.topic || '').toLowerCase();
      const agenda = String(s.agenda || '').toLowerCase();
      const sm = String(s.summary || '').toLowerCase();
      let score = 0, mk = 0, anchor = false;
      for (const k of kws) {
        const lk = k.toLowerCase();
        const inT = topic.includes(lk), inA = agenda.includes(lk), inS = sm.includes(lk);
        if (!inT && !inA && !inS) continue;
        mk++;
        score += inT ? 3 : (inA ? 2 : 1);
        if (inT && rare[k] && rare[k] <= ASM_RARE_MAX) anchor = true;
      }
      if (topic.split(',').some((t) => t.trim().length >= 2 && qLower.includes(t.trim()))) score += 3;
      return { row: s, score, ok: (mk >= 2 || anchor) && score >= 4 };
    }).filter((x) => x.ok)
      .sort((a, b) => b.score !== a.score ? b.score - a.score
        : String(b.row.meeting_date || '').localeCompare(String(a.row.meeting_date || '')))
      .slice(0, 4);

    const blMap = new Map<string, BillRow>();
    for (const r of blRes) for (const b of r.rows) {
      const key = (b.bill_name || '') + '|' + (b.proposer || '') + '|' + (b.propose_dt || '');
      if (!blMap.has(key)) blMap.set(key, b);
    }
    const today = new Date().toISOString().slice(0, 10);
    const bills = [...blMap.values()].map((b) => {
      const name = String(b.bill_name || '').toLowerCase();
      const sm = String(b.summary || '').toLowerCase();
      let score = 0, mk = 0;
      for (const k of kws) {
        const lk = k.toLowerCase();
        const inN = name.includes(lk), inS = sm.includes(lk);
        if (!inN && !inS) continue;
        mk++;
        score += inN ? 3 : 1;
      }
      // 의견등록 열린 건은 순위 가점만 — 통과 기준에 넣으면 무관 법안이 마감일만으로 올라온다
      return { row: b, score, mk, open: !!(b.notice_end_dt && b.notice_end_dt >= today) };
    });
    const strongB = bills.filter((x) => x.score >= 3);
    const pickB = (strongB.length ? strongB : bills.filter((x) => x.mk >= 2))
      .sort((a, b) => {
        const sa = a.score + (a.open ? 2 : 0), sbv = b.score + (b.open ? 2 : 0);
        if (sbv !== sa) return sbv - sa;
        return String(b.row.propose_dt || '9999').localeCompare(String(a.row.propose_dt || '9999'));
      }).slice(0, strongB.length ? 3 : 2);

    if (!speeches.length && !pickB.length) return '';

    const lines: string[] = [];
    if (speeches.length) {
      lines.push('▸ 과방위 회의 발언');
      for (const x of speeches) {
        const s = x.row;
        lines.push('  · [' + String(s.meeting_date || '').slice(0, 10) + '] ' + (s.speaker || '') +
          (s.position ? '(' + s.position + ')' : '') + ': ' +
          String(s.summary || '').replace(/\s+/g, ' ').trim().slice(0, 220) +
          (s.agenda ? ' [안건: ' + String(s.agenda).replace(/\s+/g, ' ').trim().slice(0, 40) + ']' : ''));
      }
    }
    if (pickB.length) {
      lines.push('▸ 관련 국회 법안');
      for (const x of pickB) {
        const b = x.row;
        const meta = [b.proposer, b.propose_dt ? '발의 ' + b.propose_dt : '', b.proc_result]
          .filter(Boolean).join(' / ');
        lines.push('  · ' + (b.bill_name || '') + (meta ? ' (' + meta + ')' : '') +
          (b.summary ? ': ' + String(b.summary).replace(/\s+/g, ' ').trim().slice(0, 200) : '') +
          (x.open ? '\n    ※ 국회 입법예고 의견등록 가능 — 마감 ' + b.notice_end_dt : ''));
      }
    }
    return '\n\n---\n\n[국회 동향 — 참고용 배경]\n' +
      '아래는 과방위 회의록(발언 요지)과 국회 법안 DB에서 이번 질문과 관련돼 보이는 항목을 추린 것입니다.\n' +
      '확정된 법령 내용이 아니라 "국회에서 이런 논의가 진행되고 있다"는 참고 배경입니다. ' +
      '답변의 근거는 위 조문·법령요약·기사를 우선하고, 이 블록은 필요할 때만 답변 말미에 짧게 덧붙이세요.\n\n' +
      lines.join('\n');
  } catch (e) { console.warn('국회 동향 컨텍스트 실패(건너뜀):', e); return ''; }
}

// sources = 검색돼 프롬프트에 들어간 **내부 자료 목록**(전부 답변에 반영됐다는 뜻이 아님).
// webSources = 모델이 본문에 실제 인용한 웹 문서(citations 기반) — 이쪽이 "진짜 근거"다.
// 표기할 때 두 목록의 성격 차이를 뭉개지 말 것 (2026-08-03 "참고가 전부 법령" 사고).
export interface AdvisoryResult { answer: string; sources: string[]; webSources: WebRef[] }

// ── 자문 실행 (진입점) ──
export async function answerAdvisory(sb: SupabaseClient, systemPrompt: string, question: string): Promise<AdvisoryResult> {
  const apiKey = env('ANTHROPIC_API_KEY');
  if (!apiKey) throw new Error('ANTHROPIC_API_KEY 미설정');

  // 6갈래를 동시에: 조문 RAG / 법령요약 / 조문 정밀검색(키워드) / 조문 의미검색 / 뉴스 동향 / 국회 동향(참고 배경)
  const kbP = searchKbSummaries(sb, question);
  const newsP = buildNewsContext(sb, question);
  const lawP = searchLawArticles(sb, question, 5);
  // 조문 **의미** 검색 (#89) — /law에는 있는데 자문에만 없던 갈래. 어휘가 어긋나면 키워드는 못 넘는다.
  // 실측(자문 경로): 「기지국 개설 허가 절차」의 키워드 5개는 해상무선통신망 제12조·전파관리 세칙
  // 제27조(민원)로 새고 정답인 전파법 21조(무선국 개설허가 등의 절차)를 못 찾았다. 「주파수 재할당
  // 대가 산정 기준」은 전파법 10·11·12·13·15조가 연번으로 자리를 채워 정작 「대가 산정」 조문
  // (세부사항 9조·시행령 14조·법 16조)이 하나도 없었다. 이 갈래가 셋 다 찾아온다.
  const lawSemP = getQueryEmbedding(expandQueryForSemantic(question)).then((emb) => emb
    ? sb.rpc('match_law_articles_semantic', { query_embedding: emb, match_threshold: 0.0, match_count: 8, only_current: true })
        .then((r) => (r.data || []) as Chunk[])
    : [] as Chunk[]).catch(() => [] as Chunk[]);
  const asmP = buildAssemblyTrendContext(sb, question);
  const chunks = await searchChunks(sb, apiKey, question);
  const [kb, news, lawHits, lawSem, asm] = [await kbP, await newsP, await lawP, await lawSemP, await asmP];

  // 조문 보강 — searchLawArticles(키워드 확장 + 조문 단위 필터)가 찾은 조문 중
  // 위 RAG에 안 들어온 것을 덧붙인다. RAG는 논문·보도자료도 섞여 정작 근거 조문을 놓치는 일이 있다.
  const have = new Set(chunks.map((c) => c.id));
  const extra = lawHits.filter((h) => !have.has(h.id));
  // 의미검색분을 뒤에 잇는다. 필터는 /law의 semExtra와 같게 유지 — **조문만**(별표·부칙·서식은
  // 이미 위 RAG가 훑는 대상이고, 별표는 통째로 길어 컨텍스트를 잡아먹는다), 파일 문서 제외.
  const seenArt = new Set(extra.map((h) => h.doc_name + '|' + (h.article_no || '')));
  extra.forEach((h) => have.add(h.id));
  for (const c of lawSem) {
    if (extra.length >= 10) break;                        // 키워드 5 + 의미 5 상한
    const key = c.doc_name + '|' + (c.article_no || '');
    if (!/^\d+조/.test(c.article_no || '')) continue;      // 조문만
    if (have.has(c.id) || seenArt.has(key)) continue;      // RAG·키워드분과 중복 제거
    if (/\.(pdf|md|docx|hwp)$/i.test(c.doc_name || '')) continue;
    have.add(c.id); seenArt.add(key);
    extra.push({ id: c.id, doc_name: c.doc_name, article_no: c.article_no, content: c.content, _hits: 0 } as LawHit);
  }
  const lawContext = extra.length
    ? '\n\n---\n\n[조문 정밀검색 결과 — 질문 의도에 직접 대응하는 조문]\n' +
      '위 RAG 결과에 없더라도 아래 조문이 질문의 핵심 근거일 가능성이 높습니다. 우선 확인하세요:\n\n' +
      extra.map((h, i) => `[조문 ${i + 1}] ${h.doc_name}${h.article_no ? ' ' + h.article_no : ''}\n${h.content}`).join('\n\n---\n\n')
    : '';

  // 별표 동반 인출(#90) — 조문이 「별표 N에 따른다」고 넘긴 그 표를 함께 싣는다.
  // 입력은 RAG + 조문 정밀검색분. RAG만 넘기면 조문 섹션에만 있는 조문(예: 전파법 시행령
  // 제14조 「별표 3에 따라 산정한다」)의 인용을 놓친다. chunks를 앞에 둬야 상한 2개가
  // 상위 RAG 조문에 먼저 돌아간다. app.js 호출부와 동일 유지 — 한쪽만 고치지 말 것.
  const annex = await buildAnnexContext(sb, (chunks as Chunk[]).concat(extra as unknown as Chunk[]), question);

  const telegramGuide = '\n\n---\n\n[텔레그램 답변 형식 지침]\n' +
    '이 답변은 텔레그램 메시지로 전송됩니다. 다음을 지키세요:\n' +
    '- 전체 3,000자 이내로 간결하게. 핵심 결론 먼저, 근거 조문 다음.\n' +
    '- 마크다운 표·코드블록 금지. 굵게(**)·불릿(-)·짧은 단락만 사용.\n' +
    // 별표는 괘선 문자(┌─┬─┐)로 그린 표다(실측 괘선 비율 39~44%). 텔레그램은 고정폭 폰트가
    // 아니라 그대로 옮기면 정렬이 무너져 읽을 수 없다. 위 「마크다운 표 금지」로는 안 걸린다.
    '- 별표의 표를 그대로 옮기지 마세요. 해당 항목의 값만 문장으로 인용하세요.\n' +
    '- 조항 인용 원칙(원문 확인됨/학습 데이터 기반 구분)은 그대로 유지.\n' +
    '- 웹 검색은 위 참조 자료에 없는 사실 확인에만 보조적으로 사용.\n' +
    '- 제도(조문)와 현재 추진 상황(기사)이 둘 다 관련되면 반드시 함께 답하세요. ' +
    '절차만 answer하고 최신 동향을 빠뜨리면 실무에 쓸 수 없습니다.';
  // ── 프롬프트 캐싱(Anthropic prompt caching): 텍스트는 기존 연결 순서 그대로, 캐시 표시만 추가 ──
  // 고정부(app_config.system_prompt + telegramGuide — 프롬프트 편집 전까지 불변)를 별도 블록으로
  // 분리해 cache_control:{type:'ephemeral'} 부착 → tools(web_search)+고정 지침이 함께 캐시된다.
  // 가변부(질문마다 바뀌는 RAG·조문·요약·뉴스)는 캐시 블록 '뒤'에 둬야 적중한다.
  const systemStable = systemPrompt + telegramGuide;
  // 국회 동향은 '근거'가 아니라 '배경'이라 맨 뒤 — 조문·요약·기사보다 앞에 두지 말 것
  const systemVariable = buildRagContext(chunks) + lawContext + annex.text + buildKbContext(kb) + news.text + asm;
  const system: SystemBlock[] = [
    { type: 'text', text: systemStable, cache_control: { type: 'ephemeral' } },
  ];
  if (systemVariable) system.push({ type: 'text', text: systemVariable }); // 빈 text 블록은 API가 거부

  const { text: answer, webRefs } = await callSonnet(apiKey, system, question);

  // 출처 순서: **조문 정밀검색분(extra)을 먼저** — 텔레그램 footer는 앞 6개만 보여주므로(#89),
  // RAG 15개를 먼저 채우면 정작 답변이 인용한 조문이 잘려 나간다. 실제로 「기지국 개설 허가 절차」
  // 답변이 전파법 제21조제2항을 [원문 확인됨]으로 인용했는데 출처에는 지방세법 시행령·논문·
  // 세미나 자료만 보였다 — 근거는 맞는데 어디서 왔는지 확인할 수가 없었다.
  // 별표는 조문 다음·RAG 앞 — 금액·요율을 물은 답변의 정본이 별표이므로 잘리면 안 된다(#90).
  const sources: string[] = [];
  for (const h of extra) if (h.doc_name && !sources.includes(h.doc_name)) sources.push(h.doc_name);
  for (const s of annex.sources) { const t = '[별표] ' + s; if (!sources.includes(t)) sources.push(t); }
  for (const c of chunks) if (c.doc_name && !sources.includes(c.doc_name)) sources.push(c.doc_name);
  for (const r of kb) { const t = '[요약] ' + (r.title || '').trim(); if (r.title && !sources.includes(t)) sources.push(t); }
  for (const s of news.sources) if (!sources.includes(s)) sources.push(s);
  return { answer, sources, webSources: webRefs };
}
