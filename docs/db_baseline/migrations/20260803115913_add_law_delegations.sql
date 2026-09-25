-- 20260803115913 add_law_delegations

-- 법령 위임 대응표 (법제처 3단비교 정본, 2026-08-03)
-- 왜: /law가 "기한은 시행령에 있는데 상위 법률을 빠뜨리는" 문제를 검색·프롬프트로 풀려다 실패했다.
--     3단비교(thdCmp knd=2)는 법제처가 확정한 조문 단위 위임 대응이라, 검색 운에 기대지 않고
--     법률 조문 ↔ 하위법령 조문을 확정적으로 잇는다.
--     실측 커버리지: 전파법 248조 중 171조, 전기통신사업법 236조 중 149조,
--     정보통신망법 217조 중 103조, 개인정보 보호법 201조 중 114조에 대응이 존재.
--     타계열 위임(전파법→무선설비규칙, 전기통신사업법→방송통신설비의 기술기준에 관한 규정)도 포착 —
--     문서명 추측(family)으로는 절대 못 찾는 것들이다.
-- 한계: 3단비교는 법률-시행령-시행규칙 3단이라 **행정규칙(고시)은 포함되지 않는다**.
--       고시 연결은 별건(고시 본문의 "법 제N조에 따라" 역추출).
create table if not exists public.law_delegations (
  id            bigserial primary key,
  parent_law    text not null,   -- 법률명 (예: 개인정보 보호법)
  parent_article text not null,  -- 조번호 정규형 (예: 34조, 6조의2)
  parent_title  text,            -- 조제목 (예: 제34조(개인정보 유출 등의 통지ㆍ신고))
  child_law     text not null,   -- 하위법령명 (시행령/시행규칙/타계열 규칙)
  child_article text not null,
  child_title   text,
  child_kind    text,            -- 시행령 / 시행규칙
  synced_at     timestamptz not null default now(),
  unique (parent_law, parent_article, child_law, child_article)
);
comment on table public.law_delegations is
  '법제처 3단비교(thdCmp knd=2) 위임 대응 — 법률 조문 ↔ 시행령·시행규칙 조문. /law가 상·하위 조문을 함께 제시하는 근거. sync_law_delegations.py가 적재. 고시는 미포함(3단비교 범위 밖).';
create index if not exists law_delegations_parent_idx on public.law_delegations (parent_law, parent_article);
create index if not exists law_delegations_child_idx  on public.law_delegations (child_law, child_article);
alter table public.law_delegations enable row level security;
create policy "law_delegations anon select" on public.law_delegations for select to anon using (true);;
