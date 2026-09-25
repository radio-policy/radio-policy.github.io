-- 20260617045214 kb_admin_approval_rpcs

-- 승인/삭제는 RLS로 anon 직접 UPDATE/DELETE가 막혀 있으므로,
-- 비밀번호를 서버에서 검증하는 SECURITY DEFINER RPC로 처리한다.
-- 평문 비번은 클라이언트가 사용자 입력값으로만 전달(소스엔 해시만 존재).

CREATE OR REPLACE FUNCTION public.admin_set_kb_approval(p_doc_name text, p_approved boolean, p_pwd text)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, extensions
AS $function$
DECLARE n integer;
BEGIN
  IF encode(digest(p_pwd, 'sha256'), 'hex') IS DISTINCT FROM '<REDACTED:hex_digest>' THEN
    RAISE EXCEPTION 'AUTH_FAILED';
  END IF;
  UPDATE document_chunks SET is_approved = p_approved WHERE doc_name = p_doc_name;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$function$;

CREATE OR REPLACE FUNCTION public.admin_delete_kb_document(p_doc_name text, p_pwd text)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, extensions
AS $function$
DECLARE n integer;
BEGIN
  IF encode(digest(p_pwd, 'sha256'), 'hex') IS DISTINCT FROM '<REDACTED:hex_digest>' THEN
    RAISE EXCEPTION 'AUTH_FAILED';
  END IF;
  DELETE FROM document_chunks WHERE doc_name = p_doc_name;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$function$;

GRANT EXECUTE ON FUNCTION public.admin_set_kb_approval(text, boolean, text) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.admin_delete_kb_document(text, text) TO anon, authenticated;;
