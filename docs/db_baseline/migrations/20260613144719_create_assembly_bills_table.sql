-- 20260613144719 create_assembly_bills_table


CREATE TABLE IF NOT EXISTS assembly_bills (
  id              uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  bill_id         text UNIQUE NOT NULL,      -- 의안 고유 ID (PRC_...)
  bill_no         text,                       -- 의안번호
  bill_name       text NOT NULL,              -- 의안명
  proposer        text,                       -- 제안자
  committee       text,                       -- 소관위원회
  proc_result     text DEFAULT '접수',        -- 처리결과(상태)
  propose_dt      text,                       -- 제안일 (YYYYMMDD)
  proc_dt         text,                       -- 처리일 (YYYYMMDD)
  age             integer DEFAULT 22,         -- 국회 대수
  matched_keywords text[],                    -- 매칭된 키워드 목록
  link_url        text,                       -- 의안 상세 URL
  prev_proc_result text,                      -- 이전 상태 (변경 감지용)
  created_at      timestamptz DEFAULT now(),
  updated_at      timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS assembly_bills_propose_dt_idx ON assembly_bills (propose_dt DESC);
CREATE INDEX IF NOT EXISTS assembly_bills_proc_result_idx ON assembly_bills (proc_result);

COMMENT ON TABLE assembly_bills IS '국회 의안 모니터링 — 전파/통신 관련 법안 추적';
;
