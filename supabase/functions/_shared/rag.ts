// ============================================================================
//  공용: AI 자문 RAG 파이프라인 (app.js 자문 경로의 서버판 — telegram-webhook에서 사용)
//
//  검색의 **순수 규칙**(키워드 추출·법령 어휘 대응표·제외어·RRF 융합·조문 정밀검색 순위·컨텍스트 문구·상한 상수)은
//  `_shared/rag_core.js` 한 파일에 있고 app.js와 이 파일이 같은 파일을 읽는다(#215, 2026-09-25, 개선안 §4-2-12 단계 A).
//  이 파일에는 DB 조회·Haiku 확장·임베딩·Sonnet 스트림·텔레그램 전용 지시(3,000자·5,000토큰)만 남는다.
//  규칙을 고치려면 rag_core.js를 고치고 이 함수(telegram-webhook)를 재배포. 여기서 같은 이름을 다시 정의하지 말 것
//  (tests/rag_core.test.js 구조 가드). 종전에는 '동일 유지' 주석으로만 지켰고 실제로 3곳이 갈라져 있었다(배경역사 #215).
//
//  키: ANTHROPIC_API_KEY·VOYAGE_API_KEY는 Edge Function Secrets에서만 읽는다.
//  app_config(claude_key, anon 노출)를 서버에서 재사용하지 말 것 — 지침 do-not.
// ============================================================================

import type { SupabaseClient } from 'jsr:@supabase/supabase-js@2';
// [원문 확인됨] 검증 모듈(#155) — 브라우저·node 테스트와 같은 파일을 쓰므로 globalThis로 받는다
import './cite_verify.js';
// 자문 검색의 순수 규칙(#215) — 브라우저·node 테스트와 같은 파일이라 역시 globalThis로 받는다
import './rag_core.js';
import { recordApiUsage, callHaikuText, mergeUsage, type ApiUsage } from './usage.ts';
// deno-lint-ignore no-explicit-any
const CiteVerify = (globalThis as any).CiteVerify;
// deno-lint-ignore no-explicit-any
const RagCore = (globalThis as any).RagCore;

const ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages';
const VOYAGE_URL = 'https://api.voyageai.com/v1/embeddings';

// env는 반드시 trim — 콘솔 붙여넣기로 들어간 줄바꿈이 API 키에 남으면 헤더가 깨진다
const env = (k: string) => (Deno.env.get(k) || '').trim();

// 회귀 하네스 전용 훅(#201, 2026-09-24) — tests/rag_regress_deno.ts가 Haiku 확장어·Voyage 임베딩을 고정 픽스처로
// 바꿔 끼워 Anthropic API 0회로 검색 경로를 재현한다. 운영 경로(Edge)는 아무도 설정하지 않으므로 비어 있다.
export const testHooks: {
  expand?: (query: string) => Promise<string[]>;
  embed?: (query: string, model: string) => Promise<number[] | null>;
} = {};

// 법령 검색용 키워드 추출(조사·어미 제거, 법령 명사 우선, 상한 5) — rag_core.js (#215)
const extractKeywords: (text: string) => string[] = RagCore.extractKeywords;

// ── Haiku 쿼리 확장 (실패 시 빈 배열 → 기본 키워드만) ──
async function expandQueryKeywords(apiKey: string, query: string, sb?: SupabaseClient): Promise<string[]> {
  if (testHooks.expand) return testHooks.expand(query);
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
    if (sb) await recordApiUsage(sb, 'rag.ts:expandQueryKeywords', 'claude-haiku-4-5-20251001', data.usage);
    const text = (data.content?.find((b: { type: string }) => b.type === 'text')?.text) || '';
    return text.split(',')
      .map((w: string) => w.trim().replace(/^["'\d.)\s]+|["'\s]+$/g, ''))
      .filter((w: string) => w.length >= 2 && w.length <= 25)
      .slice(0, 8);
  } catch (e) { console.warn('쿼리 확장 실패(기본 키워드로 진행):', e); return []; }
}

// ── Voyage 임베딩 (voyage-embed 함수와 동일 호출을 인라인 — 같은 프로젝트 Secret 사용) ──
async function getQueryEmbedding(query: string, model = 'voyage-4-lite'): Promise<number[] | null> {
  if (testHooks.embed) return testHooks.embed(query, model);
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
  id: number; doc_name: string; doc_category?: string; content: string; chunk_index?: number;
  notice_no?: string; article_no?: string; effective_date?: string;
  trgm_score?: number; similarity?: number;
  _score?: number; _trgm_score?: number; _semantic_score?: number; _hybrid_score?: number;
}

// 문서당 청크 상한(추가지식 8·그 외 3)·전체 상한 15는 rag_core.js rankChunks 안에서 적용된다 (#215)

// 검색 갈래별 기록(#203, 2026-09-24) — [{fn, ms, rows, error}]. buildAdvisoryContext가 배열을 만들어 각 검색
// 함수에 넘기고 answerAdvisory가 chat_logs.search_meta에 남긴다. 모듈 전역이 아니라 인자로 넘기는 이유:
// Edge isolate는 요청을 동시에 처리하므로 전역이면 두 자문의 기록이 섞인다. app.js metaRpc와 같은 형식.
export type SearchMeta = { fn: string; ms: number; rows: number | null; error: string | null }[];
type RpcResult = { data?: unknown; error?: { code?: string; message?: string } | null } | null;
function metaRpc(sb: SupabaseClient, meta: SearchMeta | undefined, fn: string, params: Record<string, unknown>) {
  const t0 = performance.now();
  const rec = (r: RpcResult, err?: unknown) => {
    if (!meta) return;
    meta.push({ fn, ms: Math.round(performance.now() - t0), rows: Array.isArray(r?.data) ? (r!.data as unknown[]).length : null,
      error: err ? String((err as Error).message || err) : (r?.error ? (r.error.code || r.error.message || 'error') : null) });
  };
  // Promise.resolve로 감싸 진짜 Promise를 돌려준다(PostgrestBuilder.then은 PromiseLike라 .catch 타입이 없다)
  return Promise.resolve(sb.rpc(fn, params) as unknown as PromiseLike<RpcResult>).then((r) => { rec(r); return r; }, (e: unknown) => { rec(null, e); throw e; });
}

// ── 3중 하이브리드 조문 검색 (app.js searchKeywords 이식, 상위 15개) ──
async function searchChunks(sb: SupabaseClient, apiKey: string, query: string, meta?: SearchMeta): Promise<Chunk[]> {
  const baseKeywords = extractKeywords(query);
  // trgm·시맨틱은 확장어를 쓰지 않으므로 Haiku 확장을 **기다리지 않고 먼저** 시작한다(B-2, #201, 2026-09-24).
  // trgm 5~6초(#185, SQL로는 못 줄임)와 임베딩 왕복이 확장 1~2초와 겹친다. 병합 순서는 아래에서 고정하므로 결과 동일.
  // only_current 명시 — 기본값에 기대면 status 필터 없는 오버로드로 조용히 해석될 수 있음(배경역사 #31 후속)
  const trgmP = metaRpc(sb, meta, 'search_chunks_trgm', { query_text: query, match_threshold: 0.12, match_count: 8, only_current: true })
    .then((r) => r?.data || []).catch(() => []);
  const semP = getQueryEmbedding(query).then((emb) => {
    if (!emb) return [];
    return metaRpc(sb, meta, 'match_chunks_semantic', { query_embedding: emb, match_threshold: 0.45, match_count: 8, only_current: true })
      .then((r) => r?.data || []).catch(() => []);
  });
  const expanded = await expandQueryKeywords(apiKey, query, sb);
  // 기본 → 법령 표제어(LAW_SYNONYMS) → LLM 확장 순 (app.js searchKeywords와 동일 유지)
  const keywords: string[] = [];
  const seenKw = new Set<string>();
  for (const w of baseKeywords.concat(lawSynonymKeywords(query)).concat(expanded)) {
    const norm = w.replace(/\s+/g, '').toLowerCase();
    if (norm.length >= 2 && !seenKw.has(norm)) { seenKw.add(norm); keywords.push(w); }
  }
  if (!keywords.length) return [];

  // 키워드 팬아웃은 RPC 1회 `search_chunks_keywords`(B-5, #208, 2026-09-24) — 종전 키워드당 document_chunks ilike limit 4를
  // 정렬 없이 따로 보냈다(≤10회, "그 단어가 든 아무 청크 4개"라 실행마다 달랐고 봇·대시보드가 갈렸다). 서버 선별 규칙(운영자 결정 (가)):
  // 질문 키워드를 많이 담은 청크 → 그 키워드가 조문 제목에 있는 청크 → 조문(제N조) → id, 앞 키워드가 집은 청크는 뒤 키워드가 다시
  // 집지 않는다(키워드당 새 청크 4건). 승인·current 필터는 RPC 안. 제외어(#173)는 조회하지 않는다('직접'은 1,470청크에 있어
  // 임의 청크를 데려온다) — 점수 계산에서는 그대로 센다. app.js searchKeywords와 동일 유지.
  const kwList = keywords.slice(0, 10).filter((kw) => !isTitleStop(kw, query));
  type KwRow = Chunk & { kw_ord?: number };
  const kwRows: KwRow[] = kwList.length
    ? await metaRpc(sb, meta, 'search_chunks_keywords', { p_keywords: kwList, p_per_kw: 4 })
        .then((r) => (r?.data || []) as KwRow[]).catch(() => [] as KwRow[])
    : [];

  const seen = new Set<number>();
  const results: Chunk[] = [];
  for (const row of kwRows) {   // 키워드 순 → 순위 순으로 정렬돼 온다
    delete row.kw_ord;
    if (!seen.has(row.id)) { seen.add(row.id); results.push(row); }
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

  // ── RRF 융합·조문 종류별 가점·문서당 상한 — rag_core.js rankChunks (#215, app.js와 같은 함수) ──
  return RagCore.rankChunks(results, keywords, baseKeywords, query) as Chunk[];
}

// ── kb 요약 검색 (app.js searchKbSummaries 이식: trgm×5 + 시맨틱(law-2)×10 융합, 상위 5) ──
interface KbRow { doc_id: string; chunk_idx: number; title?: string; content?: string; law_type?: string; law_number?: string; enforcement_date?: string; trgm_score?: number; similarity?: number; _score?: number; }
async function searchKbSummaries(sb: SupabaseClient, query: string, meta?: SearchMeta): Promise<KbRow[]> {
  try {
    const trgmP = metaRpc(sb, meta, 'search_kb_chunks_trgm', { query_text: query, match_threshold: 0.10, match_count: 6, only_current: true })
      .then((r) => r?.data || []).catch(() => []);
    const semP = getQueryEmbedding(query, 'voyage-law-2').then((emb) => {
      if (!emb) return [];
      return metaRpc(sb, meta, 'match_kb_chunks_semantic', { query_embedding: emb, match_threshold: 0.35, match_count: 6, only_current: true })
        .then((r) => r?.data || []).catch(() => []);
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
const buildRagContext: (chunks: Chunk[]) => string = RagCore.buildRagContext;   // 조문 참조 블록 문구 — rag_core.js (#215)
// ── 별표 동반 인출 (app.js buildAnnexContext 이식 — #90) ─────────────────────
// 법령 조문은 실제 숫자를 안 담고 별표로 넘긴다: 전파법 시행령 제14조는 "별표 3에 따라
// 산정한다"고만 하고 산식은 별표 3에 있다. 조문만 근거로 주면 봇은 「별표 3에 따라
// 산정합니다」로 끝나고 정작 물어본 금액·요율·기준을 답하지 못한다.
// 대시보드에는 이 경로가 있었는데(315개 별표가 이 경로로 닿는다) **봇에는 아예 없었다.**
// app.js와 동일 유지 — 한쪽만 고치지 말 것. 상한 값도 같게 둔다.
const ANNEX_MAX_UNITS: number = RagCore.ANNEX_MAX_UNITS;     // 질문당 별표 개수 — rag_core.js
const ANNEX_MAX_CHUNKS: number = RagCore.ANNEX_MAX_CHUNKS;   // 별표당 청크 — rag_core.js

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

const buildKbContext: (rows: KbRow[]) => string = RagCore.buildKbContext;   // 법령요약 블록 문구 — rag_core.js (#215)

// ── Sonnet 호출: 스트리밍으로 받아 서버에서 누적 ──
// (스트리밍 유지 이유: 비스트리밍 회귀 금지 가드레일과 일관 + Sonnet5 적응형 추론의
//  content[0]=thinking 함정 회피 — 스트림에서는 text_delta만 골라 누적하면 안전)
// system은 문자열 또는 블록 배열을 그대로 API에 전달 (블록 배열 = 프롬프트 캐싱용, answerAdvisory 참조)
type SystemBlock = { type: 'text'; text: string; cache_control?: { type: 'ephemeral' } };
// 웹 검색 인용 — 스트림의 citations_delta에서 수집한 실제 근거 URL.
// (2026-08-03 이전에는 text_delta만 담고 인용을 버려서, 웹에서 온 수치·현황의 출처가
//  어디에도 안 남았다 — footer에는 내부 RAG 문서명만 나열돼 "참고가 전부 법령" 사고.)
export interface WebRef { url: string; title: string }
// 스트림 절단 보호(#205, B-7): 무수신 3분이면 끊고, 끊겨도 받은 부분은 돌려준다(cut에 사유). stopReason·sawStop은 호출측이 경고를 붙이는 재료.
const STREAM_IDLE_MS: number = RagCore.STREAM_IDLE_MS;   // 3분 — rag_core.js
async function callSonnet(apiKey: string, system: string | SystemBlock[], question: string): Promise<{ text: string; webRefs: WebRef[]; usage: ApiUsage; stopReason: string | null; sawStop: boolean; cut: string | null }> {
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
  let usage: ApiUsage = {};   // message_start(입력·캐시) + message_delta(출력 누계) — 비용 기록용(#155)
  const webRefs: WebRef[] = [];
  const seenUrls = new Set<string>();
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let stopReason: string | null = null;
  let sawStop = false;
  let cut: string | null = null;
  let idleTimer: ReturnType<typeof setTimeout> | undefined;
  try {
  while (true) {
    // 무수신 감시 — 토큰·ping이 3분간 하나도 안 오면 연결이 죽은 것으로 보고 끊는다(전체 소요 시간과 무관, #205)
    const { done, value } = await Promise.race([
      reader.read(),
      new Promise<never>((_, rej) => { idleTimer = setTimeout(() => rej(new Error('IDLE_TIMEOUT')), STREAM_IDLE_MS); }),
    ]);
    clearTimeout(idleTimer);
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
          // 웹검색 전후의 text 블록이 붙어 "…검색하겠습니다.# 분석:"이 되지 않게 블록 사이에 빈 줄 (app.js와 동일)
          else if (d.type === 'content_block_start' && d.content_block?.type === 'text' && text && !/\n\s*$/.test(text)) text += '\n\n';
          else if (d.type === 'message_start' && d.message?.usage) usage = mergeUsage(usage, d.message.usage);
          else if (d.type === 'message_delta') {
            if (d.usage) usage = mergeUsage(usage, d.usage);
            if (d.delta?.stop_reason) stopReason = d.delta.stop_reason;   // max_tokens 잘림 표시 재료(#205)
          }
          else if (d.type === 'message_stop') sawStop = true;              // 끝 신호 — 없이 멈추면 잘린 것(#205)
        } catch { /* keep-alive 등 무시 */ }
      }
    }
  }
  } catch (e) {
    clearTimeout(idleTimer);
    try { await reader.cancel(); } catch { /* 이미 닫힘 */ }
    if (!text.trim()) throw e;   // 받은 게 없으면 종전대로 실패
    cut = (e as Error)?.message === 'IDLE_TIMEOUT'
      ? `서버에서 ${Math.round(STREAM_IDLE_MS / 1000)}초 동안 아무 응답이 없어 수신을 중단`
      : `수신 중 연결이 끊김 (${String((e as Error)?.message ?? e).slice(0, 80)})`;
    console.warn('[callSonnet] 스트림 절단 — 받은 부분 보존:', cut);
  }
  return { text, webRefs, usage, stopReason, sawStop, cut };
}

// ── 인용 조문 통째 보강(#155-1안)에 쓰는 조각 조회 — verify-citations·app.js fetchArticleChunks와 동일 조건 ──
const EXPAND_OPTS = RagCore.EXPAND_OPTS;   // app.js CITE_EXPAND_OPTS와 같은 객체 — rag_core.js
async function fetchArticleChunks(sb: SupabaseClient, docName: string, key: string): Promise<Chunk[]> {
  const r = await sb.from('document_chunks').select('id, doc_name, article_no, chunk_index, content')
    .eq('doc_name', docName).eq('status', 'current').eq('is_approved', true)
    .like('article_no', key + '%').order('chunk_index', { ascending: true }).limit(40);
  return (r.data || []) as Chunk[];
}
// ── 번호로 지목한 조문(#245)의 이름 맞추기 재료 — 그 번호의 조문을 가진 현행 문서(조문 제목은 'N조(제목)', #92).
//    '16조%'면 16조의2 등도 오지만 rag_core.js pickNamedArticles가 번호를 다시 대조한다. app.js fetchArticleKeyRows와 동일 조건.
async function fetchArticleKeyRows(sb: SupabaseClient, key: string): Promise<{ doc_name: string; article_no: string }[]> {
  const r = await sb.from('document_chunks').select('doc_name, article_no')
    .eq('status', 'current').eq('is_approved', true)
    .like('article_no', key + '%').order('id', { ascending: true }).limit(1000);
  return (r.data || []) as { doc_name: string; article_no: string }[];
}
// ── 역참조 발췌(#155-보론4)에 쓰는 조회 — 같은 문서에서 '제<key>'를 본문에 담은 조문 조각. app.js fetchCitingChunks와 동일 조건 ──
const CITING_OPTS = RagCore.CITING_OPTS;
async function fetchCitingChunks(sb: SupabaseClient, docName: string, key: string): Promise<Chunk[]> {
  const r = await sb.from('document_chunks').select('id, doc_name, article_no, chunk_index, content')
    .eq('doc_name', docName).eq('status', 'current').eq('is_approved', true)
    .not('article_no', 'is', null).like('content', '%제' + key + '%')
    .order('chunk_index', { ascending: true }).limit(30);
  return (r.data || []) as Chunk[];
}

// ── /law 키워드 검색 전용 (LLM 답변 없이 조문만 찾아 준다) ──
// 실측(2026-08-01): "3G 종료를 하는 방법"에 trgm 단독은 흔한 단어 '방법'에 끌려 개인정보·위치정보
// 시행령만 반환하고, 시맨틱을 더해도 못 잡는다(질문 어휘 "3G 종료" ≠ 법령 어휘 "휴지·폐지").
// ① Haiku 확장으로 어휘 간극을 메우고 ② 조문번호 있는 청크만 봐서 논문·보도자료를 배제하면
// 최상위가 '전파법 25조의2(무선국의 폐지 및 운용 휴지)'로 정확히 잡힌다.
// (article_no로 거르는 이유: doc_category '기타'에 고시와 박사논문이 섞여 카테고리로는 못 거른다)
export interface LawHit { id: number; doc_name: string; article_no?: string; content: string; chunk_index?: number; _hits: number }

// 법령 어휘 대응표(LAW_SYNONYMS·PRACTICE_TERMS)·제외어(QUERY_TITLE_STOP)·법령 위계·도메인 사전확률 — 전부 rag_core.js (#215).
// 아래는 이 파일이 직접 부르는 것만 이름을 붙인다. 표 자체는 여기 없다.
const lawSynonymKeywords: (query: string) => string[] = RagCore.lawSynonymKeywords;
/** 의미 검색용 질의 — 실무 용어가 있으면 법령 용어를 덧붙인다. 없으면 원문 그대로. (rag_core.js) */
export const expandQueryForSemantic: (query: string) => string = RagCore.expandQueryForSemantic;
const isTitleStop: (kw: string, query: string) => boolean = RagCore.isTitleStop;
const lawRank: (docName: string | undefined) => number = RagCore.lawRank;

export async function searchLawArticles(sb: SupabaseClient, query: string, limit = 5, meta?: SearchMeta): Promise<LawHit[]> {
  const apiKey = env('ANTHROPIC_API_KEY');
  const base = extractKeywords(query);
  const expanded = apiKey ? await expandQueryKeywords(apiKey, query, sb) : [];   // 키 없으면 기본 키워드만(페일소프트)

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

  // 조회는 RPC 1회 `search_law_articles_kw`(B-5, #208, 2026-09-24) — 종전 키워드당 (제목 ilike 40 + 본문 ilike 10) ≤20회.
  // 서버가 제목 적중·본문 적중을 hit_col로 구분해 돌려준다. .pdf/.md 등 파일 문서 제외('실행계획(안).pdf'도 '6조'라는
  // article_no를 갖고 있어 조문번호 유무만으로는 못 거른다)와 article_no NOT NULL·승인·current 필터는 RPC 안에 있다.
  // 선별 규칙(운영자 결정 (가)): 제목 적중은 제목에 담긴 질문 키워드 수 → 본문 키워드 수 → id, 본문 적중은 그 반대.

  // 점수는 '행위'와 '주제'를 분리해 매긴다(실측으로 도달한 구조).
  //   행위 = 폐업·휴지 같은 조문 표제어 → 조문 제목에 걸리면 결정적(×5)
  //   주제 = 기간통신사업·무선국 같은 대상 → 문서명·조문제목에 걸리면 가산
  // 둘을 합치지 않고 나누는 이유: 주제만 맞는 문서(기간통신사업 양수·합병 고시)가
  // 행위가 맞는 조문(전기통신사업법 19조 사업의 휴업·폐업)을 밀어내는 일이 있었다.
  //
  // ★ 상한 40·10은 그대로(#51): 40으로 받아야 '폐업'에서 전기통신사업법 19조가 빠지지 않았다
  //   (종전 정렬 없는 조회 실측 — limit 6에서 누락, 40에서 포함. 위치정보법·지방세법이 자리를 채웠다).
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
  // 제외어(#173) 뺀 조회 키워드 + 행위 가중(사전 출신 7·그 외 5) — rag_core.js titleActWeights
  const { kwActive, actOf }: { kwActive: string[]; actOf: number[] } = RagCore.titleActWeights(keywords, query);
  type LawRow = { kw_ord: number; hit_col: string; id: number; doc_name: string; article_no?: string; content: string };
  const lawRows: LawRow[] = kwActive.length
    ? await metaRpc(sb, meta, 'search_law_articles_kw', { p_keywords: kwActive, p_title_limit: 40, p_content_limit: 10 })
        .then((r) => (r?.data || []) as LawRow[]).catch(() => [] as LawRow[])
    : [];
  // 반환 순서(키워드 → 제목 적중 → 본문 적중 → 순위)대로 넣는다 — 같은 조문의 대표 청크가 실행마다 같아진다
  for (const r of lawRows) {
    put({ id: r.id, doc_name: r.doc_name, article_no: r.article_no, content: r.content, _hits: 0 }, r.hit_col === 'title' ? actOf[r.kw_ord - 1] : 0);
  }

  // 주제 점수(부분문자열)·정렬(점수→법령 위계→문서명·조문번호)·같은 조문 대표 1건·상한 — rag_core.js rankLawHits (#215)
  return RagCore.rankLawHits(acc.values(), query, limit) as LawHit[];
}

// ── /law 자연어 모드 — 법령 한정 답변 (2026-08-03) ──
// "궁금한 사항이 어떤 법과 관련돼 있는지"가 팀의 실제 질문 형태(운영자)라, 조문번호 즉답과
// 별개로 자연어 질의를 받는다. /ask와의 경계: **법령 내용만** — 뉴스·국회동향·웹검색·시사점을
// 넣지 않는다(그건 /ask의 몫). 그래서 answerAdvisory를 재사용하지 않고 조문 검색 + 요약층만
// 모아 Haiku(법령 나열·관련 이유 설명은 좁은 일이라 Sonnet 불필요, 건당 ~$0.01)로 답한다.
// 반환에 chunkIds를 함께 실어 보낸다 — 호출자(telegram-webhook)가 chat_logs에 근거를 남겨
// 만족도 👎 분석 때 "어느 조문을 집었길래 틀렸나"를 되짚을 수 있게 한다(2026-08-20).
export async function answerLawQuery(sb: SupabaseClient, query: string): Promise<{ answer: string; chunkIds: number[] } | null> {
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
    // 8→12 (2026-08-07): "3G 종료"처럼 한 질문이 여러 제도(사업 폐업·무선국 폐지·주파수 회수)에
    // 걸치면 8자리를 계열끼리 다퉈 시행령 조문이 밀려났다(실측 — 시행령 24조·51조 누락).
    searchLawArticles(sb, query, 12),
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
    '- 관련도 높은 순으로 3~8개 항목. 각 항목은 **법령명 제N조(제목)** 한 줄 + 그 조문이 **무엇을 규정하는지 2~3문장 요약**(누가·무엇을·어떤 기한/요건으로 — 승인·신고·보상 같은 핵심 요건과 숫자를 포함) + 이 질문과 어떻게 연결되는지 한 줄. 조문 핵심 문구는 짧게 직접 인용. 제목 한 줄만 쓰고 넘어가지 마세요.\n' +
    '- 질문 하나가 여러 제도에 걸치면(예: 서비스 종료 = 사업 휴업·폐업 + 무선국 폐지·휴지 + 주파수 회수·할당취소) **제도 영역별로 묶어** 각 영역의 관련 조문을 빠짐없이 제시하세요. 한 영역만 답하고 끝내면 안 됩니다.\n' +
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
  const data = await res.json() as { content?: { type: string; text?: string }[]; usage?: ApiUsage };
  await recordApiUsage(sb, 'rag.ts:answerLawQuery', 'claude-haiku-4-5-20251001', data.usage);
  // content[0]이 text가 아닐 수 있으므로 find로 고른다 (Sonnet5 적응형 추론에서 실제로 겪은 함정 — Haiku도 같은 방어)
  const text = (data.content || []).find((b) => b.type === 'text')?.text || '';
  if (!text.trim()) return null;
  const chunkIds: number[] = [];
  for (const h of merged) if (typeof h.id === 'number' && !chunkIds.includes(h.id)) chunkIds.push(h.id);
  return { answer: text.trim(), chunkIds };
}

// ── 뉴스 컨텍스트 (app.js fetchRecentNewsContext 이식) ──
// 조문만 보면 "휴지·폐지 절차는 이렇다"에서 끝난다. "3G 종료" 질문의 답 절반은
// 정부가 이용자 보호로 신중하고 IoT 회선이 변수라는 최신 동향이고, 그건 news_feed에 있다.
// 키워드 추출은 법령용(extractKeywords)과 분리 — 법령 불용어를 쓰면 '통신사·영향' 같은
// 저변별력 단어가 살아남아 엉뚱한 기사를 끌어온다(app.js와 동일 원칙).
const extractNewsKeywords: (text: string) => string[] = RagCore.extractNewsKeywords;   // 뉴스 전용 키워드(법령용과 분리) — rag_core.js

interface NewsRow { title: string; source?: string; published_at?: string; content?: string }

async function buildNewsContext(sb: SupabaseClient, query: string, meta?: SearchMeta): Promise<{ text: string; sources: string[] }> {
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
      const t0n = performance.now();
      const note = (fn: string, r: RpcResult) => { if (meta) meta.push({ fn, ms: Math.round(performance.now() - t0n), rows: Array.isArray(r?.data) ? (r!.data as unknown[]).length : null, error: r?.error ? (r.error.code || r.error.message || 'error') : null }); };
      qs.push(sb.from('news_feed').select('title, source, published_at, content')
        .or('published_at.gte.' + cutoff + ',locked.eq.true')
        .ilike('title', '%' + esc + '%').order('published_at', { ascending: false }).limit(10)
        .then((r) => { note('news_title_ilike', r); return { w: 3, rows: (r.data || []) as NewsRow[] }; }).catch(() => ({ w: 3, rows: [] as NewsRow[] })));
      qs.push(sb.from('news_feed').select('title, source, published_at, content')
        .or('published_at.gte.' + cutoff + ',locked.eq.true')
        .ilike('content', '%' + esc + '%').not('content', 'is', null)
        .order('published_at', { ascending: false }).limit(10)
        .then((r) => { note('news_content_ilike', r); return { w: 1, rows: (r.data || []) as NewsRow[] }; }).catch(() => ({ w: 1, rows: [] as NewsRow[] })));
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
const ASM_RARE_MAX: number = RagCore.ASM_RARE_MAX;   // 국회 발언 희소어 상한 — rag_core.js

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
// chunkIds = 프롬프트에 들어간 청크의 document_chunks.id. 만족도 👎를 받았을 때
// "그때 무엇을 근거로 답했나"를 되짚으려면 문서명(sources)만으로는 부족하다 — 같은 법령에서
// 어느 조문이 걸렸는지가 검색 품질의 실제 단서다.
export interface AdvisoryResult { answer: string; sources: string[]; webSources: WebRef[]; chunkIds: number[]; verdicts: unknown[]; searchMeta: SearchMeta }

// ── 자문 실행 (진입점) ──
// 자문 컨텍스트(검색·보강 단계)의 산출물 — answerAdvisory가 이걸로 프롬프트를 조립한다.
export interface AdvisoryContext {
  chunks: Chunk[]; extra: LawHit[]; addedIds: number[];
  annex: { text: string; sources: string[] }; citing: { text: string; chunks: Chunk[]; ids: number[] };
  kb: KbRow[]; news: { text: string; sources: string[] }; asm: string; lawContext: string; systemVariable: string;
  searchMeta: SearchMeta;   // 검색 갈래별 기록(#203)
}

// ── 자문 컨텍스트 조립(검색·보강 단계) — answerAdvisory에서 분리(#201, 2026-09-24 B-2).
//    Sonnet 호출 없이 검색·통째 보강·역참조·별표·요약·뉴스 조각만 만든다. 회귀 하네스
//    (tests/rag_regress_deno.ts)가 testHooks로 확장어·임베딩을 고정해 API 0회로 돌리고 단계별 청크 id를 대조한다.
//    조립 순서·내용은 answerAdvisory 안에 있던 그대로 — 여기서 순서를 바꾸면 app.js buildAdvisoryContext도 같이.
export async function buildAdvisoryContext(sb: SupabaseClient, question: string): Promise<AdvisoryContext> {
  const apiKey = env('ANTHROPIC_API_KEY');
  const meta: SearchMeta = [];   // 검색 갈래별 기록 시작(#203)

  // 6갈래를 동시에: 조문 RAG / 법령요약 / 조문 정밀검색(키워드) / 조문 의미검색 / 뉴스 동향 / 국회 동향(참고 배경)
  const kbP = searchKbSummaries(sb, question, meta);
  const newsP = buildNewsContext(sb, question, meta);
  const lawP = searchLawArticles(sb, question, 5, meta);
  // 조문 **의미** 검색 (#89) — /law에는 있는데 자문에만 없던 갈래. 어휘가 어긋나면 키워드는 못 넘는다.
  // 실측(자문 경로): 「기지국 개설 허가 절차」의 키워드 5개는 해상무선통신망 제12조·전파관리 세칙
  // 제27조(민원)로 새고 정답인 전파법 21조(무선국 개설허가 등의 절차)를 못 찾았다. 「주파수 재할당
  // 대가 산정 기준」은 전파법 10·11·12·13·15조가 연번으로 자리를 채워 정작 「대가 산정」 조문
  // (세부사항 9조·시행령 14조·법 16조)이 하나도 없었다. 이 갈래가 셋 다 찾아온다.
  const lawSemP = getQueryEmbedding(expandQueryForSemantic(question)).then((emb) => emb
    ? metaRpc(sb, meta, 'match_law_articles_semantic', { query_embedding: emb, match_threshold: 0.0, match_count: 8, only_current: true })
        .then((r) => (r?.data || []) as Chunk[])
    : [] as Chunk[]).catch(() => [] as Chunk[]);
  const asmP = buildAssemblyTrendContext(sb, question);
  // 번호로 지목한 조문 직접 인출(#245) — 「전파법 제16조」를 이름과 번호로 바로 가져온다(검색 순위와 무관). 규칙은 rag_core.js.
  // search_meta에는 질문에 조 언급이 있을 때만 남긴다(rows 0 = 이름을 못 맞췄거나 그 조문이 KB에 없음).
  const namedT0 = performance.now(), namedRefs = RagCore.namedArticleRefs(question).length;
  const namedP: Promise<Chunk[]> = RagCore.fetchNamedArticles(question, (k: string) => fetchArticleKeyRows(sb, k), (d: string, k: string) => fetchArticleChunks(sb, d, k))
    .then((rows: Chunk[]) => { if (namedRefs) meta.push({ fn: 'named_articles', ms: Math.round(performance.now() - namedT0), rows: rows.length, error: null }); return rows; })
    .catch((e: unknown) => { meta.push({ fn: 'named_articles', ms: Math.round(performance.now() - namedT0), rows: null, error: String((e as Error)?.message || e) }); return [] as Chunk[]; });
  const chunks = await searchChunks(sb, apiKey, question, meta);
  const [kb, news, lawHits, lawSem, asm, named] = [await kbP, await newsP, await lawP, await lawSemP, await asmP, await namedP];

  // 조문 보강 — searchLawArticles(키워드 확장 + 조문 단위 필터)가 찾은 조문 중
  // 위 RAG에 안 들어온 것을 덧붙인다. RAG는 논문·보도자료도 섞여 정작 근거 조문을 놓치는 일이 있다.
  // 번호로 지목한 조문(#245)을 맨 앞에 — RAG에 이미 든 조각은 빼고(같은 조의 나머지 조각은 아래 통째 보강이 한 덩어리로 합친다).
  // 키워드 5 + 의미 5 상한은 그 뒤에 그대로 둔다(지목 조문이 그 칸을 먹지 않게).
  const have = new Set(chunks.map((c) => c.id));
  const namedHits = named.filter((c) => !have.has(c.id)).map((c) => ({ id: c.id, doc_name: c.doc_name, article_no: c.article_no, content: c.content, chunk_index: c.chunk_index, _hits: 0 }) as LawHit);
  namedHits.forEach((h) => have.add(h.id));
  const extra = namedHits.concat(lawHits.filter((h) => !have.has(h.id)));
  // 의미검색분을 뒤에 잇는다. 필터는 /law의 semExtra와 같게 유지 — **조문만**(별표·부칙·서식은
  // 이미 위 RAG가 훑는 대상이고, 별표는 통째로 길어 컨텍스트를 잡아먹는다), 파일 문서 제외.
  const seenArt = new Set(extra.map((h) => h.doc_name + '|' + (h.article_no || '')));
  extra.forEach((h) => have.add(h.id));
  for (const c of lawSem) {
    if (extra.length >= 10 + namedHits.length) break;     // 키워드 5 + 의미 5 상한(지목 조문은 별도)
    const key = c.doc_name + '|' + (c.article_no || '');
    if (!/^\d+조/.test(c.article_no || '')) continue;      // 조문만
    if (have.has(c.id) || seenArt.has(key)) continue;      // RAG·키워드분과 중복 제거
    if (/\.(pdf|md|docx|hwp)$/i.test(c.doc_name || '')) continue;
    have.add(c.id); seenArt.add(key);
    extra.push({ id: c.id, doc_name: c.doc_name, article_no: c.article_no, content: c.content, _hits: 0 } as LawHit);
  }
  // 인용 조문 통째 보강(#155-1안) — 검색이 조문의 한 조각만 집으면 나머지 조각을 붙여 조문 전체를 준다.
  // 9/10 사고: 제50조는 뒷조각(8호~③)만 들어갔고, 모델은 ②에 적힌 "제1항제5호 및 제5호의2" 문구만 보고
  // 5호·5호의2의 내용을 옛 지식으로 쓰면서 [원문 확인됨]을 붙였다. 정밀검색분(extra)을 앞에 둬 보강 예산이
  // 근거 조문에 먼저 간다. 실패하면 검색 결과 그대로 진행. app.js callClaude와 동일 유지 — 한쪽만 고치지 말 것.
  let extra2: LawHit[] = extra, chunks2: Chunk[] = chunks, addedIds: number[] = [];
  try {
    const tagged = (extra as unknown as Chunk[]).map((h) => ({ ...h, _src: 'extra' }))
      .concat(chunks.map((c) => ({ ...c, _src: 'rag' })));
    const ex = await CiteVerify.expandArticles(tagged, (d: string, k: string) => fetchArticleChunks(sb, d, k), EXPAND_OPTS);
    type Tagged = Chunk & { _src: string };
    extra2 = (ex.chunks as Tagged[]).filter((c) => c._src === 'extra') as unknown as LawHit[];
    chunks2 = (ex.chunks as Tagged[]).filter((c) => c._src === 'rag');
    addedIds = ex.addedIds as number[];
    if (ex.expanded) console.log(`[조문 보강] ${ex.expanded}개 조문 통째(조각 +${addedIds.length})`);
  } catch (e) { console.warn('조문 보강 실패(검색 결과 그대로 진행):', e); }
  const lawContext = extra2.length
    ? '\n\n---\n\n[조문 정밀검색 결과 — 질문 의도에 직접 대응하는 조문]\n' +
      '위 RAG 결과에 없더라도 아래 조문이 질문의 핵심 근거일 가능성이 높습니다. 우선 확인하세요:\n\n' +
      extra2.map((h, i) => `[조문 ${i + 1}] ${h.doc_name}${h.article_no ? ' ' + h.article_no : ''}\n${h.content}`).join('\n\n---\n\n')
    : '';

  // 별표 동반 인출(#90) — 조문이 「별표 N에 따른다」고 넘긴 그 표를 함께 싣는다.
  // 입력은 RAG + 조문 정밀검색분. RAG만 넘기면 조문 섹션에만 있는 조문(예: 전파법 시행령
  // 제14조 「별표 3에 따라 산정한다」)의 인용을 놓친다. chunks를 앞에 둬야 상한 2개가
  // 상위 RAG 조문에 먼저 돌아간다. app.js 호출부와 동일 유지 — 한쪽만 고치지 말 것.
  // 별표와 역참조는 둘 다 '보강이 끝난 chunks2·extra2'만 읽고 서로 독립이라 **동시에 시작**한다(B-2, #201).
  // 종전에는 한 건씩 await라 각각의 DB 왕복이 줄줄이 더해졌다. 프롬프트 조립 순서는 아래에서 그대로 고정. app.js와 동일 유지.
  const annexP = buildAnnexContext(sb, chunks2.concat(extra2 as unknown as Chunk[]), question);

  // 역참조 발췌(#155-보론4) — 검색된 조문을 인용하는 같은 법령의 다른 조문(제재·조사·준용)에서 인용 문장만.
  // 「대리점·판매점 관리」 질문에 제20조(등록취소 사유)·제51조(조사 대상)는 질문 어휘로 검색되지 않지만
  // "제32조의4제5항에 따른 …"처럼 검색된 조문을 가리키므로 이 경로로 닿는다. app.js와 동일 유지.
  // 제재 조문(벌칙·과태료·과징금)은 별도 칸으로 먼저 싣고, 금액이 적힌 항 머리 문장을 찾으려 그 조문 전체를 읽는다(fetchArticle, #230).
  const emptyCiting: { text: string; chunks: Chunk[]; ids: number[]; sanctions?: number } = { text: '', chunks: [], ids: [], sanctions: 0 };
  const citingP: Promise<{ text: string; chunks: Chunk[]; ids: number[]; sanctions?: number }> = Promise.resolve()
    .then(() => CiteVerify.buildCitingExcerpts((extra2 as unknown as Chunk[]).concat(chunks2), (d: string, k: string) => fetchCitingChunks(sb, d, k),
      { ...CITING_OPTS, fetchArticle: (d: string, k: string) => fetchArticleChunks(sb, d, k) }))
    .catch((e: unknown) => { console.warn('역참조 발췌 실패(건너뜀):', e); return emptyCiting; });
  const annex = await annexP;
  const citing = await citingP;
  if (citing.chunks.length) console.log(`[역참조 발췌] ${citing.chunks.length}건(제재 ${citing.sanctions || 0})`);

  // 국회 동향은 '근거'가 아니라 '배경'이라 맨 뒤 — 조문·요약·기사보다 앞에 두지 말 것
  const systemVariable = buildRagContext(chunks2) + lawContext + citing.text + annex.text + buildKbContext(kb) + news.text + asm;
  return { chunks: chunks2, extra: extra2, addedIds, annex, citing, kb, news, asm, lawContext, systemVariable, searchMeta: meta };
}

export async function answerAdvisory(sb: SupabaseClient, systemPrompt: string, question: string): Promise<AdvisoryResult> {
  const apiKey = env('ANTHROPIC_API_KEY');
  if (!apiKey) throw new Error('ANTHROPIC_API_KEY 미설정');
  const { chunks: chunks2, extra: extra2, addedIds, annex, citing, kb, news, systemVariable, searchMeta } = await buildAdvisoryContext(sb, question);

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
  const system: SystemBlock[] = [
    { type: 'text', text: systemStable, cache_control: { type: 'ephemeral' } },
  ];
  if (systemVariable) system.push({ type: 'text', text: systemVariable }); // 빈 text 블록은 API가 거부

  const sonnet = await callSonnet(apiKey, system, question);
  const { webRefs, usage } = sonnet;
  let rawAnswer = sonnet.text;
  await recordApiUsage(sb, 'rag.ts:callSonnet', 'claude-sonnet-5', usage);
  // 잘린 답이 정상인 척하지 않게 표시(#205, B-7). 세 경우: 연결 절단 / 길이 상한(max_tokens 5000) / 끝 신호 없이 멈춤.
  if (sonnet.cut) rawAnswer += `\n\n⚠️ 답변이 도중에 끊겼습니다 — ${sonnet.cut}. 위 내용은 받은 부분까지입니다.`;
  else if (sonnet.stopReason === 'max_tokens') rawAnswer += '\n\n…(길이 제한으로 잘림 — 질문을 좁혀 다시 물어보세요)';
  else if (!sonnet.sawStop) rawAnswer += '\n\n⚠️ 답변 수신이 끝 신호 없이 멈췄습니다(잘렸을 수 있음).';

  // [원문 확인됨] 검증(#155-2·3안) — 표시가 붙은 인용의 조문(법령명·조·항·호·별표)이 실제로 위 컨텍스트에
  // 있었는지 대조하고(2안), 있었으면 Haiku가 원문과 설명이 맞는지 판정한다(3안). 없으면 「⚠️ 원문 미확인」,
  // 다르면 「⚠️ 원문과 다르게 설명됨」으로 표시를 바꾼다. 시스템 프롬프트의 핵심 조문 5개도 대조 대상.
  // 검증 자체가 실패하면 답변은 그대로 나간다(fail-open). 대시보드는 verify-citations Edge가 같은 모듈을 쓴다.
  let answer = rawAnswer;
  let verdicts: unknown[] = [];          // chat_logs.cite_verdicts 에 남긴다 — 검증기 오탐률 측정 재료(#176)
  let citedDocs: string[] = [];          // 답변이 실제로 인용해 확인된 문서 — 출처 목록을 이 순서로 앞세운다(#176)
  try {
    const vr = await CiteVerify.verifyCitations({
      answer: rawAnswer, chunks: (extra2 as unknown as Chunk[]).concat(chunks2).concat(citing.chunks), annexSources: annex.sources, systemPrompt,
      callHaiku: (sys: string, u: string) => callHaikuText(sb, apiKey, sys, u, 'rag.ts:citeJudge', 3000)   // 900은 24건 판정 JSON에 빠듯(#205),
    });
    answer = vr.answer;
    verdicts = vr.verdicts || [];
    citedDocs = (vr.citedDocs || []) as string[];
    if (vr.verdicts.length || vr.autoTagged) console.log('[인용 검증]', 'auto+' + (vr.autoTagged || 0), 'quote+' + (vr.quoteTagged || 0), JSON.stringify(vr.verdicts.map((v: { key: string; status: string; reason: string }) => [v.key, v.status, v.reason])));
  } catch (e) { console.warn('인용 검증 실패(답변 그대로):', e); }

  // 출처 순서: **조문 정밀검색분(extra)을 먼저** — 텔레그램 footer는 앞 6개만 보여주므로(#89),
  // RAG 15개를 먼저 채우면 정작 답변이 인용한 조문이 잘려 나간다. 실제로 「기지국 개설 허가 절차」
  // 답변이 전파법 제21조제2항을 [원문 확인됨]으로 인용했는데 출처에는 지방세법 시행령·논문·
  // 세미나 자료만 보였다 — 근거는 맞는데 어디서 왔는지 확인할 수가 없었다.
  // 별표는 조문 다음·RAG 앞 — 금액·요율을 물은 답변의 정본이 별표이므로 잘리면 안 된다(#90).
  const sources: string[] = [];
  for (const h of extra2) if (h.doc_name && !sources.includes(h.doc_name)) sources.push(h.doc_name);
  for (const s of annex.sources) { const t = '[별표] ' + s; if (!sources.includes(t)) sources.push(t); }
  for (const c of chunks2) if (c.doc_name && !sources.includes(c.doc_name)) sources.push(c.doc_name);
  for (const r of kb) { const t = '[요약] ' + (r.title || '').trim(); if (r.title && !sources.includes(t)) sources.push(t); }
  for (const s of news.sources) if (!sources.includes(s)) sources.push(s);
  // 답변이 실제로 인용해 확인된 문서를 맨 앞으로(#176) — 텔레그램 footer는 앞 6개만 보여주는데, 9/17 실측에서
  // 6칸 중 5칸이 답변에 안 쓰인 검색 잡음이었다. 나머지 순서(정밀검색→별표→RAG→요약→뉴스)는 그대로.
  if (citedDocs.length) {
    const isCited = (s: string) => citedDocs.some((d) => s === d || d.startsWith(s) || s.startsWith(d));
    const front = sources.filter(isCited), rest = sources.filter((s) => !isCited(s));
    sources.length = 0; sources.push(...front, ...rest);
  }
  // 근거 청크 id — sources와 같은 순서(조문 정밀검색분 먼저, 그다음 RAG, 끝에 보강 조각). 숫자 id만 남긴다.
  const chunkIds: number[] = [];
  for (const h of (extra2 as unknown as Chunk[]).concat(chunks2 as Chunk[]).concat(addedIds.concat(citing.ids).map((id) => ({ id } as Chunk)))) {
    if (typeof h.id === 'number' && !chunkIds.includes(h.id)) chunkIds.push(h.id);
  }
  return { answer, sources, webSources: webRefs, chunkIds, verdicts, searchMeta };
}
