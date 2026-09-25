-- 20260613132328 expand_documents_type_check


ALTER TABLE documents DROP CONSTRAINT documents_type_check;
ALTER TABLE documents ADD CONSTRAINT documents_type_check CHECK (type = ANY (ARRAY[
  '법령', '고시', 'ITU-R',
  '전파법', '전파법_시행령', '전파법_시행규칙',
  '전기통신사업법', '전기통신사업법_시행령',
  '방송통신발전기본법', '방송통신발전기본법_시행령',
  '기술기준', '적합성평가', '주파수할당', '주파수분배표',
  '전자파', '정보통신망법', '정보통신기반시설', '방송통신설비'
]::text[]));
;
