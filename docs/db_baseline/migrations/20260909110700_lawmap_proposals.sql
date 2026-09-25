-- 20260909110700 lawmap_proposals

-- #147 (2026-09-09) 법령 관계도 AI 연결 "제안 → 관리자 승인" (인수인계 과제 1, 2026-09-06 운영자 결정).
-- AI가 만드는 연결(자문 말미 <lawmap> 블록, 관리자 즉석 생성, 보강)은 정식 관계도(law_graph_*)에 바로 넣지 않고
-- 이 표에 검토 대기로 쌓인다. 관리자가 관계도 탭 "검토 대기 N건" 카드에서 수정·AI 보강 후 승인하면 saveLawmapData
-- (조문 실존 관문 #123)를 거쳐 정식 연결이 된다. 정식 관계도 테이블은 오염되지 않고 상태 컬럼도 필요 없다.
create table if not exists public.lawmap_proposals (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  created_by uuid default auth.uid(),
  requester text,                      -- profiles.name 스냅샷(표시용)
  origin text not null default 'advisory',   -- advisory | generate | enrich
  question text,                       -- 자문 질문 / 생성 질의
  topic text not null,
  description text,
  relations jsonb not null default '[]'::jsonb,   -- [{law,type,relation,basis,law_desc}]
  gate jsonb,                          -- 제출 시 관문 결과 [{law,ok,reason,tag}] (조문 실존만 — 적합성은 사람이 본다)
  status text not null default 'pending' check (status in ('pending','approved','rejected')),
  decided_at timestamptz,
  decided_by uuid,
  decision_note text,
  result jsonb                         -- 승인 시 saveLawmapData 반환(topicId·saved·skipped)
);
create index if not exists lawmap_proposals_status_idx on public.lawmap_proposals (status, created_at desc);
alter table public.lawmap_proposals enable row level security;
-- 제안 올리기: 승인 프로필(본인 명의만). 자문 말미 자동 제출이 여기로 온다.
create policy lawmap_proposals_ins on public.lawmap_proposals
  for insert to authenticated with check (public.is_approved_user() and created_by = auth.uid());
-- 읽기: 관리자 전체 / 본인은 자기 제안 상태 확인
create policy lawmap_proposals_sel on public.lawmap_proposals
  for select to authenticated using (public.is_admin() or created_by = auth.uid());
-- 승인·기각·수정·삭제: 관리자만
create policy lawmap_proposals_upd on public.lawmap_proposals
  for update to authenticated using (public.is_admin()) with check (public.is_admin());
create policy lawmap_proposals_del on public.lawmap_proposals
  for delete to authenticated using (public.is_admin());;
