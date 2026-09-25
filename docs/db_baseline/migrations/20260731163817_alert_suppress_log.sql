-- 20260731163817 alert_suppress_log

-- 긴급 재알림 억제 내역 (배경역사 #44). 1~2주 실측 후 "본문에만 새 내용" 놓침이
-- 실제 있는지 판단하는 근거. service key(크롤러)만 쓰고 대시보드 노출 없음.
create table if not exists alert_suppress_log (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  article_title text not null,
  article_url text,
  matched_title text not null,     -- 어떤 기존 기사와 유사해서 억제됐는지
  shared_keywords text             -- 공유 키워드 (판정 재현용)
);
alter table alert_suppress_log enable row level security;
-- 정책 없음 = anon 접근 차단, service role만 접근;
