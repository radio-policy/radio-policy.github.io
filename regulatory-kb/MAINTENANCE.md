# KB 유지관리 — 법령 추가/갱신 시 중복 방지 절차

새 PDF를 추가하거나 같은 법을 다시 올릴 때 **반드시 아래 순서**를 따른다. 판정 기준은 `manifest.json`이다.

## 중복 판정 키(dedup_key)
`정규화 제목 + "|" + law_type`
- 정규화 제목: `(구버전)`, `(현행)` 같은 버전 수식어 제거.
- 같은 dedup_key = **같은 법령**(시행 버전만 다를 수 있음).

## 추가 전 체크리스트
1. PDF 첫 페이지에서 `title`, `law_type`, `law_number`, `enforcement_date` 확인.
2. `manifest.json`의 `entries`에서 동일 `dedup_key` 검색.
3. 분기 처리:
   - **동일 dedup_key + 동일 law_number** → *이미 존재*. 기존 `path`에 **덮어쓰기만**(내용 개선 시). 새 파일 만들지 않는다. → 중복 없음.
   - **동일 dedup_key + 더 최신 law_number/enforcement_date** → *새 버전*. 기존 항목 `status`를 `superseded`(+`superseded_by`)로 변경하고, 최신본을 `status: current`로 추가/갱신. (예: 단말장치 기술기준 2022-16호 → 2025-13호)
   - **dedup_key 없음** → *신규*. 적절한 법령군 폴더에 concept 문서 생성.
4. 문서 생성/갱신 후 `manifest.json`, 해당 `index.md`, `references/index.md`, `log.md` 갱신.


## 자동화 권장(선택)
`manifest.json`은 기계가독형이므로, 추후 앱(`okf.py` 등)에서 로드시 dedup_key 충돌을 검증하거나, 업로드 스크립트에서 제목→page_id 매핑 캐시로 재사용할 수 있다.

## 법안 요약(bills/) — 확정 법령과 다른 규칙 (2026-09-04 신설 — 배경역사 #121)

`bills/<year>/<의안번호>.md`는 국회 계류 중인 법률안 OKF다. **위 dedup_key·중복 판정 절차와 다르다** — 법령은 `제목|law_type`이지만 법안은 같은 이름의 개정안이 제안자만 다르게 여러 건 공존하므로(예: 「전파법 일부개정법률안」이 의원별로 동시 계류) 의안번호를 붙여 구분한다.

- `concept_type: Bill` (manifest·frontmatter 필수 — `import_regulatory_kb.py`의 `is_bill_entry()`가 이 값 또는 `path`의 `bills/` 접두로 법안 문서를 가른다)
- `dedup_key`: `정규화 제목|의안#<의안번호>` (예: `전파법 일부개정법률안|의안#2215722`) — `bill_dedup_key()`가 생성. `law_number`에 의안번호가 없으면 `#`이 빠진 dedup_key로 경고가 뜬다.
- `family: bills` (법령군 폴더가 아니라 통째로 `bills` 하나)
- `enforcement_date`: 시행일이 없으므로 **발의일**을 넣는다.
- `status: current` 고정 — 법안에는 superseded 개념이 없다(같은 이름 개정안은 dedup_key가 의안번호로 이미 갈라 놓았으므로 서로 버전 관계가 아니다). RPC `only_current` 필터를 통과시키는 데도 필요.
- **본문 게이트가 다르다**: 법령 요약처럼 `# Citations`로 끝나지 않는다. `# 제안이유`·`# 주요내용`·`# 통신사업자 영향` 3개 섹션 헤더가 모두 있어야 하고(`import_regulatory_kb.check_body_complete`의 `bills/` 분기), 최소 150자 이상, 말미가 문장 중간에서 끊기지 않아야 한다.
- 새 법안 문서를 만들 때 이 3섹션 중 하나라도 빠뜨리면 게이트가 "법안 필수 섹션 없음"으로 반려한다 — 법령 문서의 `# Citations` 누락 반려와 같은 실패 모드이니 혼동하지 말 것.
- kb_documents에서 `concept_type='Bill'`인 항목은 자문 화면에서 `[법안요약 · 국회 계류 — 확정 법령 아님]` 라벨로 별도 표시되고 조문 다리(법령명→현행 조문)에서 제외된다(`rag.ts`·`app.js` 공통) — 확정 법령처럼 인용되지 않게 하는 마지막 방어선이므로, 이 문서 작성 시 요약·주요내용을 "시행 중"이 아니라 "계류 중"으로 서술할 것.
