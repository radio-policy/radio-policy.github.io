-- 20260903161316 assembly_bills_stage_columns_122

alter table public.assembly_bills
  add column if not exists committee_dt    text,
  add column if not exists cmt_present_dt  text,
  add column if not exists cmt_proc_dt     text,
  add column if not exists cmt_proc_result text,
  add column if not exists law_submit_dt   text,
  add column if not exists law_present_dt  text,
  add column if not exists law_proc_dt     text;
comment on column public.assembly_bills.committee_dt    is '소관위 회부일 (API COMMITTEE_DT) — #122';
comment on column public.assembly_bills.cmt_present_dt  is '소관위 상정일 (API CMT_PRESENT_DT) — 소위 필드는 API에 없어 상정일이 심사 착수의 대리 지표';
comment on column public.assembly_bills.cmt_proc_dt     is '소관위 처리일 (API CMT_PROC_DT)';
comment on column public.assembly_bills.cmt_proc_result is '소관위 처리결과 (API CMT_PROC_RESULT_CD) — 가결이면 proc_result=위원회 의결, 대안반영폐기 등은 종결';
comment on column public.assembly_bills.law_submit_dt   is '법사위 회부일 (API LAW_SUBMIT_DT)';
comment on column public.assembly_bills.law_present_dt  is '법사위 상정일 (API LAW_PRESENT_DT)';
comment on column public.assembly_bills.law_proc_dt     is '법사위 처리일 (API LAW_PROC_DT)';;
