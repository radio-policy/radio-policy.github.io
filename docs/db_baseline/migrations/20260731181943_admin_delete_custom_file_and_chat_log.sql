-- 20260731181943 admin_delete_custom_file_and_chat_log

-- 대시보드 삭제 무성 실패 수정 (배경역사 #48)
-- document_chunks·chat_logs는 RLS가 켜져 있으나 DELETE 정책이 없어,
-- 프런트의 직접 delete()가 오류 없이 0건 삭제로 끝났다(PostgREST가 성공으로 응답).
-- admin_delete_kb_document와 동일한 패턴(security definer + sha256 검증 + 행수 반환).
-- 반환값(삭제 행수)을 프런트가 0으로 판정해 실패를 드러내는 것이 핵심이다.

create or replace function public.admin_delete_custom_file(p_doc_name text, p_pwd text)
returns integer
language plpgsql
security definer
set search_path to 'public', 'extensions'
as $function$
DECLARE n integer;
BEGIN
  IF encode(digest(p_pwd, 'sha256'), 'hex') IS DISTINCT FROM '<REDACTED:hex_digest>' THEN
    RAISE EXCEPTION 'AUTH_FAILED';
  END IF;
  -- 카테고리 조건 필수 — 다른 카테고리의 동명 문서를 지우지 않기 위함
  DELETE FROM document_chunks
   WHERE doc_category = '추가지식' AND doc_name = p_doc_name;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$function$;

create or replace function public.admin_delete_chat_log(p_id uuid, p_pwd text)
returns integer
language plpgsql
security definer
set search_path to 'public', 'extensions'
as $function$
DECLARE n integer;
BEGIN
  IF encode(digest(p_pwd, 'sha256'), 'hex') IS DISTINCT FROM '<REDACTED:hex_digest>' THEN
    RAISE EXCEPTION 'AUTH_FAILED';
  END IF;
  DELETE FROM chat_logs WHERE id = p_id;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$function$;

grant execute on function public.admin_delete_custom_file(text, text) to anon, authenticated;
grant execute on function public.admin_delete_chat_log(uuid, text) to anon, authenticated;;
