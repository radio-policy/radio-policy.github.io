-- 20260729180433 embedding_backfill_partial_indexes

-- 백필 조회(embedding IS NULL ... order by id limit N)가 부분 인덱스 없이 Seq Scan으로
-- 5.1초씩 걸렸다(EXPLAIN 실측, 캐시 적중 상태 / 0행 반환인데도). 배치마다 반복되니
-- 부하 시 statement timeout(57014)·PostgREST 500의 진원이 됐다.
-- 임베딩이 채워지면 인덱스에서 빠지므로 평상시 크기는 0에 수렴한다.
CREATE INDEX IF NOT EXISTS document_chunks_embedding_null_idx
  ON public.document_chunks (id) WHERE embedding IS NULL;

CREATE INDEX IF NOT EXISTS kb_chunks_embedding_null_idx
  ON public.kb_chunks (id) WHERE embedding IS NULL;

-- report_samples 백필도 같은 패턴을 쓴다
CREATE INDEX IF NOT EXISTS report_samples_embedding_null_idx
  ON public.report_samples (id) WHERE embedding IS NULL;;
