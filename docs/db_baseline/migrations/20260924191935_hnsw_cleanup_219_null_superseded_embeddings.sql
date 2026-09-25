-- 20260924191935 hnsw_cleanup_219_null_superseded_embeddings

-- #219 (개선안 §4-3-3, 운영자 결정 2026-09-25 04:2x "진행"): 옛 판(superseded) 조각의 임베딩 비우기.
-- 검색은 전부 only_current라 이 벡터는 HNSW 자리만 차지한다(지침 1308). 되돌리기용 백업표를 먼저 뜬다(1주 뒤 DROP).
create table public._bak_superseded_emb_20260925 as
  select id, embedding from public.document_chunks
   where status = 'superseded' and embedding is not null;
alter table public._bak_superseded_emb_20260925 enable row level security;
revoke all on public._bak_superseded_emb_20260925 from anon, authenticated;
grant select, insert, update, delete on public._bak_superseded_emb_20260925 to service_role;
comment on table public._bak_superseded_emb_20260925 is
  '#219 되돌리기용: superseded 조각 임베딩 백업(2026-09-25). 이상 없으면 2026-10-02 이후 DROP';

update public.document_chunks d set embedding = null
  from public._bak_superseded_emb_20260925 b
 where d.id = b.id;;
