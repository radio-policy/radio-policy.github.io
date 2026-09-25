-- 20260913163845 lawmap_proposal_mark_approved

update lawmap_proposals set
  status = 'approved',
  decided_at = now(),
  decided_by = 'acb015d9-b1cb-44b5-9b76-52109724fc4b',
  topic = '대리점·판매점 규제',
  description = '대리점의 판매점 선임 사전승낙과 미승인 중간관리자의 금지행위 위반·사업자 귀속 여부',
  decision_note = '세션 검토 승인 — 조문 3건 원문 대조 완료. 제50조 관계설명을 제1항제5호·제5호의2 한정으로 좁힘. 전기통신사업법 2건은 한 엣지에 두 조문으로 병합(중복 엣지 방지).',
  result = jsonb_build_object(
    'topicId', (select id from law_graph_nodes where name = '대리점·판매점 규제' and node_type = 'topic'),
    'saved', jsonb_build_array('전기통신사업법', '전기통신사업법', '방송통신사업 금지행위 등에 대한 업무처리규정'),
    'skipped', '[]'::jsonb)
where id = '5bb0ff98-a26f-4c12-91ef-6b1e959eb519';;
