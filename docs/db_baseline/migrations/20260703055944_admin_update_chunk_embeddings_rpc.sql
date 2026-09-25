-- 20260703055944 admin_update_chunk_embeddings_rpc

-- 승인 직후 브라우저에서 임베딩을 저장하기 위한 관리자 RPC.
-- anon은 document_chunks UPDATE가 RLS로 막혀 있고 batch_update_embeddings는 service_role 전용이므로,
-- admin_set_kb_approval과 동일한 비밀번호(SHA-256) 검증을 거치는 별도 통로를 둔다. (배경역사 #23)
CREATE OR REPLACE FUNCTION public.admin_update_chunk_embeddings(p_ids bigint[], p_embeddings text[], p_pwd text)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'extensions'
AS $function$
DECLARE n integer := 0; i integer;
BEGIN
  IF encode(digest(p_pwd, 'sha256'), 'hex') IS DISTINCT FROM '<REDACTED:hex_digest>' THEN
    RAISE EXCEPTION 'AUTH_FAILED';
  END IF;
  IF array_length(p_ids, 1) IS DISTINCT FROM array_length(p_embeddings, 1) THEN
    RAISE EXCEPTION 'LENGTH_MISMATCH';
  END IF;
  FOR i IN 1..coalesce(array_length(p_ids, 1), 0) LOOP
    UPDATE document_chunks SET embedding = p_embeddings[i]::vector WHERE id = p_ids[i];
    n := n + 1;
  END LOOP;
  RETURN n;
END;
$function$;;
