-- 20260805104355 match_law_articles_weighted

-- /law 조문 검색: 하드 필터 → 가중치 (#88)
--
-- 종전: article_no !~ '^(부칙|서식|별표|별지)' 로 **완전 배제**했다.
--       ① 「붙임」이 목록에 빠져 1,191개가 그대로 통과 — 「주파수 분배표」 붙임이 리파밍 검색에서
--          2~6위를 독식한 실측 사례가 있었다.
--       ② 배제된 것은 **영영 도달할 수 없다.** 조문이 가리키지 않는 별표가 463개 중 65개(14%)이고,
--          「시행일이 언제부터인가」의 답은 부칙에 있다.
--
-- 실측이 하드 필터가 불필요함을 보여줬다 — 필터 없이 원본 유사도를 재면 **조문이 이미 위에 있다**:
--     "주파수 회수 또는 재배치 절차"  조문 0.570 vs 별표 0.531 (+0.039)
--     "과징금 산정 기준"              조문 0.591 vs 별표 0.558 (+0.033)
--   (앞서 근거로 삼던 "정답 조문 0.418 vs 무관 별표 0.54"는 5G 커버리지 맵 특정 사례였고 일반 경향이 아니다)
--
-- 그래서 배제 대신 **가점/감점으로 순위만 정리**한다. 아무것도 사라지지 않는다.
--   조문(^N조)          +0.08  ← 실측 격차(0.03~0.04)의 약 2배. 어쩌다 밀려도 뒤집을 수 있는 크기
--   별표·붙임              0   ← 기준
--   부칙·서식·별지      −0.05  ← 운영자: "law는 부칙이나 서식이 그리 우선순위가 되는 건 아니야"
--   파일 문서(pdf/md/…) −0.10  ← 보도자료·회의록·ITU-R PDF는 /law의 답이 아니다
--
-- ⚠️ similarity 반환값에는 가중치를 섞지 않는다. 호출부(rag.ts)가 이 값을 표시·비교에 쓰므로
--    "왜 0.531이 0.481로 보이지" 같은 혼선을 막는다. 정렬에만 반영한다.
-- ⚠️ ORDER BY의 `+ 0.0`은 유지 — HNSW 인덱스를 무력화해 전수 정밀 스캔을 강제한다.
--    이게 없으면 ef_search 기본값 탓에 상위 40건만 훑어 가중치가 무의미해진다.
-- ⚠️ match_threshold는 **가중치 적용 전 원본 유사도** 기준으로 판정한다(호출부는 0.0을 쓴다).
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
language sql
stable
security definer
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
    and (1 - (embedding <=> query_embedding)) > match_threshold
  order by
    ((embedding <=> query_embedding) + 0.0)
    - (case when article_no ~ '^\d+조' then 0.08 else 0 end)
    + (case when article_no ~ '^(부칙|서식|별지)' then 0.05 else 0 end)
    + (case when doc_name ~* '\.(pdf|md|docx|hwp)$' then 0.10 else 0 end)
  limit match_count;
$function$;

comment on function public.match_law_articles_semantic is
  '/law 조문 의미검색(#88). 배제가 아니라 가중치 — 조문 +0.08 / 부칙·서식·별지 −0.05 / 파일문서 −0.10. similarity는 원본값(가중치 미반영), 정렬에만 적용. ORDER BY의 +0.0은 HNSW 무력화(전수 스캔)이므로 제거 금지.';;
