-- 20261015074013 annex_chunks_semantic_20261014

-- 별표 조각 + 질문 임베딩 유사도 (장동선 /ask 빠뜨림 판정 §4-7, 2026-10-15)
-- 별표 동반(app.js·rag.ts buildAnnexContext 1단계, rag_core.js annexBlock)이 별표 조각을 고를 때 「질문 키워드 적중 수」 동점을
-- 질문과 뜻이 가까운 순으로 가르게 한다. 종전 PostgREST 조회(doc_name = · status current · article_no like '별표 N(%' · chunk_index 순)와
-- 같은 행을 같은 순서로 돌려주고, 1 - 코사인 거리를 계산 열로만 더한다.
-- ⚠️ 거리로 ORDER BY·LIMIT 하지 말 것 — HNSW 인덱스를 타면 ef_search 후보를 후필터해 행이 조용히 줄거나 0이 된다(#185).
--    doc_name으로 좁힌 ≤812행에 정확 계산이라 hnsw 설정도 필요 없다.
-- SECURITY INVOKER + search_path '' (#295) — 공개 조각의 유사도만 돌려준다. anon 포함 EXECUTE 명시(브라우저·봇 공통 경로).
create or replace function public.annex_chunks_semantic(query_embedding public.vector, p_doc_name text, p_article_prefix text)
returns table(id bigint, chunk_index integer, article_no text, content text, similarity double precision)
language sql
stable
security invoker
set search_path = ''
as $$
  select c.id, c.chunk_index, c.article_no, c.content,
         case when c.embedding is null or query_embedding is null then null
              else (1 - (c.embedding operator(public.<=>) query_embedding))::double precision end as similarity
  from public.document_chunks c
  where c.doc_name = p_doc_name
    and c.status = 'current'
    and starts_with(c.article_no, p_article_prefix)
  order by c.chunk_index;
$$;

revoke all on function public.annex_chunks_semantic(public.vector, text, text) from public, anon, authenticated, service_role;
grant execute on function public.annex_chunks_semantic(public.vector, text, text) to anon;
grant execute on function public.annex_chunks_semantic(public.vector, text, text) to authenticated;
grant execute on function public.annex_chunks_semantic(public.vector, text, text) to service_role;

comment on function public.annex_chunks_semantic(public.vector, text, text) is
  '별표 조각 + 질문 임베딩 유사도(장동선 판정 §4-7, 2026-10-15). 거리 ORDER BY·LIMIT 금지(#185) — chunk_index 순 전체 행.';
;
