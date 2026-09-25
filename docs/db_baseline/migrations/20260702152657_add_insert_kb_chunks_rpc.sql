-- 20260702152657 add_insert_kb_chunks_rpc

-- 한 문서의 청크들을 임베딩과 함께 일괄 삽입(text→vector 캐스팅, batch_update_embeddings와 동일 패턴).
create or replace function public.insert_kb_chunks(
  p_doc_id bigint, p_contents text[], p_embeddings text[]
) returns int language plpgsql as $$
declare i int; n int;
begin
  n := coalesce(array_length(p_contents,1),0);
  for i in 1..n loop
    insert into public.kb_chunks(doc_id, chunk_idx, content, embedding)
    values (p_doc_id, i-1, p_contents[i], p_embeddings[i]::vector);
  end loop;
  return n;
end; $$;;
