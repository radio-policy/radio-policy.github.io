-- 20260913184055 lawmap_backup_before_c_section_fix

-- 2026-09-14 C절(폐지판본·노드타입·허브설명·kb 동기화) 수정 전 원본 보존.
-- 롤백 근거는 scratchpad/lawmap_review/_rollback_20260914.sql
create table if not exists law_graph_nodes_bak_20260914 as
  select id, name, node_type, doc_name, description, now() as backed_up_at
    from law_graph_nodes;

create table if not exists law_graph_edges_bak_20260914 as
  select id, source_id, target_id, relation_type, description, source, weight, now() as backed_up_at
    from law_graph_edges;;
