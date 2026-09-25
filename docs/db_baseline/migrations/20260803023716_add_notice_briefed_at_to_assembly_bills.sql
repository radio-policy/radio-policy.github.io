-- 20260803023716 add_notice_briefed_at_to_assembly_bills

-- 운영자 지시(2026-08-03): 국회 입법예고는 브리핑에 "처음 감지될 때 딱 한 번"만 노출.
-- notice_briefed_at 이 NULL 인 건만 (c) 의견등록 섹션에 싣고, 발송 성공 후 now()로 채운다.
ALTER TABLE assembly_bills ADD COLUMN IF NOT EXISTS notice_briefed_at timestamptz;
COMMENT ON COLUMN assembly_bills.notice_briefed_at IS
  '모닝 브리핑 입법예고(의견등록) 섹션에 최초로 실린 시각. NULL이면 아직 안 실림. 운영자 지시 2026-08-03 — 1회 노출 원칙';
CREATE INDEX IF NOT EXISTS idx_assembly_bills_notice_briefed
  ON assembly_bills (notice_end_dt) WHERE notice_briefed_at IS NULL;;
