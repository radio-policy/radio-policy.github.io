-- 20260729171620 kb_document_list_status_and_bureau_rename

-- ① 지식베이스 목록이 구버전·시행예정본을 현행본과 나란히 보여줘 "같은 법령이 2개"로 보였다.
--    status를 반환해 UI가 구분·필터할 수 있게 한다.
--    (OUT 파라미터가 바뀌므로 CREATE OR REPLACE로는 안 되고 DROP이 필요하다)
DROP FUNCTION IF EXISTS public.list_kb_documents();
CREATE FUNCTION public.list_kb_documents()
RETURNS TABLE(doc_category text, doc_name text, chunks bigint, embedded bigint,
              approved boolean, status text)
LANGUAGE sql STABLE AS $function$
  SELECT min(doc_category) AS doc_category, doc_name, count(*) AS chunks,
         count(*) FILTER (WHERE embedding IS NOT NULL) AS embedded,
         bool_and(is_approved) AS approved,
         min(status) AS status
  FROM document_chunks
  WHERE doc_category IS DISTINCT FROM '보도자료'
  GROUP BY doc_name
  ORDER BY doc_name;
$function$;

-- ② 부령 문서명 복원. build_doc_name이 법제처 '법령구분명'(= "부령")을 쓰는 바람에
--    소관부처 접두가 사라져 '전파법 시행규칙(과학기술정보통신부령)' → '(부령)'이 됐다.
UPDATE document_chunks SET doc_name = doc_name || ' [PDF원본]'
 WHERE status = 'superseded' AND doc_name IN (
   '전파법 시행규칙(과학기술정보통신부령)(제00156호)(20251001)',
   '정보통신망 이용촉진 및 정보보호 등에 관한 법률 시행규칙(과학기술정보통신부령)(제00071호)(20210331)',
   '정보통신산업 진흥법 시행규칙(과학기술정보통신부령)(제00001호)(20170726)');

UPDATE document_chunks SET doc_name = replace(doc_name, '(부령)', '(과학기술정보통신부령)')
 WHERE doc_name IN ('전파법 시행규칙(부령)(제00156호)(20251001)',
                    '정보통신망 이용촉진 및 정보보호 등에 관한 법률 시행규칙(부령)(제00071호)(20210331)',
                    '정보통신산업 진흥법 시행규칙(부령)(제00001호)(20170726)');
UPDATE document_chunks SET doc_name = replace(doc_name, '(부령)', '(행정안전부령)')
 WHERE doc_name = '재난 및 안전관리 기본법 시행규칙(부령)(제00567호)(20250708)';

UPDATE law_watch SET doc_name = replace(doc_name, '(부령)', '(과학기술정보통신부령)')
 WHERE doc_name LIKE '%(부령)%' AND doc_name NOT LIKE '재난 및 안전관리%';
UPDATE law_watch SET doc_name = replace(doc_name, '(부령)', '(행정안전부령)')
 WHERE doc_name LIKE '재난 및 안전관리%(부령)%';
UPDATE law_pending SET watch_doc_name = replace(watch_doc_name, '(부령)', '(과학기술정보통신부령)')
 WHERE watch_doc_name LIKE '%(부령)%' AND watch_doc_name NOT LIKE '재난 및 안전관리%';
UPDATE law_pending SET watch_doc_name = replace(watch_doc_name, '(부령)', '(행정안전부령)')
 WHERE watch_doc_name LIKE '재난 및 안전관리%(부령)%';;
