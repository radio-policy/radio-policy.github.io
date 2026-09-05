# 법령 관계도 주제 엣지 전수 검증 — 판정 기준 (모든 에이전트 공통)

## 목적
Supabase 프로젝트 `zwkjedumfuhodckmtxxn`의 `law_graph_edges` 중 **주제(topic) 노드에서 나가는 엣지**의
설명문(description)이 법령 원문과 맞는지 검증하고, 엣지별 판정을 JSON으로 남긴다.
청중은 통신정책 전문가다. **조문 번호가 맞아도 조문의 성격이 설명과 다르면 오류**다.

## 절대 규칙
- **읽기 전용.** DB 쓰기·삭제 금지 (MCP execute_sql은 읽기 전용이다). 리포 파일 수정 금지. 결과는 지정된 JSON 파일에만 쓴다.
- **원문 인용 없이는 판정하지 않는다.** 모든 판정에 document_chunks에서 실제로 읽은 조문을 근거로 붙인다(200자 이내 인용).
- 추정 금지. 근거를 못 찾으면 `UNVERIFIABLE` 또는 `DELETE`(아래 기준)로 적고 이유를 쓴다.

## 데이터 조회 (MCP 도구 `mcp__a17e0580-b610-4e4c-984d-b5ed86e55bc4__execute_sql`, project_id = zwkjedumfuhodckmtxxn)

1) 내 주제들의 엣지:
```sql
SELECT e.id AS edge_id, t.name AS topic, d.name AS target, d.node_type, e.source, e.relation_type, e.weight, e.description
FROM law_graph_edges e
JOIN law_graph_nodes t ON t.id=e.source_id AND t.node_type='topic'
JOIN law_graph_nodes d ON d.id=e.target_id
WHERE t.name IN ('주제1','주제2', ...)
ORDER BY t.name, d.name;
```
2) 대상 문서의 최신본 이름(문서명은 `노드명(법률)(제N호)(YYYYMMDD)` 꼴, 여러 판이 있으면 날짜 최신):
```sql
SELECT DISTINCT doc_name FROM document_chunks WHERE doc_name LIKE '대상노드명%' ORDER BY doc_name DESC;
```
3) 조문 확인 (`article_no`는 '19조(사업의 휴업ㆍ폐업)'처럼 '제'가 없는 형태가 대부분, 일부 '제19조…'도 있음):
```sql
SELECT article_no, left(content, 900) FROM document_chunks
WHERE doc_name = '<최신 doc_name>' AND (article_no LIKE '19조%' OR article_no LIKE '제19조%')
ORDER BY chunk_index;
```
4) 조문 번호가 없는 설명은 대상 문서에서 주제 키워드로 조문을 찾는다:
```sql
SELECT article_no, left(content, 400) FROM document_chunks
WHERE doc_name = '<최신 doc_name>' AND content ILIKE '%키워드%' ORDER BY chunk_index LIMIT 10;
```

## 판정 절차 (엣지마다)
1. 설명에 조문 번호가 있으면 → 그 조문을 **대상 문서**에서 읽는다.
   - 단, 설명이 "상위법 제N조 위임", "사업법 제N조", "법 제N조" 식으로 **다른 법령의 조문**을 가리키면 그 상위법 문서에서 확인한다(대상 고시 자체에 그 번호가 없는 것은 오류가 아님).
2. 조문 내용이 설명과 **성격까지** 맞는지 본다. 함정 예시:
   - 전파법 제15조의2 "주파수할당의 취소"는 부정취득·대가미납 시 **제재** 조항 → "3G 종료 시 주파수 반납 근거"로 쓰면 오류(실제 근거는 제16조 재할당·제6조의2 회수).
   - 전기통신사업법 제3조(역무 제공 의무 일반)를 "재난문자 송출 의무"로 쓴 것 → 오류(재난문자 조문은 그 법에 없음).
   - "관련 조문", "(관련)" 같은 자리표시 설명 → 근거 없음.
3. 조문 번호가 없으면 키워드 검색으로 조문을 특정한다. 특정되면 `FIX`로 번호를 채운다. 대상 문서에 주제와 관련된 조문이 전혀 없으면 `DELETE`.
4. "[인접 제도]"로 시작하는 설명은 위임·인용이 아니라 '옆에 두고 볼 제도'라는 뜻이다. 실제 인접성이 원문으로 확인되면 KEEP(필요시 조문 보강), 아니면 DELETE.
5. 대상 문서가 document_chunks에 없으면 `UNVERIFIABLE` (삭제 권고 아님).

## 판정 값
- `KEEP` — 조문·성격 모두 맞음. (설명에 조문 번호가 없어도 문장이 정확하고 조문을 특정할 수 있으면 `FIX`로 번호를 채우는 편이 좋다)
- `FIX` — 연결은 타당하나 설명 수정 필요. `new_description` 필수(조문 번호 포함, 100자 내외, 기존 어조 유지).
- `DELETE` — 대상 문서에 근거 조문이 없거나 성격이 달라 연결 자체가 오도.
- `UNVERIFIABLE` — 대상 문서 미보유.

## 출력 (반드시 이 형식, UTF-8 JSON, 지정 경로에 저장)
```json
{
  "batch": "N",
  "topics": ["..."],
  "edges": [
    {
      "edge_id": "uuid",
      "topic": "…", "target": "…", "source": "seed|ai|...",
      "current_description": "…",
      "verdict": "KEEP|FIX|DELETE|UNVERIFIABLE",
      "new_description": "… (FIX일 때만)",
      "evidence": [{"doc_name": "…", "article_no": "…", "quote": "≤200자 원문 인용"}],
      "reason": "한 문장"
    }
  ],
  "summary": {"KEEP": 0, "FIX": 0, "DELETE": 0, "UNVERIFIABLE": 0}
}
```
JSON 저장은 Write 도구로 한다. 최종 응답에는 요약 수치와 DELETE·FIX 목록(주제/대상/이유 한 줄)만 적는다.
