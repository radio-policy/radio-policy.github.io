-- 20260729132719 pending_article_lookup_dedupe

-- 노이즈 제거 2종:
--  ① "제N조 삭제 <연도>" 한 줄짜리 조문 — 인용 가치가 없다.
--  ② 같은 조문이 여러 시행일에 걸쳐 있으면서 본문이 동일한 경우 — 예컨대 정보통신망법
--     제48조의3은 2026.10.1과 2027.4.1 통합본이 같다. 시행일 순으로 훑어 직전 판과
--     내용이 같으면 버린다. (시행예정본끼리는 전부 법제처 API 적재본이라 문자열 비교가
--     신뢰 가능하다. 반면 현행본과의 비교는 현행 다수가 PDF 추출본이라 위양성이 나므로
--     하지 않는다 — 첫 시행예정본은 항상 남기고 실제 변경 여부 판단은 모델에 맡긴다.)
CREATE OR REPLACE FUNCTION public.fetch_pending_articles(
  p_docs         text[],
  p_article_keys text[],
  p_limit        integer DEFAULT 24
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
  WITH art AS (
    SELECT p.law_name, p.enf_date, p.law_no, p.doc_name AS pending_doc,
           p.watch_doc_name AS current_doc, c.article_no,
           public.norm_article_key(c.article_no) AS akey,
           string_agg(c.content, E'\n' ORDER BY c.chunk_index) AS content
    FROM law_pending p
    JOIN document_chunks c
      ON c.doc_name = p.doc_name AND c.status = 'pending'
    WHERE p.sync_state IN ('detected', 'loaded')
      AND p.watch_doc_name = ANY(p_docs)
      AND public.norm_article_key(c.article_no) = ANY(p_article_keys)
    GROUP BY 1,2,3,4,5,6,7
  ), dedup AS (
    SELECT art.*,
           lag(regexp_replace(content, '\s+', '', 'g'))
             OVER (PARTITION BY current_doc, akey ORDER BY enf_date) AS prev_norm
    FROM art
  )
  SELECT law_name, enf_date, law_no, pending_doc, current_doc, article_no, content
  FROM dedup
  WHERE content !~ '^제[0-9]+조(의[0-9]+)?\s*삭제'
    AND (prev_norm IS NULL OR prev_norm <> regexp_replace(content, '\s+', '', 'g'))
  ORDER BY enf_date, article_no
  LIMIT p_limit;
$$;;
