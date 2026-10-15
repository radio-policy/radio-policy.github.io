-- 20261015080314 documents_type_yakgwan_20261015

-- #312: 사업자 이용약관 분류 '약관' — upload_law_pdf.py VALID_CATEGORIES와 짝인 documents.type 검사 목록에 더한다
alter table public.documents drop constraint documents_type_check;
alter table public.documents add constraint documents_type_check CHECK ((type = ANY (ARRAY['법령'::text, '고시'::text, 'ITU-R'::text, '전파법'::text, '전파법_시행령'::text, '전파법_시행규칙'::text, '전기통신사업법'::text, '전기통신사업법_시행령'::text, '방송통신발전기본법'::text, '방송통신발전기본법_시행령'::text, '기술기준'::text, '적합성평가'::text, '주파수할당'::text, '주파수분배표'::text, '전자파'::text, '정보통신망법'::text, '정보통신기반시설'::text, '방송통신설비'::text, '약관'::text])));;
