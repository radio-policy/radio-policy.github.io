-- 20260803114118 law_semantic_exclude_tables

-- 별표·별지도 제외 (2026-08-03, 실측 2차)
-- 부칙·서식만 뺐더니 이번엔 별표·별지가 상위를 독식했다: "기지국 개설 허가 절차"에서
-- 「별지 8(공용화 및 환경친화형 기지국)」이 1~3위를 차지하고 정작 전파법 21조(무선국 개설허가
-- 등의 절차)가 5위로 밀렸다. 별표는 긴 표라서 여러 어휘를 조금씩 품어 아무 질문에나 약하게
-- 걸린다(문서 길이 편향). 의미 검색 경로에서만 제외하고, 키워드 검색(searchLawArticles)은
-- 그대로 두므로 "별표 N" 같이 명시적으로 찾을 때는 여전히 나온다.
create or replace function public.match_law_articles_semantic(
  query_embedding vector,
  match_threshold double precision default 0.0,
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
    and article_no is not null
    and article_no !~ '^(부칙|서식|별표|별지)'
    and doc_name !~* '\.(pdf|md|docx|hwp)$'
    and (1 - (embedding <=> query_embedding)) > match_threshold
  order by (embedding <=> query_embedding) + 0.0
  limit match_count;
$function$;;
