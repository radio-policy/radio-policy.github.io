-- 20260923093310 rag_search_tuning_step2b_law_semantic_window_300

SELECT '[1,0]'::vector <=> '[0,1]'::vector;
-- 후보 폭 80 → 300: 가산점(조문 -0.08 vs 서식/별지 +0.05)으로 거리순 122·207위 본조문이 상위 8에 들던 사례(표본 74778)를 보존하기 위함.
CREATE OR REPLACE FUNCTION public.match_law_articles_semantic(query_embedding vector, match_threshold double precision DEFAULT 0.0, match_count integer DEFAULT 8, only_current boolean DEFAULT true)
 RETURNS TABLE(id bigint, doc_name text, doc_category text, chunk_index integer, content text, notice_no text, article_no text, effective_date text, similarity double precision)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET hnsw.ef_search = 300
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
    limit greatest(match_count * 30, 300)
  ) c
  where (1 - dist) > match_threshold
  order by
    dist
    - (case when article_no ~ '^\d+조' then 0.08 else 0 end)
    + (case when article_no ~ '^(부칙|서식|별지)' then 0.05 else 0 end)
    + (case when doc_name ~* '\.(pdf|md|docx|hwp)$' then 0.10 else 0 end)
  limit match_count;
$function$;;
