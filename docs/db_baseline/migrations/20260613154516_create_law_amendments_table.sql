-- 20260613154516 create_law_amendments_table


CREATE TABLE IF NOT EXISTS law_amendments (
  id           uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  law_id       text UNIQUE NOT NULL,          -- 법령 고유 ID (법제처 MST)
  law_nm       text NOT NULL,                 -- 법령명
  law_type     text NOT NULL,                 -- bylaw(시행령)/rules(시행규칙)/admrul(고시)/lsAnc(입법예고)
  ann_type     text,                          -- 제정/개정/폐지
  public_dt    text,                          -- 공포일자 YYYYMMDD
  enf_dt       text,                          -- 시행일자 YYYYMMDD
  public_no    text,                          -- 공포번호
  matched_keywords text[],
  link_url     text,
  prev_public_dt text,                        -- 이전 공포일 (변경 감지용)
  created_at   timestamptz DEFAULT now(),
  updated_at   timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS law_amendments_law_type_idx ON law_amendments(law_type);
CREATE INDEX IF NOT EXISTS law_amendments_public_dt_idx ON law_amendments(public_dt);
;
