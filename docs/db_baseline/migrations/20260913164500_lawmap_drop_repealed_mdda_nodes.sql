-- 20260913164500 lawmap_drop_repealed_mdda_nodes

-- 폐지된 단통법(2026-04-28 → 전기통신사업법 이관) 노드·엣지 제거.
-- 인용 5건은 전부 현행법 '부칙'의 폐지·경과·타법개정 문구에서 나온 것이라 살아 있는 관계가 아니다.
-- build_law_citation_graph.py CITE_BLOCKLIST에 함께 넣었으므로 17:00 재빌드에도 되살아나지 않는다.
delete from law_graph_edges
 where source_id in ('0505564c-647a-474e-82ad-015c6bca155e','97bfd894-8502-4d5a-9841-5280c5618edc')
    or target_id in ('0505564c-647a-474e-82ad-015c6bca155e','97bfd894-8502-4d5a-9841-5280c5618edc');

delete from law_graph_nodes
 where id in ('0505564c-647a-474e-82ad-015c6bca155e','97bfd894-8502-4d5a-9841-5280c5618edc');

-- 세션 시험으로 넣은 비로그인 요청 행 제거(운영자 봇 발송 확인 완료 — message_id 1674).
delete from lawmap_proposals
 where origin = 'request' and created_by is null and topic = '테스트 요청(무시해 주세요)';;
