-- 20260927083704 urgency_sentence_norm_251

-- #251 보완: 문장 공백 정리를 JS `\s`와 같은 문자 집합으로 못 박는다(PG `\s`는 로캘에 따라 U+FEFF를 빼고,
-- JS `\s`는 넣는다 — 대시보드의 200자 검사·「문장 바뀜」 판단과 DB 판 번호가 어긋나지 않게).
-- 집합 = JS WhiteSpace + LineTerminator: TAB VT FF SP NBSP U+1680 U+2000~U+200A U+2028 U+2029 U+202F U+205F U+3000 U+FEFF LF CR.
create or replace function public.urgency_rules_sentence_rev()
returns trigger
language plpgsql
set search_path to 'public'
as $function$
begin
  new.sentence := btrim(regexp_replace(normalize(coalesce(new.sentence, ''), NFC),
                  '[\t\n\v\f\r    -     　﻿]+', ' ', 'g'));
  if tg_op = 'INSERT' then
    new.sentence_rev := 0;
  elsif new.sentence is distinct from old.sentence then
    new.sentence_rev := old.sentence_rev + 1;
  else
    new.sentence_rev := old.sentence_rev;          -- 클라이언트가 판 번호를 바꿀 수 없다
  end if;
  return new;
end $function$;;
