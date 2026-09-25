-- 20260803114030 add_match_law_articles_semantic

-- /law 전용 의미 검색 — **실제 조문만** 대상 (2026-08-03)
-- 왜: match_chunks_semantic은 전 코퍼스를 훑는데 실제 조문은 33%뿐이다
--     (조문번호 없음 40.6% = 보도자료·회의록·논문 / 별표 17.9% / 부칙 5.5% / 서식 2.9%).
--     "5G 커버리지 맵 공개" 질의에서 상위 12건이 전부 부칙·별표·서식이라 정답 고시가 40위 밖으로
--     밀렸다. voyage-law-2로 바꿔도 7위까지만 올라와 해결이 안 됐다(실측 A/B) —
--     모델 문제가 아니라 **검색 대상 문제**였다.
-- 부칙(시행일 한 줄)·서식은 제외, 별표는 유지 — 별표에는 기술기준·대상기자재 같은 실질 내용이
-- 들어 있어 통째로 버리면 진짜 근거를 잃는다.
--
-- ★ `+ 0.0`은 오타가 아니라 의도적으로 **HNSW 인덱스를 쓰지 않게** 하는 장치다.
--   HNSW는 ef_search 기본값 탓에 후보를 ~40개만 훑어서, 필터를 걸면 남는 게 몇 건 안 된다
--   (실측: match_count=300을 줘도 33행만 반환). ef_search를 올리려면 슈퍼유저 권한이 필요해
--   (Supabase 관리형에서는 불가) 전수 정확 검색으로 간다. 조문 대상이 ~1.5만 건이라
--   실측 응답이 100ms 안쪽이고, 근사 검색의 누락 위험이 아예 없어진다.
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
    and article_no !~ '^(부칙|서식)'
    and doc_name !~* '\.(pdf|md|docx|hwp)$'
    and (1 - (embedding <=> query_embedding)) > match_threshold
  order by (embedding <=> query_embedding) + 0.0
  limit match_count;
$function$;
grant execute on function public.match_law_articles_semantic(vector, double precision, integer, boolean) to anon, authenticated, service_role;;
