-- 20260612054236 create_list_kb_documents_rpc

-- 지식 베이스 실제 문서 목록 (대시보드 국내 법령·고시 탭에서 호출)
CREATE OR REPLACE FUNCTION list_kb_documents()
RETURNS TABLE(doc_category text, doc_name text, chunks bigint, embedded bigint)
LANGUAGE sql STABLE AS $$
  SELECT doc_category, doc_name, count(*) AS chunks,
         count(*) FILTER (WHERE embedding IS NOT NULL) AS embedded
  FROM document_chunks
  WHERE doc_category IS DISTINCT FROM '보도자료'
  GROUP BY doc_category, doc_name
  ORDER BY doc_category, doc_name;
$$;;
