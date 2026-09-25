-- 20260923093152 rag_search_tuning_step1_rollback_trgm_operator

SELECT extensions.word_similarity('load', 'load');
-- 롤백: <% 연산자 조건이 한국어 본문에서 선택도가 없어(37K/47K 통과) 3.1s→8.7s로 느려짐. 2026-09-23 17:40 원본 정의로 복원(SET 절 없음 → proconfig 초기화).
CREATE OR REPLACE FUNCTION public.search_chunks_trgm(query_text text, match_threshold double precision DEFAULT 0.12, match_count integer DEFAULT 8, only_current boolean DEFAULT true)
 RETURNS TABLE(id bigint, doc_name text, doc_category text, chunk_index integer, content text, notice_no text, article_no text, effective_date text, trgm_score double precision)
 LANGUAGE sql
 STABLE SECURITY DEFINER
AS $function$
  SELECT
    id, doc_name, doc_category, chunk_index, content,
    notice_no, article_no, effective_date,
    extensions.word_similarity(query_text, content)::float AS trgm_score
  FROM document_chunks
  WHERE is_approved
    AND (NOT only_current OR status = 'current')
    AND extensions.word_similarity(query_text, content) > match_threshold
  ORDER BY trgm_score DESC
  LIMIT match_count;
$function$;

CREATE OR REPLACE FUNCTION public.search_kb_chunks_trgm(query_text text, match_threshold double precision DEFAULT 0.10, match_count integer DEFAULT 6, only_current boolean DEFAULT true)
 RETURNS TABLE(doc_id bigint, title text, law_type text, law_number text, enforcement_date text, status text, concept_type text, path text, chunk_idx integer, content text, trgm_score double precision)
 LANGUAGE sql
 STABLE
AS $function$
  select d.id, d.title, d.law_type, d.law_number, d.enforcement_date,
         d.status, d.concept_type, d.path, c.chunk_idx, c.content,
         extensions.word_similarity(query_text, c.content)::float as trgm_score
  from public.kb_chunks c
  join public.kb_documents d on d.id = c.doc_id
  where (not only_current or d.status = 'current')
    and extensions.word_similarity(query_text, c.content) > match_threshold
  order by trgm_score desc
  limit match_count;
$function$;;
