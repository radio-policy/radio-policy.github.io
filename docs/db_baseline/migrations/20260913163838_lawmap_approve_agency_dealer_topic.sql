-- 20260913163838 lawmap_approve_agency_dealer_topic

-- 검토 대기 제안 5bb0ff98(대리점판매점규제) 승인 반영.
-- 주제명은 '대리점·판매점 규제'로 띄운다: lawmapTopicWords가 [\s·,()/]로만 쪼개므로
-- '대리점판매점규제'로 붙여 두면 한 낱말이 되어 '대리점'·'판매점' 검색에 영원히 안 걸린다.
with t as (
  insert into law_graph_nodes (name, node_type, description, source)
  values ('대리점·판매점 규제', 'topic',
          '대리점의 판매점 선임 사전승낙과 미승인 중간관리자의 금지행위 위반·사업자 귀속 여부',
          'ai')
  returning id
)
insert into law_graph_edges (source_id, target_id, relation_type, description, source, weight)
select t.id, x.target_id, '근거', x.descr, 'ai', x.w
from t, (values
  ('e551ff1d-404a-47c0-bbaf-cf27c85dfee0'::uuid,
   '판매점 선임 시 이동통신사업자의 서면 사전승낙 필요, 미승낙자와의 계약체결 거래 금지 (제32조의14) · 대리점·판매점 등 계약체결을 대리하는 자의 약관위반·중요사항 미고지를 사업자 행위로 귀속, 상당한 주의 시 면책 (제50조제2항)',
   2),
  ('21a224bf-576e-4493-9982-39d83f970b1d'::uuid,
   '사업자가 체계적 제도·교육·검증 등 실질적 사전 예방조치를 취한 경우 제50조제2항의 ''상당한 주의''로 인정 (제11조)',
   1)
) as x(target_id, descr, w);;
