-- 20260612063723 list_kb_documents_group_by_name

-- 같은 문서가 여러 카테고리로 저장돼도 목록에 1행만 표시되도록 doc_name 기준 그룹핑
CREATE OR REPLACE FUNCTION list_kb_documents()
RETURNS TABLE(doc_category text, doc_name text, chunks bigint, embedded bigint)
LANGUAGE sql STABLE AS $$
  SELECT min(doc_category) AS doc_category, doc_name, count(*) AS chunks,
         count(*) FILTER (WHERE embedding IS NOT NULL) AS embedded
  FROM document_chunks
  WHERE doc_category IS DISTINCT FROM '보도자료'
  GROUP BY doc_name
  ORDER BY doc_name;
$$;;
