-- 20260927072713 urgency_sentence_rules_251

-- #251 (2026-09-27) 긴급도 세션 C — 팀 규칙의 「문장 조건」(낱말이 걸린 기사만 Haiku가 문장으로 확인) + 판정 기록 표.
-- 설계안 docs/뉴스중요도_공통팀별_설계안_260925.md §10-2. Fable 재검토 대상.

-- 1) 규칙: 문장 조건(팀 규칙만) + 문장 판(문장이 바뀔 때만 +1 — 판정 기록의 열쇠)
alter table public.urgency_rules
  add column if not exists sentence text not null default '',
  add column if not exists sentence_rev integer not null default 0;
alter table public.urgency_rules
  add constraint urgency_rules_sentence_team_check check (sentence = '' or team_id is not null),
  add constraint urgency_rules_sentence_len_check check (char_length(sentence) <= 200);

create or replace function public.urgency_rules_sentence_rev()
returns trigger
language plpgsql
set search_path to 'public'
as $function$
begin
  -- 공백 정리(여러 칸·줄바꿈 → 한 칸, 앞뒤 제거) + NFC — 같은 문장이 공백만 달라 판이 올라가지 않게
  new.sentence := btrim(regexp_replace(normalize(coalesce(new.sentence, ''), NFC), '\s+', ' ', 'g'));
  if tg_op = 'INSERT' then
    new.sentence_rev := 0;
  elsif new.sentence is distinct from old.sentence then
    new.sentence_rev := old.sentence_rev + 1;
  else
    new.sentence_rev := old.sentence_rev;          -- 클라이언트가 판 번호를 바꿀 수 없다
  end if;
  return new;
end $function$;

create trigger urgency_rules_sentence_rev before insert or update on public.urgency_rules
  for each row execute function public.urgency_rules_sentence_rev();

-- 2) 판정 기록: (규칙, 문장 판, 기사)마다 한 줄 — 한 번 판정하면 다시 묻지 않는다
create table public.urgency_rule_verdicts (
  rule_id      text        not null references public.urgency_rules(id),
  sentence_rev integer     not null,
  news_id      uuid        not null references public.news_feed(id) on delete cascade,
  team_id      smallint    not null references public.teams(id),
  status       text        not null default 'pending',
  verdict      boolean,
  reason       text        not null default '',
  input_kind   text        not null default '',
  model        text        not null default '',
  cost_usd     numeric(10,6) not null default 0,
  attempts     smallint    not null default 0,
  requested_by uuid,
  created_at   timestamptz not null default now(),
  judged_at    timestamptz,
  constraint urgency_rule_verdicts_pkey primary key (rule_id, sentence_rev, news_id),
  constraint urgency_rule_verdicts_status_check check (status in ('pending','wait_body','done','failed','stale')),
  constraint urgency_rule_verdicts_done_check check ((status = 'done') = (verdict is not null)),
  constraint urgency_rule_verdicts_kind_check check (input_kind in ('','body','snippet','title'))
);
create index urgency_rule_verdicts_open_idx on public.urgency_rule_verdicts (created_at)
  where status in ('pending','wait_body');
create index urgency_rule_verdicts_team_idx on public.urgency_rule_verdicts (team_id, judged_at);
create index urgency_rule_verdicts_news_idx on public.urgency_rule_verdicts (news_id);

-- 브라우저가 넣는 대기 행의 요청자 = 로그인 계정(값을 보내도 덮는다). service_role은 null 유지.
create or replace function public.urgency_rule_verdicts_requester()
returns trigger
language plpgsql
set search_path to 'public'
as $function$
begin
  if auth.uid() is not null then
    new.requested_by := auth.uid();
  end if;
  return new;
end $function$;

create trigger urgency_rule_verdicts_requester before insert on public.urgency_rule_verdicts
  for each row execute function public.urgency_rule_verdicts_requester();

alter table public.urgency_rule_verdicts enable row level security;

-- 읽기 = team_urgency와 같음(관리자 · 자기 팀 · 실장은 자기 실 팀들)
create policy urgency_rule_verdicts_sel on public.urgency_rule_verdicts as permissive for select to authenticated
  using ((select is_admin()) or ((select is_approved_user()) and team_id = (select my_team()))
         or ((select is_approved_user()) and (select my_division()) is not null
             and team_id in (select t.id from public.teams t where t.division = (select my_division()))));

-- 넣기 = 대기 행만(판정 칸은 빈 값), 자기 팀의 켜진 문장 규칙 · 지금 판만. 판정·수정·삭제는 service_role(크롤러)만.
create policy urgency_rule_verdicts_ins on public.urgency_rule_verdicts as permissive for insert to authenticated
  with check (status = 'pending' and verdict is null and reason = '' and input_kind = '' and model = ''
              and cost_usd = 0 and attempts = 0 and judged_at is null
              and ((select is_admin()) or ((select is_approved_user()) and team_id = (select my_team())))
              and exists (select 1 from public.urgency_rules r
                          where r.id = urgency_rule_verdicts.rule_id
                            and r.team_id = urgency_rule_verdicts.team_id
                            and r.enabled and r.sentence <> ''
                            and r.sentence_rev = urgency_rule_verdicts.sentence_rev));

-- GRANT 명시(#214) — anon 없음
revoke all on public.urgency_rule_verdicts from public, anon, authenticated;
grant select, insert on public.urgency_rule_verdicts to authenticated;
grant all on public.urgency_rule_verdicts to service_role;;
