-- 20260803042127 kb_quality_views_kind_aware

-- ① 조문 인식률은 '법령·고시 계열'에만 적용 (보도자료·업로드물·공고 제외)
--    근거: 법제처 명명규칙 '(제…호)(YYYYMMDD)' 문서 190건 평균 조문인식 92.1%(0% 5건),
--          그 외 179건 평균 2.9%(0% 171건) — 잣대가 다른 집단임이 데이터로 분리됨.
--    공고는 조문 대신 □/○·십진 번호 체계를 쓰므로 제외(7건 중 4건이 정상적으로 0%).
create or replace view public.kb_quality_article_parse as
select doc_name,
       count(*)::int as total_chunks,
       (count(*) filter (where article_no is not null and article_no <> ''))::int as parsed_chunks,
       round(100.0*(count(*) filter (where article_no is not null and article_no <> ''))/count(*),1) as parse_pct
from public.document_chunks c
where status = 'current'
  and doc_name ~ '\(제[0-9,\-]+호\)\([0-9]{8}\)$'          -- 법제처 명명규칙 = 법령/시행령/규칙/고시/훈령/예규
  and doc_name !~ '공고\)'                                  -- 공고는 조문 체계가 아님
  and doc_category not in ('보도자료','회의록','해외동향','추가지식','ITU-R')
  and not exists (select 1 from public.kb_quality_ack a where a.doc_name = c.doc_name)
group by doc_name
having count(*) >= 3
order by parse_pct asc, total_chunks desc
limit 15;

-- ③ 본문 부실 판정을 문서 종류별로 차등 (획일 2000자 → 종류별 하한)
--    근거: 종류별 실측 최소/중앙값 —
--      법령류      min 4669 / median 29115  → 2000 유지(하한 한참 아래)
--      훈령·예규   min 2892 / median  8459  → 2000 유지
--      바이너리업로드(pdf·docx·hwp) min 219 / p10 1962 / median 57980 → 2000 유지(추출실패 탐지)
--      텍스트업로드(.md 보도자료)  min 1608 / p10 2350            → 800 (정상 단문 보도자료 오탐 제거)
--      고시        min 126  / p10   820 / median 7561            → 300 (306·313자 고시도 제1조·제2조 완비 확인)
--      공고        min 417  / median 2703                        → 300 (공고는 원래 단문)
--    추가로, 법제처 원문이 본문 없이 첨부파일을 가리키는 '포인터 고시'(예: 무선통신매뉴얼 126자,
--    "자세한 내용은 … 버튼을 이용하십시오")는 재수집으로 개선 불가하므로 제외.
create or replace view public.kb_quality_low_docs as
with doc as (
  select doc_name, doc_category,
         sum(length(content))::int as chars,
         count(*)::int as chunks,
         bool_or(content like '%자세한 내용은%버튼을 이용%') as is_stub
  from public.document_chunks
  where status = 'current'
  group by doc_name, doc_category
), k as (
  select doc.*,
         case
           when doc_name ~ '\.(pdf|docx|hwp|hwpx|pptx)$' then '바이너리업로드'
           when doc_name ~ '\.(md|txt)$'                 then '텍스트업로드'
           when doc_name ~ '공고\)'                       then '공고'
           when doc_name ~ '고시\)'                       then '고시'
           else '법령'
         end as doc_kind
  from doc
), m as (
  select k.*,
         case k.doc_kind
           when '텍스트업로드' then 800
           when '공고'        then 300
           when '고시'        then 300
           else 2000
         end as min_chars
  from k
)
select doc_name, doc_category, chars, chunks, doc_kind, min_chars
from m
where chars < min_chars
  and not (is_stub and chars < 300)
  and not exists (select 1 from public.kb_quality_ack a where a.doc_name = m.doc_name)
order by chars asc
limit 15;

grant select on public.kb_quality_low_docs, public.kb_quality_article_parse to anon, authenticated;;
