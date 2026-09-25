-- 20260923091925 rag_search_tuning_step1_trgm_index_efsearch

-- 0) 확장 라이브러리 로드(세션에서 GUC를 실제 파라미터로 등록시키기 위함)
SELECT extensions.word_similarity('load', 'load');
SELECT '[1,0]'::vector <=> '[0,1]'::vector;

-- 1) news_feed created_at 인덱스
CREATE INDEX IF NOT EXISTS news_feed_created_at_idx ON public.news_feed (created_at DESC);

-- 2) search_chunks_trgm: <% 연산자 조건 추가 → GIN 사용, 기존 > match_threshold 유지
CREATE OR REPLACE FUNCTION public.search_chunks_trgm(query_text text, match_threshold double precision DEFAULT 0.12, match_count integer DEFAULT 8, only_current boolean DEFAULT true)
 RETURNS TABLE(id bigint, doc_name text, doc_category text, chunk_index integer, content text, notice_no text, article_no text, effective_date text, trgm_score double precision)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET pg_trgm.word_similarity_threshold = 0.10
AS $function$
  SELECT
    id, doc_name, doc_category, chunk_index, content,
    notice_no, article_no, effective_date,
    extensions.word_similarity(query_text, content)::float AS trgm_score
  FROM document_chunks
  WHERE is_approved
    AND (NOT only_current OR status = 'current')
    AND query_text OPERATOR(extensions.<%) content
    AND extensions.word_similarity(query_text, content) > match_threshold
  ORDER BY trgm_score DESC
  LIMIT match_count;
$function$;

-- 2b) search_kb_chunks_trgm: 동일 처리
CREATE OR REPLACE FUNCTION public.search_kb_chunks_trgm(query_text text, match_threshold double precision DEFAULT 0.10, match_count integer DEFAULT 6, only_current boolean DEFAULT true)
 RETURNS TABLE(doc_id bigint, title text, law_type text, law_number text, enforcement_date text, status text, concept_type text, path text, chunk_idx integer, content text, trgm_score double precision)
 LANGUAGE sql
 STABLE
 SET pg_trgm.word_similarity_threshold = 0.10
AS $function$
  select d.id, d.title, d.law_type, d.law_number, d.enforcement_date,
         d.status, d.concept_type, d.path, c.chunk_idx, c.content,
         extensions.word_similarity(query_text, c.content)::float as trgm_score
  from public.kb_chunks c
  join public.kb_documents d on d.id = c.doc_id
  where (not only_current or d.status = 'current')
    and query_text OPERATOR(extensions.<%) c.content
    and extensions.word_similarity(query_text, c.content) > match_threshold
  order by trgm_score desc
  limit match_count;
$function$;

-- 3) HNSW 후보 폭: 함수 호출 동안만 ef_search 100
ALTER FUNCTION public.match_chunks_semantic(vector, double precision, integer, boolean) SET hnsw.ef_search = 100;
ALTER FUNCTION public.match_kb_chunks_semantic(vector, double precision, integer, boolean) SET hnsw.ef_search = 100;;
