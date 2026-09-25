-- views — tools_db_baseline.py가 실DB에서 생성(손으로 고치지 말 것), 비밀 마스킹됨

create or replace view public.kb_quality_article_parse as
 SELECT doc_name,
    count(*)::integer AS total_chunks,
    count(*) FILTER (WHERE article_no IS NOT NULL AND article_no <> ''::text)::integer AS parsed_chunks,
    round(100.0 * count(*) FILTER (WHERE article_no IS NOT NULL AND article_no <> ''::text)::numeric / count(*)::numeric, 1) AS parse_pct
   FROM document_chunks c
  WHERE status = 'current'::text AND doc_name ~ '\(제[0-9,\-]+호\)\([0-9]{8}\)$'::text AND doc_name !~ '공고\)'::text AND (doc_category <> ALL (ARRAY['보도자료'::text, '회의록'::text, '해외동향'::text, '추가지식'::text, 'ITU-R'::text])) AND NOT (EXISTS ( SELECT 1
           FROM kb_quality_ack a
          WHERE a.doc_name = c.doc_name))
  GROUP BY doc_name
 HAVING count(*) >= 3
  ORDER BY (round(100.0 * count(*) FILTER (WHERE article_no IS NOT NULL AND article_no <> ''::text)::numeric / count(*)::numeric, 1)), (count(*)::integer) DESC
 LIMIT 15;

create or replace view public.kb_quality_low_docs as
 WITH doc AS (
         SELECT document_chunks.doc_name,
            document_chunks.doc_category,
            sum(length(document_chunks.content))::integer AS chars,
            count(*)::integer AS chunks,
            bool_or(document_chunks.content ~~ '%자세한 내용은%버튼을 이용%'::text) AS is_stub
           FROM document_chunks
          WHERE document_chunks.status = 'current'::text
          GROUP BY document_chunks.doc_name, document_chunks.doc_category
        ), k AS (
         SELECT doc.doc_name,
            doc.doc_category,
            doc.chars,
            doc.chunks,
            doc.is_stub,
                CASE
                    WHEN doc.doc_name ~ '\.(pdf|docx|hwp|hwpx|pptx)$'::text THEN '바이너리업로드'::text
                    WHEN doc.doc_name ~ '\.(md|txt)$'::text THEN '텍스트업로드'::text
                    WHEN doc.doc_name ~ '공고\)'::text THEN '공고'::text
                    WHEN doc.doc_name ~ '고시\)'::text THEN '고시'::text
                    ELSE '법령'::text
                END AS doc_kind
           FROM doc
        ), m AS (
         SELECT k.doc_name,
            k.doc_category,
            k.chars,
            k.chunks,
            k.is_stub,
            k.doc_kind,
                CASE k.doc_kind
                    WHEN '텍스트업로드'::text THEN 800
                    WHEN '공고'::text THEN 300
                    WHEN '고시'::text THEN 300
                    ELSE 2000
                END AS min_chars
           FROM k
        )
 SELECT doc_name,
    doc_category,
    chars,
    chunks,
    doc_kind,
    min_chars
   FROM m
  WHERE chars < min_chars AND NOT (is_stub AND chars < 300) AND NOT (EXISTS ( SELECT 1
           FROM kb_quality_ack a
          WHERE a.doc_name = m.doc_name))
  ORDER BY chars
 LIMIT 15;
