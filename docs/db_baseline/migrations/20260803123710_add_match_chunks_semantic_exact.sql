-- 20260803123710 add_match_chunks_semantic_exact

-- 자문용 의미 검색 A/B 비교본 — HNSW 인덱스를 쓰지 않는 전수 정확 검색 (2026-08-03)
-- 기존 match_chunks_semantic은 **그대로 둔다**. 이건 비교 전용이라 어느 쪽이 나은지 실측한 뒤에
-- 자문 경로를 옮길지 판단한다(옮기지 않기로 하면 이 함수만 지우면 끝).
-- `+ 0.0`이 인덱스 사용을 막는 장치인 이유는 match_law_articles_semantic 주석 참조
-- (HNSW는 ef_search 기본값 탓에 후보 ~40개만 훑고, Supabase 관리형에서는 상향 권한이 없다).
create or replace function public.match_chunks_semantic_exact(
  query_embedding vector,
  match_threshold double precision default 0.5,
  match_count integer default 8,
  only_current boolean default true
)
returns table(
  id bigint, doc_name text, doc_category text, chunk_index integer,
  content text, notice_no text, article_no text, effective_date text,
  similarity double precision
)
language sql stable security definer
as $function$
  select
    id, doc_name, doc_category, chunk_index, content,
    notice_no, article_no, effective_date,
    (1 - (embedding <=> query_embedding))::float as similarity
  from document_chunks
  where embedding is not null
    and is_approved
    and (not only_current or status = 'current')
    and (1 - (embedding <=> query_embedding)) > match_threshold
  order by (embedding <=> query_embedding) + 0.0
  limit match_count;
$function$;;
