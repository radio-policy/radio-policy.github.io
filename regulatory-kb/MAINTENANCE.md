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
