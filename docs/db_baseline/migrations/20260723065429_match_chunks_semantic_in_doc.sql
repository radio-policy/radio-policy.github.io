-- 20260723065429 match_chunks_semantic_in_doc

-- 특정 법령 문서 안에서의 시맨틱 검색 (법령 관계도 관련 조문 찾기용)
create or replace function public.match_chunks_semantic_in_doc(
  query_embedding vector,
  p_doc_name text,
  match_count integer default 12
)
returns table(id bigint, doc_name text, chunk_index integer, content text, article_no text, similarity double precision)
language sql stable security definer
set search_path = public
as $$
  select id, doc_name, chunk_index, content, article_no,
         (1 - (embedding <=> query_embedding))::float as similarity
  from document_chunks
  where doc_name = p_doc_name
    and embedding is not null
  order by embedding <=> query_embedding
  limit match_count;
$$;

grant execute on function public.match_chunks_semantic_in_doc(vector, text, integer) to anon, authenticated;;
