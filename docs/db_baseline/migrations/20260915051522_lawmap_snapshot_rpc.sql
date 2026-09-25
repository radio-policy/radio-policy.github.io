-- 20260915051522 lawmap_snapshot_rpc

-- 관계도 노드·엣지를 한 번에 돌려준다 (#170-보론6, 2026-09-15).
-- 종전에는 PostgREST max-rows(1000) 때문에 브라우저가 6번 왕복했다(노드 2 + 엣지 4).
-- 왕복 횟수가 첫 화면 대기의 대부분이라, 한 요청으로 줄인다.
-- SECURITY INVOKER(기본) 유지 — 호출자 권한으로 돌아 두 표의 RLS(anon select)가 그대로 적용된다.
-- STABLE: 쓰기 없음. 실측 59ms / 1.2MB (anon statement_timeout 3s 대비 여유 50배).
create or replace function public.lawmap_snapshot()
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
  select jsonb_build_object(
    'nodes', (
      select coalesce(jsonb_agg(jsonb_build_object(
        'id', id, 'name', name, 'node_type', node_type,
        'description', description, 'doc_name', doc_name, 'source', source
      ) order by id), '[]'::jsonb)
      from law_graph_nodes
    ),
    'edges', (
      select coalesce(jsonb_agg(jsonb_build_object(
        'id', id, 'source_id', source_id, 'target_id', target_id,
        'relation_type', relation_type, 'description', description,
        'source', source, 'weight', weight
      ) order by id), '[]'::jsonb)
      from law_graph_edges
    )
  );
$$;

comment on function public.lawmap_snapshot() is
  '법령 관계도 전체(노드+엣지)를 한 JSON으로. 대시보드 loadLawMap이 호출하며, 실패 시 클라이언트가 종전 페이지네이션으로 폴백한다. (#170-보론6)';

grant execute on function public.lawmap_snapshot() to anon, authenticated;;
