-- 20260729111822 law_version_tracking

-- 법령 자동 현행화(Phase 1+2) 기반: 조문 레이어 버전 관리 + 감시 레지스트리
-- 기존 데이터는 전부 status='current'로 채워지므로 현재 자문 동작에 영향 없음.

-- ── 1. document_chunks 버전 컬럼 ──────────────────────────────
ALTER TABLE document_chunks
  ADD COLUMN IF NOT EXISTS law_id  text,   -- 법제처 법령ID (버전 간 동일성 기준)
  ADD COLUMN IF NOT EXISTS law_mst text,   -- 법제처 법령일련번호 (버전 고유키)
  ADD COLUMN IF NOT EXISTS status  text NOT NULL DEFAULT 'current';  -- current | pending | superseded

ALTER TABLE document_chunks
  DROP CONSTRAINT IF EXISTS document_chunks_status_chk;
ALTER TABLE document_chunks
  ADD CONSTRAINT document_chunks_status_chk
  CHECK (status IN ('current','pending','superseded'));

CREATE INDEX IF NOT EXISTS idx_document_chunks_status   ON document_chunks(status);
CREATE INDEX IF NOT EXISTS idx_document_chunks_law      ON document_chunks(law_id, status);

-- ── 2. 감시 레지스트리 ────────────────────────────────────────
-- 감시 대상은 매 실행마다 document_chunks에서 자동 발견(동적) → 이 표는 상태 캐시.
CREATE TABLE IF NOT EXISTS law_watch (
  id                bigserial PRIMARY KEY,
  doc_name          text UNIQUE NOT NULL,     -- 지식베이스 문서명(정체 키)
  law_name          text,                     -- 파싱된 법령명 (예: 전파법)
  law_type_token    text,                     -- 법률 / 대통령령 / 과학기술정보통신부령 / 고시 …
  api_target        text,                     -- law | admrul (법제처 DRF target)
  law_id            text,                     -- 법제처 법령ID
  registered_mst    text,                     -- 등재본 일련번호
  registered_law_no text,                     -- 등재본 법령번호 (제21065호)
  registered_enf    text,                     -- 등재본 시행일 (YYYYMMDD)
  latest_mst        text,                     -- 최신 현행본 일련번호
  latest_law_no     text,
  latest_enf        text,
  pending_mst       text,                     -- 시행예정본 (Phase 3 대비, 저장만)
  pending_law_no    text,
  pending_enf       text,
  watch_status      text NOT NULL DEFAULT 'watching',  -- watching | unmatched | excluded
  sync_status       text NOT NULL DEFAULT 'unknown',   -- current | outdated | approved | synced | unknown
  approved_at       timestamptz,              -- 운영자가 '현행화' 승인한 시각
  approved_mst      text,                     -- 승인 대상 버전
  last_checked_at   timestamptz,
  note              text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE law_watch DROP CONSTRAINT IF EXISTS law_watch_watch_status_chk;
ALTER TABLE law_watch ADD CONSTRAINT law_watch_watch_status_chk
  CHECK (watch_status IN ('watching','unmatched','excluded'));
ALTER TABLE law_watch DROP CONSTRAINT IF EXISTS law_watch_sync_status_chk;
ALTER TABLE law_watch ADD CONSTRAINT law_watch_sync_status_chk
  CHECK (sync_status IN ('current','outdated','approved','synced','unknown'));

CREATE INDEX IF NOT EXISTS idx_law_watch_sync  ON law_watch(sync_status);
CREATE INDEX IF NOT EXISTS idx_law_watch_watch ON law_watch(watch_status);

-- RLS: 다른 운영 테이블과 동일 패턴 (anon 읽기 허용, 쓰기는 service 전용)
ALTER TABLE law_watch ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS law_watch_anon_select ON law_watch;
CREATE POLICY law_watch_anon_select ON law_watch FOR SELECT TO anon, authenticated USING (true);

-- ── 3. 검색 함수에 현행본 필터 추가 ───────────────────────────
-- kb_chunks의 only_current 패턴과 동일. 기본값 true → 기존 호출부 무수정으로 동작.
CREATE OR REPLACE FUNCTION public.match_chunks_semantic(
  query_embedding vector,
  match_threshold double precision DEFAULT 0.5,
  match_count integer DEFAULT 8,
  only_current boolean DEFAULT true)
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
    AND (NOT only_current OR status = 'current')
    AND (1 - (embedding <=> query_embedding)) > match_threshold
  ORDER BY embedding <=> query_embedding
  LIMIT match_count;
$function$;

CREATE OR REPLACE FUNCTION public.search_chunks_trgm(
  query_text text,
  match_threshold double precision DEFAULT 0.12,
  match_count integer DEFAULT 8,
  only_current boolean DEFAULT true)
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
$function$;;
