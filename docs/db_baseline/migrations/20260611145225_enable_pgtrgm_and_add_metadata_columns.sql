-- 20260611145225 enable_pgtrgm_and_add_metadata_columns


-- 1. pg_trgm 확장 활성화
CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA extensions;

-- 2. document_chunks 메타데이터 컬럼 추가
ALTER TABLE document_chunks
  ADD COLUMN IF NOT EXISTS notice_no text,
  ADD COLUMN IF NOT EXISTS article_no text,
  ADD COLUMN IF NOT EXISTS effective_date text;
;
