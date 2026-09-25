-- 20260923093158 rag_search_tuning_step2_law_semantic_two_stage

SELECT '[1,0]'::vector <=> '[0,1]'::vector;
-- match_law_articles_semantic 2단화: 안쪽은 순수 거리 정렬(HNSW 사용)로 후보 max(match_count*10, 80)건, 바깥에서 가산점 재정렬.
-- 시그니처·반환 컬럼 불변(호출부 무수정). 원본(전수 정렬)은 2026-09-23 17:40 정의 — 롤백 시 그대로 CREATE OR REPLACE.
CREATE OR REPLACE FUNCTION public.match_law_articles_semantic(query_embedding vector, match_threshold double precision DEFAULT 0.0, match_count integer DEFAULT 8, only_current boolean DEFAULT true)
 RETURNS TABLE(id bigint, doc_name text, doc_category text, chunk_index integer, content text, notice_no text, article_no text, effective_date text, similarity double precision)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET hnsw.ef_search = 200
AS $function$
  select id, doc_name, doc_category, chunk_index, content,
         notice_no, article_no, effective_date,
         (1 - dist)::float as similarity
  from (
    select id, doc_name, doc_category, chunk_index, content, notice_no, article_no, effective_date,
           (embedding <=> query_embedding) as dist
    from document_chunks
    where embedding is not null
      and is_approved
      and (not only_current or status = 'current')
      and article_no is not null
    order by embedding <=> query_embedding
    limit greatest(match_count * 10, 80)
  ) c
  where (1 - dist) > match_threshold
  order by
    dist
    - (case when article_no ~ '^\d+조' then 0.08 else 0 end)
    + (case when article_no ~ '^(부칙|서식|별지)' then 0.05 else 0 end)
    + (case when doc_name ~* '\.(pdf|md|docx|hwp)$' then 0.10 else 0 end)
  limit match_count;
$function$;;
