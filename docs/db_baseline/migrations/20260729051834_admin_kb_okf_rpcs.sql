-- 20260729051834 admin_kb_okf_rpcs

-- 대시보드 승인 시 OKF 요약을 kb_documents/kb_chunks에 적재하기 위한 관리자 RPC 2종.
-- 기존 admin_* 패턴과 동일: SECURITY DEFINER + 비밀번호 sha256 검증(RLS 우회는 검증 통과 시에만).

CREATE OR REPLACE FUNCTION public.admin_upsert_kb_document(
  p_pwd text, p_dedup_key text, p_title text, p_concept_type text, p_family text,
  p_law_type text, p_law_number text, p_enforcement_date text,
  p_competent_authority text, p_path text, p_description text, p_body_md text)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'extensions'
AS $function$
DECLARE new_id bigint;
BEGIN
  IF encode(digest(p_pwd, 'sha256'), 'hex') IS DISTINCT FROM '<REDACTED:hex_digest>' THEN
    RAISE EXCEPTION 'AUTH_FAILED';
  END IF;
  IF p_path IS NULL OR p_title IS NULL OR p_body_md IS NULL THEN
    RAISE EXCEPTION 'MISSING_FIELDS';
  END IF;
  -- 동일 path 재적재는 덮어쓰기(idempotent) — cascade로 kb_chunks도 정리
  DELETE FROM kb_documents WHERE path = p_path;
  -- add_law.py의 on_readd_rule과 동일: 같은 dedup_key의 기존 current(다른 법령번호)는 superseded 처리
  IF p_dedup_key IS NOT NULL AND p_dedup_key <> '' THEN
    UPDATE kb_documents
       SET status = 'superseded', superseded_by = p_law_number
     WHERE dedup_key = p_dedup_key AND status = 'current'
       AND law_number IS DISTINCT FROM p_law_number;
  END IF;
  INSERT INTO kb_documents
    (dedup_key, title, concept_type, family, law_type, law_number, enforcement_date,
     competent_authority, status, path, description, body_md)
  VALUES
    (nullif(p_dedup_key,''), p_title, nullif(p_concept_type,''), nullif(p_family,''),
     nullif(p_law_type,''), nullif(p_law_number,''), nullif(p_enforcement_date,''),
     nullif(p_competent_authority,''), 'current', p_path, nullif(p_description,''), p_body_md)
  RETURNING id INTO new_id;
  RETURN new_id;
END;
$function$;

CREATE OR REPLACE FUNCTION public.admin_insert_kb_chunks(
  p_pwd text, p_doc_id bigint, p_contents text[], p_embeddings text[])
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'extensions'
AS $function$
DECLARE n integer; i integer;
BEGIN
  IF encode(digest(p_pwd, 'sha256'), 'hex') IS DISTINCT FROM '<REDACTED:hex_digest>' THEN
    RAISE EXCEPTION 'AUTH_FAILED';
  END IF;
  IF array_length(p_contents, 1) IS DISTINCT FROM array_length(p_embeddings, 1) THEN
    RAISE EXCEPTION 'LENGTH_MISMATCH';
  END IF;
  n := coalesce(array_length(p_contents, 1), 0);
  FOR i IN 1..n LOOP
    INSERT INTO kb_chunks (doc_id, chunk_idx, content, embedding)
    VALUES (p_doc_id, i - 1, p_contents[i], p_embeddings[i]::vector);
  END LOOP;
  RETURN n;
END;
$function$;;
