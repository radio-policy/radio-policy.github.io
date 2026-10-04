-- 20261004030209 news_feed_urgency_fix_english_and_check

-- F7(10-04 임시 계정 시험, 설계 local_docs/팀채점_설계_261004.md §8): news_feed.urgency에 옛 영어 값 3건(low 2·medium 1,
-- origin issuemap, 08-26 적재). 팀 층 매처가 'medium'을 등급으로 못 읽어 「적어도 참고」 팀 규칙이 사실상 내림이 됐다.
-- 같은 행의 importance는 모두 '참고'이고 나머지 14,790행은 urgency = importance — 대시보드가 보여 온 값(importance)으로 맞춘다.
update public.news_feed
   set urgency = importance
 where urgency is not null
   and urgency not in ('긴급', '보통', '참고')
   and importance in ('긴급', '보통', '참고');

-- 다시 생기지 않게 — 쓰는 길은 크롤러·정부 공고·방미통위·해외·관리자 화면 모두 세 값만 쓴다(빈 값은 허용, 지금 0행).
-- NOT VALID로 먼저 걸고(짧은 잠금) 검사는 다음 마이그레이션 VALIDATE에서.
alter table public.news_feed
  add constraint news_feed_urgency_check check (urgency in ('긴급', '보통', '참고')) not valid;;
