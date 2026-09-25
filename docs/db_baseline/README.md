# DB 설계도 (docs/db_baseline) — 자동 생성, 손으로 고치지 말 것

`py -3.12 tools_db_baseline.py`가 실DB(Supabase `zwkjedumfuhodckmtxxn`)의 카탈로그에서 만든다(§4-4-11, 배경역사 #227).
정의만 있고 데이터는 없다. 비밀값(봇 토큰·Vault 값·운영자/구독자 chat_id·메일·해시)은 가려져 있다.
`docs/schema.sql`은 폐지됐다 — 이 폴더가 정본이다.

## 갱신
- DB를 바꾼 세션은 커밋 전에 `py -3.12 tools_release.py`를 돌린다 → ⑦이 이 폴더와 실DB가 다르면 알려 준다.
- `py -3.12 tools_db_baseline.py` → 바뀐 파일만 다시 쓴다 → `git add docs/db_baseline/<바뀐 파일>` → 3단계 검증.
- 월 1회(매월 1일 전후) 한 번 더 확인한다.

## 복구 순서 (새 Supabase 프로젝트 — SQL Editor에서 파일 순서대로)
1. `00_extensions.sql` → `05_sequences.sql` → `10_tables.sql` → `15_foreign_keys.sql`
2. `20_functions.sql`(맨 위 `set check_function_bodies = off`) → `25_views.sql` → `30_indexes.sql` → `40_triggers.sql`
3. `50_policies.sql` → `60_grants.sql`(전부 회수 후 지금 권한만 부여) → `65_role_settings.sql`(statement_timeout — 실행 뒤 `NOTIFY pgrst, 'reload config';`)
4. Vault 값 재입력: `90_vault_names.txt`의 이름마다 `vault.create_secret(값, 이름)` — 값은 운영자 보관분·재발급
   (`github_pat`는 조직 `radio-policy` 소유 fine-grained PAT, Actions R/W 필수 — 지침 #18·#116)
5. `70_cron.sql` — 1~4가 끝난 뒤(잡이 Vault·함수를 부른다). 파일의 `<OPERATOR_CHAT_ID>`는 실제 값으로 바꾼다(20_functions도 동일)
6. `80_storage.sql`(버킷) — 스토리지 정책은 50에 들어 있다
7. Edge Function: `supabase/functions/`의 폴더 전부 배포(verify_jwt는 지침 Edge 표) + Edge Secrets(지침 '외부 서비스·키')
8. Auth 설정(이메일 확인 끄기 `mailer_autoconfirm` — 지침 #104), GitHub Secrets·PC `.env`의 URL·키 교체
9. 데이터는 이 폴더에 없다 — Supabase 백업(Pro 일일 백업)에서 되살리거나 크롤러 재수집

복구 연습(2026-09-26, 빈 브랜치 DB에 1~3·6 적용, cron은 적용 후 되돌림): 다시 뜬 설계도가 표·외래키·함수·뷰·인덱스·
트리거·정책·권한·역할 설정·버킷까지 원본과 한 글자도 다르지 않았다. 다른 것은 예상한 셋뿐 — cron(되돌림)·Vault(값 재입력
전)·`pg_net` 위치(새 프로젝트엔 `extensions` 스키마에 미리 설치돼 `with schema public`이 건너뛰어짐; 함수는 `net.*`라 동작 같음).

`migrations/`는 참고용 변경 이력(Supabase `schema_migrations` 원문, 비밀 마스킹). 5/28 이전 표·SQL Editor 손 DDL이
빠져 있어 **이력을 재생해서는 복구되지 않는다** — 복구는 위 번호 파일로 한다(같은 복구 연습에서 브랜치가 이력 재생에
실패했다 — MIGRATIONS_FAILED).
