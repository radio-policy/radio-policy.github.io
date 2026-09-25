-- 20260804023605 news_screen_cache_created_at

-- 선별 캐시에 최초 등록 시각 추가 (#83)
-- 목적: 판정 건수가 튀었을 때 "새 기사가 실제로 늘어난 것"과 "제목이 바뀌어 재판정된 것"을
--       구분하기 위함. 지금은 judged_at(마지막 판정)만 있어 둘을 못 가른다.
--       2026-08-04 아침 피크(판정 209·218건) 조사에서 이 구분이 불가능해 원인 확정을 못 했다.
--
-- 판별법: created_at == judged_at → 신규 등록(첫 판정)
--         created_at <  judged_at → 제목 변경으로 재판정
--
-- ⚠️ DEFAULT를 붙인 채로 컬럼을 추가하면 **기존 1,046행이 전부 ALTER 시각으로 채워져**
--    "그때 처음 봤다"는 거짓 사실이 만들어진다. 그래서 두 단계로 나눈다:
--    ① 기본값 없이 추가 → 기존 행은 NULL(= 계측 이전, 알 수 없음)
--    ② 그 다음 DEFAULT 지정 → 앞으로 들어오는 행만 시각이 찍힌다
--
-- crawler.py는 upsert 페이로드에 {url, title_hash, criteria_hash}만 담으므로
-- ON CONFLICT UPDATE가 created_at을 건드리지 않는다 → **코드 변경 불필요**.
alter table public.news_screen_cache add column if not exists created_at timestamptz;
alter table public.news_screen_cache alter column created_at set default now();

comment on column public.news_screen_cache.created_at is
  '최초 등록 시각(#83). judged_at과 같으면 신규 기사, 더 이르면 제목 변경 재판정. NULL은 계측 이전 행.';;
