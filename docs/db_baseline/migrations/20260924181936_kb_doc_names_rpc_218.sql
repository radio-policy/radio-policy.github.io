-- 20260924181936 kb_doc_names_rpc_218

-- #218 (개선안 §4-2-12 단계 B-마): KB 문서명 목록을 한 번에. 파이썬 7곳이 document_chunks를 1,000행씩
-- 수십 페이지 훑어 문서명을 모으던 것(현행 42페이지 4.6초, 일부는 order 없이 range)을 대체. DB 실행 ≈0.06초.
create or replace function public.kb_doc_names(p_status text default null, p_category text default null)
returns table(doc_name text, doc_category text)
language sql stable
set search_path = public, pg_catalog
as $$
  select c.doc_name, min(c.doc_category) as doc_category
  from public.document_chunks c
  where (p_status is null or c.status = p_status)
    and (p_category is null or c.doc_category = p_category)
  group by c.doc_name
  order by c.doc_name;
$$;
comment on function public.kb_doc_names(text, text) is
  'KB 문서명 목록(선택: status·doc_category 필터). 서버 전용 — kb_store.list_docs가 부른다 (#218)';
revoke all on function public.kb_doc_names(text, text) from public, anon, authenticated;
grant execute on function public.kb_doc_names(text, text) to service_role;;
