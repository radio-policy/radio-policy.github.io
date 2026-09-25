-- 20260913184130 lawmap_c_section_fix_24

-- 2026-09-14 관계도 C절 기계적 수정 24건. 원본은 law_graph_nodes_bak_20260914 에 보존.
-- 원인: build_law_citation_graph.py:227 이 대표 판본을 status 가 아니라 doc_name 문자열 크기로
-- 고르고, :705 가 이미 doc_name 이 있는 노드는 영원히 갱신하지 않아 개정 뒤 낡은 채 굳었다.
-- 이번 수정은 일회성 패치이며 원인은 그대로 남는다(별도 과제).
-- 사전 확인: 15건 모두 신판에 본칙 조문 누락 0건(부칙·조문제목 띄어쓰기 차이만 존재).

-- ── C-1. 폐지·시행예정 판본을 가리키는 노드 15건 → 현행본 ──
update law_graph_nodes set doc_name='지방세법 시행령(대통령령)(제36445호)(20260701)'
 where doc_name='지방세법 시행령(대통령령)(제36364호)(20260601)';

update law_graph_nodes set doc_name='정보통신망 이용촉진 및 정보보호 등에 관한 법률(법률)(제21445호)(20260911)'
 where doc_name='정보통신망 이용촉진 및 정보보호 등에 관한 법률(법률)(제21066호)(20251001)';

update law_graph_nodes set doc_name='방송통신발전 기본법(법률)(제21380호)(20260820)'
 where doc_name='방송통신발전 기본법(법률)(제21066호)(20251001)';

update law_graph_nodes set doc_name='국가재정법(법률)(제21419호)(20260911)'
 where doc_name='국가재정법(법률)(제21738호)(20260602)';

update law_graph_nodes set doc_name='개인정보 보호법 시행령(대통령령)(제36121호)(20260820)'
 where doc_name='개인정보 보호법 시행령(대통령령)(제36340호)(20260519)';

update law_graph_nodes set doc_name='지방세법(법률)(제21308호)(20260701)'
 where doc_name='지방세법(법률)(제21308호)(20260424)';

update law_graph_nodes set doc_name='개인정보 보호법(법률)(제21445호)(20260911)'
 where doc_name='개인정보 보호법(법률)(제20897호)(20251002)';

update law_graph_nodes set doc_name='정보통신망 이용촉진 및 정보보호 등에 관한 법률 시행령(대통령령)(제36502호)(20260707)'
 where doc_name='정보통신망 이용촉진 및 정보보호 등에 관한 법률 시행령(대통령령)(제36220호)(20260324)';

update law_graph_nodes set doc_name='인공지능 발전과 신뢰 기반 조성 등에 관한 기본법 시행령(대통령령)(제36580호)(20260820)'
 where doc_name='인공지능 발전과 신뢰 기반 조성 등에 관한 기본법 시행령(대통령령)(제36506호)(20260721)';

update law_graph_nodes set doc_name='국가재정법 시행령(대통령령)(제36546호)(20260731)'
 where doc_name='국가재정법 시행령(대통령령)(제36312호)(20260506)';

update law_graph_nodes set doc_name='방송통신기자재등의 적합성평가에 관한 고시(국립전파연구원고시)(제2026-4호)(20260724)'
 where doc_name='방송통신기자재등의 적합성평가에 관한 고시(과학기술정보통신부고시)(제2025-56호)(20261106)';

update law_graph_nodes set doc_name='방송통신기자재등 시험기관의 지정 및 관리에 관한 고시(국립전파연구원고시)(제2026-5호)(20260821)'
 where doc_name='방송통신기자재등 시험기관의 지정 및 관리에 관한 고시(국립전파연구원고시)(제2025-22호)(20260701).pdf';

update law_graph_nodes set doc_name='데이터 산업진흥 및 이용촉진에 관한 기본법(법률)(제21392호)(20260828)'
 where doc_name='데이터 산업진흥 및 이용촉진에 관한 기본법(법률)(제21066호)(20251001)';

update law_graph_nodes set doc_name='간이무선국·우주국·지구국의 무선설비 및 전파탐지용 무선설비 등 그 밖의 업무용 무선설비의 기술기준(국립전파연구원고시)(제2026-3호)(20260707)'
 where doc_name='간이무선국·우주국·지구국의 무선설비 및 전파탐지용 무선설비 등 그 밖의 업무용 무선설비의 기술기준(국립전파연구원고시)(제2025-5호)(20250526).pdf';

update law_graph_nodes set doc_name='항공주파수 이용 및 관리에 관한 규정(국토교통부고시)(제2026-446호)(20260820)'
 where doc_name='항공주파수 이용 및 관리에 관한 규정(국토교통부고시)(제2023-842호)(20231222)';

-- ── C-2. 대통령령인데 node_type='notice' 인 것 2건 ──
-- 화면 색만이 아니라, 누락 후보 추출 쿼리가 node_type='notice' 로 걸러 모집단까지 왜곡했다.
update law_graph_nodes set node_type='decree'
 where doc_name like '%(대통령령)%' and node_type <> 'decree';

-- ── C-3. 특정 주제 시점으로 오염된 허브 노드 설명문 3건 → 중립 ──
-- 전파법은 70개 주제가 공유하는데 어느 주제에서 눌러도 "검사제도 근거법"이 떴다.
update law_graph_nodes
   set description='무선국 개설·주파수 이용·전파 이용 질서 전반을 정하는 법률'
 where name='전파법' and description='무선국 준공검사·정기검사·수시검사 등 검사제도의 근거법';

update law_graph_nodes
   set description='전파법의 위임사항을 정하는 대통령령'
 where name='전파법 시행령' and description='검사 절차·시기·수수료 등을 정하는 대통령령';

update law_graph_nodes
   set description='정보통신망 이용촉진과 정보보호에 관한 사항을 정하는 법률'
 where name='정보통신망 이용촉진 및 정보보호 등에 관한 법률'
   and description='침해사고 즉시 신고 의무 및 신고 시기·방법 대통령령 위임';

-- ── C-4. kb_documents 가 구판을 current 로 들고 있던 4건 ──
update kb_documents set law_number='제21445호', enforcement_date='2026-09-11' where id=744;
update kb_documents set law_number='제21419호', enforcement_date='2026-09-11' where id=862;
update kb_documents set law_number='제21380호', enforcement_date='2026-08-20' where id=620;
update kb_documents set law_number='제21445호', enforcement_date='2026-09-11' where id=617;;
