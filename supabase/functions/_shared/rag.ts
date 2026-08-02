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
  // 일반 가점·감점: 조문번호 있는 청크(법령·고시 원문) 가점, 파일 확장자 문서(논문·계획서류) 감점.
  // 크기 0.5/(K+1) = 목록 1개 1위 기여의 절반 — 논문이 조문을 이기려면 한 목록 상위만큼 더 필요.
  const FILE_DOC_RE = /\.(pdf|md|docx|hwp)$/i;
  for (const r of results) {
    if (r.article_no) r._hybrid_score = (r._hybrid_score || 0) + 0.5 / (RRF_K + 1);
    if (FILE_DOC_RE.test(r.doc_name || '')) r._hybrid_score = (r._hybrid_score || 0) - 0.5 / (RRF_K + 1);
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
async function callSonnet(apiKey: string, system: string | SystemBlock[], question: string): Promise<string> {
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
        } catch { /* keep-alive 등 무시 */ }
      }
    }
  }
  return text;
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
  return out;
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

export interface AdvisoryResult { answer: string; sources: string[] }

// ── 자문 실행 (진입점) ──
export async function answerAdvisory(sb: SupabaseClient, systemPrompt: string, question: string): Promise<AdvisoryResult> {
  const apiKey = env('ANTHROPIC_API_KEY');
  if (!apiKey) throw new Error('ANTHROPIC_API_KEY 미설정');

  // 4갈래를 동시에: 조문 RAG / 법령요약 / 조문 정밀검색(/law와 동일) / 뉴스 동향
  const kbP = searchKbSummaries(sb, question);
  const newsP = buildNewsContext(sb, question);
  const lawP = searchLawArticles(sb, question, 5);
  const chunks = await searchChunks(sb, apiKey, question);
  const [kb, news, lawHits] = [await kbP, await newsP, await lawP];

  // 조문 보강 — searchLawArticles(키워드 확장 + 조문 단위 필터)가 찾은 조문 중
  // 위 RAG에 안 들어온 것을 덧붙인다. RAG는 논문·보도자료도 섞여 정작 근거 조문을 놓치는 일이 있다.
  const have = new Set(chunks.map((c) => c.id));
  const extra = lawHits.filter((h) => !have.has(h.id));
  const lawContext = extra.length
    ? '\n\n---\n\n[조문 정밀검색 결과 — 질문 의도에 직접 대응하는 조문]\n' +
      '위 RAG 결과에 없더라도 아래 조문이 질문의 핵심 근거일 가능성이 높습니다. 우선 확인하세요:\n\n' +
      extra.map((h, i) => `[조문 ${i + 1}] ${h.doc_name}${h.article_no ? ' ' + h.article_no : ''}\n${h.content}`).join('\n\n---\n\n')
    : '';

  const telegramGuide = '\n\n---\n\n[텔레그램 답변 형식 지침]\n' +
    '이 답변은 텔레그램 메시지로 전송됩니다. 다음을 지키세요:\n' +
    '- 전체 3,000자 이내로 간결하게. 핵심 결론 먼저, 근거 조문 다음.\n' +
    '- 마크다운 표·코드블록 금지. 굵게(**)·불릿(-)·짧은 단락만 사용.\n' +
    '- 조항 인용 원칙(원문 확인됨/학습 데이터 기반 구분)은 그대로 유지.\n' +
    '- 웹 검색은 위 참조 자료에 없는 사실 확인에만 보조적으로 사용.\n' +
    '- 제도(조문)와 현재 추진 상황(기사)이 둘 다 관련되면 반드시 함께 답하세요. ' +
    '절차만 answer하고 최신 동향을 빠뜨리면 실무에 쓸 수 없습니다.';
  // ── 프롬프트 캐싱(Anthropic prompt caching): 텍스트는 기존 연결 순서 그대로, 캐시 표시만 추가 ──
  // 고정부(app_config.system_prompt + telegramGuide — 프롬프트 편집 전까지 불변)를 별도 블록으로
  // 분리해 cache_control:{type:'ephemeral'} 부착 → tools(web_search)+고정 지침이 함께 캐시된다.
  // 가변부(질문마다 바뀌는 RAG·조문·요약·뉴스)는 캐시 블록 '뒤'에 둬야 적중한다.
  const systemStable = systemPrompt + telegramGuide;
  const systemVariable = buildRagContext(chunks) + lawContext + buildKbContext(kb) + news.text;
  const system: SystemBlock[] = [
    { type: 'text', text: systemStable, cache_control: { type: 'ephemeral' } },
  ];
  if (systemVariable) system.push({ type: 'text', text: systemVariable }); // 빈 text 블록은 API가 거부

  const answer = await callSonnet(apiKey, system, question);

  const sources: string[] = [];
  for (const c of chunks) if (c.doc_name && !sources.includes(c.doc_name)) sources.push(c.doc_name);
  for (const h of extra) if (h.doc_name && !sources.includes(h.doc_name)) sources.push(h.doc_name);
  for (const r of kb) { const t = '[요약] ' + (r.title || '').trim(); if (r.title && !sources.includes(t)) sources.push(t); }
  for (const s of news.sources) if (!sources.includes(s)) sources.push(s);
  return { answer, sources };
}
