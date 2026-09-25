-- 20260913184010 kb_demote_split_mrn_21305_chunks

-- 망법 제21305호(20260707)는 구판인데 청크 228개 중 128개가 status='current'로 남아
-- 있었다(한 문서가 current/superseded로 쪼개진 승격 버그). 진짜 현행은 제21445호(20260911).
-- 자문 RAG가 구판 조문을 현행으로 집고, 인용검증이 거기에 '원문 확인됨'을 붙이는 상태였다.
-- 사전 확인: 제21445호가 본칙 조문을 전부 포함, 구판에만 있는 것은 부칙 제16955호(20200204) 1건.
update document_chunks
   set status = 'superseded'
 where doc_name = '정보통신망 이용촉진 및 정보보호 등에 관한 법률(법률)(제21305호)(20260707)'
   and status = 'current';;
