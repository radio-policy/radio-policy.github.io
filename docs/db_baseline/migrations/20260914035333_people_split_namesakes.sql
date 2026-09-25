-- 20260914035333 people_split_namesakes

-- 동명이인 분리 (#169-보론2, 2026-09-14 운영자 지시).
-- speaker_key 가 발언자 이름 원문이자 UNIQUE 라 '다른 사람 둘'이 한 행으로 합쳐졌다
-- (김성수: 20대 의원 58건 ↔ 과기혁신본부장 5건 / 이종호: 한수원 본부장 1건 ↔ 과기정통부장관 53건).
-- speaker_key 는 이제 '식별자'(접미사 허용), 발언 조인은 speaker_match 로 한다.
-- speech_from/to 가 있으면 그 구간의 발언만 그 사람 것으로 본다(NULL이면 전 구간).
alter table public.people
  add column if not exists speaker_match text,
  add column if not exists speech_from   date,
  add column if not exists speech_to     date;

update public.people set speaker_match = speaker_key where speaker_match is null;

-- 합쳐져 있던 두 행은 지운다. 이 행들의 stance_summary 는 두 사람의 발언을 섞어 쓴 것이라
-- 살려 둘 값어치가 없다 — 분리 후 각자 다시 만든다.
delete from public.people where speaker_key in ('김성수','이종호');;
