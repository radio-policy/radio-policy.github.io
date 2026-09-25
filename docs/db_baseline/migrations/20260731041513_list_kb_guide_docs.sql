-- 20260731041513 list_kb_guide_docs

-- 실무 안내 탭 목록용. body_md(203건 681kB)를 브라우저로 내려받지 않기 위해
-- 표 포함 여부·청크 수만 서버에서 계산해 돌려준다.
create or replace function public.list_kb_guide_docs()
returns table (
  id bigint, title text, path text, description text,
  concept_type text, competent_authority text,
  chunks bigint, has_table boolean
)
language sql
stable
security definer
set search_path = public
as $$
  select d.id, d.title, d.path, d.description,
         d.concept_type, d.competent_authority,
         coalesce(c.n, 0) as chunks,
         (d.body_md ~ '\n\s*\|.*\|') as has_table
  from kb_documents d
  left join (select doc_id, count(*) n from kb_chunks group by doc_id) c on c.doc_id = d.id
  where d.status = 'current'
  order by d.path;
$$;

grant execute on function public.list_kb_guide_docs() to anon, authenticated;;
