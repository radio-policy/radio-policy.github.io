-- 20260913164030 lawmap_rename_dealer_topic

-- 검색 낱말 보강: lawmapTopicWords가 [\s·,()/]로만 쪼개므로 이름에 든 낱말로만 검색이 걸린다.
-- '대리점·판매점 규제'로는 '사전승낙' 검색이 영영 안 잡혀 이름에 넣는다.
-- 법문상 승낙의 대상은 '판매점'(제32조의14 제목 '판매점 선임에 대한 승낙')이므로 그 어순을 지킨다.
update law_graph_nodes
set name = '판매점 사전승낙·대리점 관리'
where name = '대리점·판매점 규제' and node_type = 'topic';

update lawmap_proposals
set topic = '판매점 사전승낙·대리점 관리'
where id = '5bb0ff98-a26f-4c12-91ef-6b1e959eb519';;
