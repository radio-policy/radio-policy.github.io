-- 20260826154505 create_people_profiles

-- 인물 프로필 (이슈맵 딥리서치 후속, 2026-08-27): 과방위 의원 + 정부·참고인
-- 원천은 assembly_speeches/assembly_bills — 이 테이블은 명부·AI 입장 요약 캐시만 담당
create table if not exists people (
  id bigserial primary key,
  speaker_key text not null unique,   -- assembly_speeches.speaker 정확 일치 키
  name text not null,                 -- 표시 이름 (한자 표기 등 보정)
  kind text not null default '의원',  -- 의원 | 정부·참고인
  party text,                         -- 활동 당시 소속 정당 (의원만, 시드)
  position text,                      -- 최근 직함
  terms text,                         -- 활동 대수 표시: '20·22대'
  is_22 boolean default false,        -- 22대(2024-06~) 발언 존재 여부 = 현역 판정
  speech_count int default 0,
  first_speech date,
  last_speech date,
  stance_summary text,                -- AI 쟁점별 입장 요약 (markdown, 캐시)
  stance_updated_at timestamptz,
  updated_at timestamptz default now()
);
alter table people enable row level security;
create policy people_sel on people for select using (true);
create policy people_upd on people for update using (true);;
