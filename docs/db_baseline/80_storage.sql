-- storage — tools_db_baseline.py가 실DB에서 생성(손으로 고치지 말 것), 비밀 마스킹됨

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) values ('documents', 'documents', true, null, NULL) on conflict (id) do nothing;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) values ('uploads', 'uploads', false, null, NULL) on conflict (id) do nothing;
