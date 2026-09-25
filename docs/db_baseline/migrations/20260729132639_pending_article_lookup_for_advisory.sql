-- 20260729132639 pending_article_lookup_for_advisory

-- Phase 3 — 자문 답변에 '시행예정 조문'을 덧붙이기 위한 조회 함수.
--
-- 짝짓기 축은 law_id가 아니라 law_pending.watch_doc_name ↔ doc_name 문자열 조인이다.
-- (current 문서의 97%가 PDF 업로드본이라 law_id가 NULL이어서 law_id 조인은 3쌍밖에 못 만든다)
--
-- article_no에는 조문 제목이 붙어 있어("48조의3(침해사고의 신고 등)") 제목이 개정되면
-- 매칭이 깨진다. 조번호만 잘라 비교한다 — 이렇게 하면 현행 조문의 100%가 대응본을 찾는다.
CREATE OR REPLACE FUNCTION public.norm_article_key(a text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT (regexp_match(regexp_replace(coalesce(a, ''), '^제', ''),
                       '^([0-9]+조(?:의[0-9]+)?)'))[1];
$$;

-- 인용된 현행 조문에 대응하는 시행예정 조문 본문을 돌려준다.
-- 내용 diff는 하지 않는다 — 현행본 다수가 PDF 추출본이라 줄바꿈·따옴표·날짜 표기가 달라
-- 문자열 비교는 위양성 100%가 난다. 양쪽 원문을 나란히 모델에 주고 판단시키는 편이 정확하다.
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
  SELECT p.law_name, p.enf_date, p.law_no, p.doc_name, p.watch_doc_name,
         c.article_no,
         string_agg(c.content, E'\n' ORDER BY c.chunk_index)
  FROM law_pending p
  JOIN document_chunks c
    ON c.doc_name = p.doc_name AND c.status = 'pending'
  WHERE p.sync_state IN ('detected', 'loaded')
    AND p.watch_doc_name = ANY(p_docs)
    AND public.norm_article_key(c.article_no) = ANY(p_article_keys)
  GROUP BY p.law_name, p.enf_date, p.law_no, p.doc_name, p.watch_doc_name, c.article_no
  ORDER BY p.enf_date, c.article_no
  LIMIT p_limit;
$$;

-- 조문이 매칭되지 않아도 "이 법령은 언제부터 개정 시행 예정"은 알려줄 수 있어야 한다.
CREATE OR REPLACE FUNCTION public.pending_versions_for_docs(p_docs text[])
RETURNS TABLE (law_name text, current_doc text, law_no text, enf_date text, loaded boolean)
LANGUAGE sql STABLE AS $$
  SELECT p.law_name, p.watch_doc_name, p.law_no, p.enf_date,
         (p.sync_state = 'loaded')
  FROM law_pending p
  WHERE p.sync_state IN ('detected', 'loaded')
    AND p.watch_doc_name = ANY(p_docs)
  ORDER BY p.law_name, p.enf_date;
$$;;
