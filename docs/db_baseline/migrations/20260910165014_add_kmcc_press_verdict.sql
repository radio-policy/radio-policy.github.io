-- 20260910165014 add_kmcc_press_verdict

-- #154-보론3: 방미통위 일반 보도자료 관련성 판정 캐시. Haiku 판정이 실행마다 뒤집혀(드라마 AI 제작 사례: 무관→관련)
-- 지운 글이 매시 되살아나는 것을 막는다. url 단위 1회 판정·영구 재사용. RLS 켜고 정책 0개 = service_role 전용.
create table if not exists public.kmcc_press_verdict (
  url text primary key,
  title text,
  relevant boolean not null,
  reason text,
  judged_at timestamptz not null default now()
);
alter table public.kmcc_press_verdict enable row level security;
comment on table public.kmcc_press_verdict is '방미통위 일반 보도자료 관련성 판정 캐시(kmcc_meeting.py, #154). 운영자가 relevant를 고치면 다음 실행에 반영';;
