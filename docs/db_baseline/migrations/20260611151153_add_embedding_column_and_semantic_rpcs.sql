-- 20260611151153 add_embedding_column_and_semantic_rpcs


-- 1. embedding 컬럼 추가 (voyage-4-lite 기본 1024차원)
ALTER TABLE document_chunks
  ADD COLUMN IF NOT EXISTS embedding vector(1024);

-- 2. 시맨틱 유사도 검색 RPC (코사인 유사도)
CREATE OR REPLACE FUNCTION match_chunks_semantic(
  query_embedding vector(1024),
  match_threshold  float DEFAULT 0.5,
  match_count      int   DEFAULT 8
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
  similarity     float
)
LANGUAGE sql STABLE SECURITY DEFINER
AS $$
  SELECT
    id, doc_name, doc_category, chunk_index, content,
    notice_no, article_no, effective_date,
    (1 - (embedding <=> query_embedding))::float AS similarity
  FROM document_chunks
  WHERE embedding IS NOT NULL
    AND (1 - (embedding <=> query_embedding)) > match_threshold
  ORDER BY embedding <=> query_embedding
  LIMIT match_count;
$$;

GRANT EXECUTE ON FUNCTION match_chunks_semantic(vector(1024), float, int) TO anon;
GRANT EXECUTE ON FUNCTION match_chunks_semantic(vector(1024), float, int) TO authenticated;

-- 3. 배치 임베딩 업데이트 RPC (백필 스크립트용)
CREATE OR REPLACE FUNCTION batch_update_embeddings(
  p_ids        bigint[],
  p_embeddings text[]
)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
AS $$
DECLARE
  i int;
BEGIN
  FOR i IN 1..array_length(p_ids, 1) LOOP
    UPDATE document_chunks
    SET embedding = p_embeddings[i]::vector(1024)
    WHERE id = p_ids[i];
  END LOOP;
END;
$$;

GRANT EXECUTE ON FUNCTION batch_update_embeddings(bigint[], text[]) TO service_role;
;
