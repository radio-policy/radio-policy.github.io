-- 20260924191955 hnsw_cleanup_219_reindex

-- #219: 옛 판 임베딩을 비운 뒤 HNSW 재구축 1회(야간, 비동시 — MCP는 트랜잭션이라 CONCURRENTLY 불가 #72).
-- 디스크 여유 6.2GB 확인(Management API config/disk/util, 04:1x), 진행 중 쿼리 0.
set local maintenance_work_mem = '256MB';
reindex index public.document_chunks_embedding_hnsw_idx;;
