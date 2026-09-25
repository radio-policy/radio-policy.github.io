-- 20260925172658 anon_write_lockdown_20260926

-- §4-4-8 anon 쓰기 봉쇄 (#226, 2026-09-26, 운영자 결정 D1~D4·D6 권고안, D5 기각, documents 버킷 유지)
-- D1. document_chunks: 업로드는 승인 계정만, 여전히 승인 대기(is_approved=false)로만
drop policy if exists doc_chunks_ins on public.document_chunks;
create policy doc_chunks_ins_approved on public.document_chunks
  for insert to authenticated
  with check (coalesce(is_approved, false) = false and public.is_approved_user());

-- D3. kb_quality_ack: '확인함'은 관리자만
drop policy if exists kb_quality_ack_ins on public.kb_quality_ack;
create policy kb_quality_ack_ins_admin on public.kb_quality_ack
  for insert to authenticated
  with check (public.is_admin());

-- D4. chat_logs: 본인 명의 + 승인 계정만
alter policy chat_logs_ins_auth on public.chat_logs
  with check (user_id = auth.uid() and public.is_approved_user());

-- D2. Storage uploads: 올리기=승인 계정, 지우기=관리자, 내려받기(서명 URL)=누구나
drop policy if exists "uploads anon insert" on storage.objects;
drop policy if exists "uploads anon delete" on storage.objects;
drop policy if exists "uploads anon select" on storage.objects;
create policy uploads_ins_approved on storage.objects
  for insert to authenticated
  with check (bucket_id = 'uploads' and public.is_approved_user());
create policy uploads_del_admin on storage.objects
  for delete to authenticated
  using (bucket_id = 'uploads' and public.is_admin());
create policy uploads_sel_all on storage.objects
  for select to anon, authenticated
  using (bucket_id = 'uploads');

-- D6. 표 권한 명시(#214) — anon 쓰기 회수, 읽기 유지
revoke insert, update, delete, truncate on public.document_chunks from anon;
revoke insert, update, delete, truncate on public.kb_quality_ack  from anon;
revoke insert, update, delete, truncate on public.chat_logs       from anon;
revoke insert, update, delete, truncate on public.teams           from anon;
grant  select on public.document_chunks, public.kb_quality_ack to anon, authenticated;
grant  insert on public.document_chunks, public.kb_quality_ack, public.chat_logs to authenticated;
grant  all    on public.document_chunks, public.kb_quality_ack, public.chat_logs, public.teams to service_role;;
