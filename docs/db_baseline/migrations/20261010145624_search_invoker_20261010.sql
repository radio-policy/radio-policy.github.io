-- 20261010145624 search_invoker_20261010

-- search_invoker_20261010 — 보안 구현 C-3 (판정 Q3-b·Q6 ③(c), 운영자 결정 R3)
-- 검색 4개: search_path '' + 본문 스키마 한정(<=> 는 public 연산자라 OPERATOR(public.<=>)) + SECURITY INVOKER.
-- 공개 목록 2개(_in_doc·list_kb_guide_docs): search_path=public 그대로, INVOKER만.
-- 읽는 표 document_chunks(정책 public true)·kb_documents·kb_chunks(anon,authenticated true) → 노출·결과 같음.
-- SET 절이 있어 SQL 함수 인라인은 전후 모두 일어나지 않는다(계획은 본문 쿼리로 비교).
-- 되돌리기: 함수마다 alter function … security definer; (+ 검색 4는 설계도 20_functions.sql 판으로 재정의)
-- 적용 전 되돌리는 시험(고정 입력 결과 id·trgm 점수·KB 목록 md5·EXPLAIN 동일) 통과(10-10 23:5x).

select '[1,0]'::public.vector OPERATOR(public.<=>) '[0,1]'::public.vector;   -- vector 라이브러리 선로드(#185 — 없으면 SET hnsw.* 가 42501)

create or replace function public.match_chunks_semantic(query_embedding public.vector, match_threshold double precision default 0.5, match_count integer default 8, only_current boolean default true)
 returns table(id bigint, doc_name text, doc_category text, chunk_index integer, content text, notice_no text, article_no text, effective_date text, similarity double precision)
 language sql
 stable security invoker
 set "hnsw.ef_search" to '100'
 set search_path to ''
as $function$
  SELECT
    id, doc_name, doc_category, chunk_index, content,
    notice_no, article_no, effective_date,
    (1 - (embedding OPERATOR(public.<=>) query_embedding))::float AS similarity
  FROM public.document_chunks
  WHERE embedding IS NOT NULL
    AND is_approved
    AND (NOT only_current OR status = 'current')
    AND (1 - (embedding OPERATOR(public.<=>) query_embedding)) > match_threshold
  ORDER BY embedding OPERATOR(public.<=>) query_embedding
  LIMIT match_count;
$function$;

create or replace function public.match_chunks_semantic_exact(query_embedding public.vector, match_threshold double precision default 0.5, match_count integer default 8, only_current boolean default true)
 returns table(id bigint, doc_name text, doc_category text, chunk_index integer, content text, notice_no text, article_no text, effective_date text, similarity double precision)
 language sql
 stable security invoker
 set search_path to ''
as $function$
  select
    id, doc_name, doc_category, chunk_index, content,
    notice_no, article_no, effective_date,
    (1 - (embedding OPERATOR(public.<=>) query_embedding))::float as similarity
  from public.document_chunks
  where embedding is not null
    and is_approved
    and (not only_current or status = 'current')
    and (1 - (embedding OPERATOR(public.<=>) query_embedding)) > match_threshold
  order by (embedding OPERATOR(public.<=>) query_embedding) + 0.0
  limit match_count;
$function$;

create or replace function public.match_law_articles_semantic(query_embedding public.vector, match_threshold double precision default 0.0, match_count integer default 8, only_current boolean default true)
 returns table(id bigint, doc_name text, doc_category text, chunk_index integer, content text, notice_no text, article_no text, effective_date text, similarity double precision)
 language sql
 stable security invoker
 set "hnsw.ef_search" to '300'
 set search_path to ''
as $function$
  select id, doc_name, doc_category, chunk_index, content,
         notice_no, article_no, effective_date,
         (1 - dist)::float as similarity
  from (
    select id, doc_name, doc_category, chunk_index, content, notice_no, article_no, effective_date,
           (embedding OPERATOR(public.<=>) query_embedding) as dist
    from public.document_chunks
    where embedding is not null
      and is_approved
      and (not only_current or status = 'current')
      and article_no is not null
    order by embedding OPERATOR(public.<=>) query_embedding
    limit greatest(match_count * 30, 300)
  ) c
  where (1 - dist) > match_threshold
  order by
    dist
    - (case when article_no ~ '^\d+조' then 0.08 else 0 end)
    + (case when article_no ~ '^(부칙|서식|별지)' then 0.05 else 0 end)
    + (case when doc_name ~* '\.(pdf|md|docx|hwp)$' then 0.10 else 0 end)
  limit match_count;
$function$;

create or replace function public.search_chunks_trgm(query_text text, match_threshold double precision default 0.12, match_count integer default 8, only_current boolean default true)
 returns table(id bigint, doc_name text, doc_category text, chunk_index integer, content text, notice_no text, article_no text, effective_date text, trgm_score double precision)
 language sql
 stable security invoker
 set search_path to ''
as $function$
  SELECT
    id, doc_name, doc_category, chunk_index, content,
    notice_no, article_no, effective_date,
    extensions.word_similarity(query_text, content)::float AS trgm_score
  FROM public.document_chunks
  WHERE is_approved
    AND (NOT only_current OR status = 'current')
    AND extensions.word_similarity(query_text, content) > match_threshold
  ORDER BY trgm_score DESC
  LIMIT match_count;
$function$;

alter function public.match_chunks_semantic_in_doc(public.vector, text, integer) security invoker;
alter function public.list_kb_guide_docs() security invoker;;
