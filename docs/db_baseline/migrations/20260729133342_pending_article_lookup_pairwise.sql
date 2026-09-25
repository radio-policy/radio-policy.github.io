-- 20260729133342 pending_article_lookup_pairwise

-- 결함 수정: 문서 배열과 조번호 배열을 따로 넘기면 교차곱이 된다.
-- 실제 사례 — 시행령 제58조의2(침해사고 신고 절차)를 인용했더니 본법 제58조의2
-- (구매자정보 제공 요청)의 시행예정본이 딸려 왔고, 보도자료 청크의 '제6조·제10조'가
-- 정보통신망법 본법의 6조·10조를 끌어왔다. (문서, 조번호) 쌍으로 매칭해야 한다.
DROP FUNCTION IF EXISTS public.fetch_pending_articles(text[], text[], integer);

CREATE OR REPLACE FUNCTION public.fetch_pending_articles(
  p_pairs jsonb,              -- [{"doc":"<현행 doc_name>","key":"48조의3"}, ...]
  p_limit integer DEFAULT 16
)
RETURNS TABLE (
  law_name    text,
  enf_date    text,
  law_no      text,
  pending_doc text,
  current_doc text,
  article_no  text,
  content     text
)
LANGUAGE sql STABLE AS $$
  WITH want AS (
    SELECT DISTINCT e->>'doc' AS doc, e->>'key' AS akey
    FROM jsonb_array_elements(p_pairs) e
    WHERE coalesce(e->>'doc','') <> '' AND coalesce(e->>'key','') <> ''
  ), art AS (
    SELECT p.law_name, p.enf_date, p.law_no, p.doc_name AS pending_doc,
           p.watch_doc_name AS current_doc, c.article_no, w.akey,
           string_agg(c.content, E'\n' ORDER BY c.chunk_index) AS content
    FROM want w
    JOIN law_pending p
      ON p.watch_doc_name = w.doc AND p.sync_state IN ('detected', 'loaded')
    JOIN document_chunks c
      ON c.doc_name = p.doc_name AND c.status = 'pending'
     AND public.norm_article_key(c.article_no) = w.akey
    GROUP BY 1,2,3,4,5,6,7
  ), dedup AS (
    SELECT art.*,
           lag(regexp_replace(content, '\s+', '', 'g'))
             OVER (PARTITION BY current_doc, akey ORDER BY enf_date, article_no) AS prev_norm
    FROM art
  )
  SELECT law_name, enf_date, law_no, pending_doc, current_doc, article_no, content
  FROM dedup
  WHERE content !~ '^제[0-9]+조(의[0-9]+)?\s*삭제'
    AND (prev_norm IS NULL OR prev_norm <> regexp_replace(content, '\s+', '', 'g'))
  ORDER BY enf_date, article_no
  LIMIT p_limit;
$$;;
