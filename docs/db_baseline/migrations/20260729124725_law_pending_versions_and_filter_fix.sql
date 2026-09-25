-- 20260729124725 law_pending_versions_and_filter_fix

-- ① 필터 누락 복구
-- law_version_tracking 마이그레이션에서 only_current 인자를 추가할 때 인자 개수가 달라져
-- CREATE OR REPLACE가 '교체'가 아니라 '새 오버로드 생성'이 되었다. app.js는 인자 3개로
-- 호출하므로 status 필터가 없는 구 오버로드가 계속 쓰이고 있었다(구버전·시행예정 조문이
-- 자문 근거로 유입). 구 오버로드를 제거하면 같은 호출이 4인자 버전(only_current 기본 true)으로
-- 해석된다.
DROP FUNCTION IF EXISTS public.match_chunks_semantic(vector, double precision, integer);
DROP FUNCTION IF EXISTS public.search_chunks_trgm(text, double precision, integer);

-- ② 시행예정본 다건 수용
-- law_watch는 법령당 pending 1건(pending_mst/law_no/enf)만 담을 수 있어, 정보통신망법처럼
-- 2026.9.11 / 2026.10.1 / 2027.4.1 다단 시행이 걸린 경우 가장 이른 1건 외에는 버려졌다.
-- 시행일별 통합본은 (MST, 시행일자) 조합으로 식별된다 — 같은 MST가 서로 다른 시행일 통합본을
-- 갖는 경우가 실제로 있다(정보통신망법 MST 285199 → 20261001 / 20270401).
CREATE TABLE IF NOT EXISTS public.law_pending (
  id              bigserial PRIMARY KEY,
  law_name        text NOT NULL,
  law_id          text,
  law_type_token  text,
  api_target      text NOT NULL DEFAULT 'law',   -- law | admrul
  watch_doc_name  text,                          -- 감시 기준이 된 현행 등재본(law_watch.doc_name)
  mst             text NOT NULL,                 -- 법령일련번호 / 행정규칙일련번호
  law_no          text,                          -- 공포번호 / 발령번호
  enf_date        text NOT NULL,                 -- YYYYMMDD (시행일)
  doc_name        text,                          -- 적재된 경우 document_chunks.doc_name
  sync_state      text NOT NULL DEFAULT 'detected',  -- detected | loaded | promoted | obsolete
  note            text,
  detected_at     timestamptz NOT NULL DEFAULT now(),
  loaded_at       timestamptz,
  promoted_at     timestamptz,
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT law_pending_uniq UNIQUE (law_name, mst, enf_date)
);

CREATE INDEX IF NOT EXISTS law_pending_state_idx ON public.law_pending (sync_state, enf_date);
CREATE INDEX IF NOT EXISTS law_pending_law_idx   ON public.law_pending (law_name, enf_date);

ALTER TABLE public.law_pending ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS law_pending_read ON public.law_pending;
CREATE POLICY law_pending_read ON public.law_pending FOR SELECT USING (true);;
