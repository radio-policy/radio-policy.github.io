-- 20260617043826 kb_upload_approval_gate

-- 지식베이스 업로드 파일 승인 게이트
-- 기본값 true: 기존 행·크롤러 유입·법령 RAG는 변화 없음. UI 업로드만 앱에서 false로 저장.
ALTER TABLE public.document_chunks
  ADD COLUMN IF NOT EXISTS is_approved boolean NOT NULL DEFAULT true;

-- RAG 시맨틱 검색: 미승인 청크 제외
CREATE OR REPLACE FUNCTION public.match_chunks_semantic(query_embedding vector, match_threshold double precision DEFAULT 0.5, match_count integer DEFAULT 8)
 RETURNS TABLE(id bigint, doc_name text, doc_category text, chunk_index integer, content text, notice_no text, article_no text, effective_date text, similarity double precision)
 LANGUAGE sql
 STABLE SECURITY DEFINER
AS $function$
  SELECT
    id, doc_name, doc_category, chunk_index, content,
    notice_no, article_no, effective_date,
    (1 - (embedding <=> query_embedding))::float AS similarity
  FROM document_chunks
  WHERE embedding IS NOT NULL
    AND is_approved
    AND (1 - (embedding <=> query_embedding)) > match_threshold
  ORDER BY embedding <=> query_embedding
  LIMIT match_count;
$function$;

-- RAG 트라이그램(키워드) 검색: 미승인 청크 제외
CREATE OR REPLACE FUNCTION public.search_chunks_trgm(query_text text, match_threshold double precision DEFAULT 0.12, match_count integer DEFAULT 8)
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
    AND extensions.word_similarity(query_text, content) > match_threshold
  ORDER BY trgm_score DESC
  LIMIT match_count;
$function$;

-- 문서 목록에 승인여부 노출 (반환 타입 변경이라 DROP 후 재생성)
DROP FUNCTION IF EXISTS public.list_kb_documents();
CREATE FUNCTION public.list_kb_documents()
 RETURNS TABLE(doc_category text, doc_name text, chunks bigint, embedded bigint, approved boolean)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT min(doc_category) AS doc_category, doc_name, count(*) AS chunks,
         count(*) FILTER (WHERE embedding IS NOT NULL) AS embedded,
         bool_and(is_approved) AS approved
  FROM document_chunks
  WHERE doc_category IS DISTINCT FROM '보도자료'
  GROUP BY doc_name
  ORDER BY doc_name;
$function$;;
