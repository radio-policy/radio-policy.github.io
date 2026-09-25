-- 20260615122455 custom_file_storage_setup

-- 원본 업로드 파일 보관용 컬럼
ALTER TABLE public.document_chunks ADD COLUMN IF NOT EXISTS file_path text;

-- 원본 파일 보관 버킷 (private)
INSERT INTO storage.buckets (id, name, public)
VALUES ('uploads', 'uploads', false)
ON CONFLICT (id) DO NOTHING;

-- 대시보드는 anon 키로 동작 → anon 역할에 uploads 버킷 read/write/delete 허용
DROP POLICY IF EXISTS "uploads anon insert" ON storage.objects;
CREATE POLICY "uploads anon insert" ON storage.objects
  FOR INSERT TO anon WITH CHECK (bucket_id = 'uploads');

DROP POLICY IF EXISTS "uploads anon select" ON storage.objects;
CREATE POLICY "uploads anon select" ON storage.objects
  FOR SELECT TO anon USING (bucket_id = 'uploads');

DROP POLICY IF EXISTS "uploads anon delete" ON storage.objects;
CREATE POLICY "uploads anon delete" ON storage.objects
  FOR DELETE TO anon USING (bucket_id = 'uploads');;
