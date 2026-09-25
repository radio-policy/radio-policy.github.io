-- 20260611145237 create_trgm_index_and_rpc


-- 1. GIN trgm 인덱스 (content 전문 검색 가속)
CREATE INDEX IF NOT EXISTS document_chunks_content_trgm_idx
  ON document_chunks USING gin(content extensions.gin_trgm_ops);

-- 2. trgm 유사도 검색 RPC 함수
CREATE OR REPLACE FUNCTION search_chunks_trgm(
  query_text  text,
  match_threshold float DEFAULT 0.12,
  match_count int   DEFAULT 8
)
RETURNS TABLE (
  id             bigint,
  doc_name       text,
  doc_category   text,
  chunk_index    int,
  content        text,
  notice_no      text,
  article_no     text,
  effective_date text,
  trgm_score     float
)
LANGUAGE sql STABLE SECURITY DEFINER
AS $$
  SELECT
    id, doc_name, doc_category, chunk_index, content,
    notice_no, article_no, effective_date,
    extensions.word_similarity(query_text, content)::float AS trgm_score
  FROM document_chunks
  WHERE extensions.word_similarity(query_text, content) > match_threshold
  ORDER BY trgm_score DESC
  LIMIT match_count;
$$;

-- 3. anon role에 실행 권한 부여
GRANT EXECUTE ON FUNCTION search_chunks_trgm(text, float, int) TO anon;
GRANT EXECUTE ON FUNCTION search_chunks_trgm(text, float, int) TO authenticated;
;
