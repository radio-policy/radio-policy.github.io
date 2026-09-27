-- 20260927050925 urgency_team_layer_250

-- 긴급도 2단계 세션 A — 팀 층 (2026-09-27, 설계안 §10 E1·E2·E4·E7·E8 + 결정 1(가)) · Fable 재검토

-- ① E1: 팀 표에 실(division)·표시 순서 + 15팀 (기존 1·2·3 번호 유지)
alter table public.teams add column if not exists division text;
alter table public.teams add column if not exists sort_order smallint not null default 100;
comment on column public.teams.division is '실(室) — 계정 관리의 팀 고르기를 실별로 묶는다 (E1)';
comment on column public.teams.sort_order is '표시 순서(실 순서 × 10 + 팀 순서)';
update public.teams set division = '사업협력실', sort_order = 20 + id where id in (1, 2, 3);
insert into public.teams (name, division, sort_order) values
  ('Comm전략팀', '정책개발실', 11), ('서비스제도팀', '정책개발실', 12), ('정책제도팀', '정책개발실', 13), ('통신Infra제도팀', '정책개발실', 14),
  ('정책분석팀', '대외지원실', 31), ('CR지원팀', '대외지원실', 32), ('정보보호정책팀', '대외지원실', 33), ('AI사업지원팀', '대외지원실', 34),
  ('MNO PR팀', '전략Comm실', 41), ('AI PR팀', '전략Comm실', 42), ('Digital Comm팀', '전략Comm실', 43),
  ('기업PR팀', '미디어Comm실', 51), ('뉴미디어팀', '미디어Comm실', 52),
  ('Creative전략팀', 'Comm지원실', 61), ('스포츠마케팅팀', 'Comm지원실', 62)
on conflict (name) do nothing;

-- ② 결정 1(가): 규칙이 본 검색 요약을 저장 — 수집 때와 브라우저 재적용이 같은 글을 본다.
--    content에 넣지 않는다(#188 — refetch_content의 '100자 미만 = 재수집' 조건이 깨진다). 크롤러(service_role)만 쓴다.
alter table public.news_feed add column if not exists screen_text text;
comment on column public.news_feed.screen_text is '수집 때 선별·긴급도 규칙·AI 판정에 쓴 검색 요약(네이버 description, ≤300자). 규칙 재적용·미리보기의 입력 = 제목 + 이 값(없으면 summary). content와 별개 (#250)';

-- ③ 팀 등급 (E2·E4·E7) — 공통값(news_feed.urgency)은 건드리지 않고 읽을 때 덧씌운다
create table public.team_urgency (
  news_id    uuid not null references public.news_feed(id) on delete cascade,
  team_id    smallint not null references public.teams(id) on delete cascade,
  urgency    text not null check (urgency in ('긴급','보통','참고')),
  source     text not null check (source in ('human','rule','ai')),
  rule_id    text,
  set_by     uuid,
  updated_at timestamptz not null default now(),
  primary key (news_id, team_id),
  check (source <> 'rule' or rule_id is not null)
);
comment on table public.team_urgency is '팀별 뉴스 등급(#250). human = 팀원 수정, rule = 팀 낱말 규칙(수집 때·규칙 저장 때), ai = 팀 AI(세션 C). 행이 없으면 그 팀은 공통값. set_by는 DB에만(화면은 이름 숨김, E7)';
create index team_urgency_team_idx on public.team_urgency (team_id, news_id);

create or replace function public.team_urgency_touch() returns trigger
language plpgsql set search_path = public as $$
begin
  new.updated_at := now();
  new.set_by := coalesce(auth.uid(), new.set_by);   -- 로그인 쓰기는 본인 id로 고정(위조 불가), 크롤러는 null
  return new;
end $$;
create trigger team_urgency_touch before insert or update on public.team_urgency
  for each row execute function public.team_urgency_touch();

alter table public.team_urgency enable row level security;
create policy team_urgency_sel on public.team_urgency for select to authenticated
  using ((select public.is_admin()) or ((select public.is_approved_user()) and team_id = (select public.my_team())));
create policy team_urgency_ins on public.team_urgency for insert to authenticated
  with check (source in ('human','rule')
    and ((select public.is_admin()) or ((select public.is_approved_user()) and team_id = (select public.my_team()))));
create policy team_urgency_upd on public.team_urgency for update to authenticated
  using ((select public.is_admin()) or ((select public.is_approved_user()) and team_id = (select public.my_team())))
  with check (source in ('human','rule')
    and ((select public.is_admin()) or ((select public.is_approved_user()) and team_id = (select public.my_team()))));
create policy team_urgency_del on public.team_urgency for delete to authenticated
  using (source in ('human','rule')
    and ((select public.is_admin()) or ((select public.is_approved_user()) and team_id = (select public.my_team()))));

revoke all on public.team_urgency from public, anon, authenticated;
grant select, insert, update, delete on public.team_urgency to authenticated;
grant all on public.team_urgency to service_role;

-- ④ E8: 수정 기록 팀 분리 — null = 공통(관리자). 공통 AI 학습은 null 행만 읽는다
alter table public.importance_feedback add column if not exists team_id smallint references public.teams(id);
comment on column public.importance_feedback.team_id is 'null = 공통값 수정(관리자, 공통 AI 학습 재료). 값 = 그 팀의 팀 등급 수정(팀 AI 재료, 공통 학습에 넣지 않음) (#250)';
alter table public.importance_feedback drop constraint if exists importance_feedback_news_id_key;
alter table public.importance_feedback add constraint importance_feedback_news_team_key unique nulls not distinct (news_id, team_id);

drop policy if exists imp_fb_sel on public.importance_feedback;
drop policy if exists imp_fb_ins on public.importance_feedback;
drop policy if exists imp_fb_upd on public.importance_feedback;
create policy imp_fb_sel on public.importance_feedback for select to anon, authenticated
  using (team_id is null or (select public.is_admin()) or team_id = (select public.my_team()));
create policy imp_fb_ins on public.importance_feedback for insert to authenticated
  with check (case when team_id is null then (select public.is_admin())
                   else (select public.is_admin()) or ((select public.is_approved_user()) and team_id = (select public.my_team())) end);
create policy imp_fb_upd on public.importance_feedback for update to authenticated
  using (case when team_id is null then (select public.is_admin())
              else (select public.is_admin()) or ((select public.is_approved_user()) and team_id = (select public.my_team())) end)
  with check (case when team_id is null then (select public.is_admin())
                   else (select public.is_admin()) or ((select public.is_approved_user()) and team_id = (select public.my_team())) end);
-- 삭제는 팀 행만(「공통값으로 되돌리기」). 공통 행은 영구 보관 — 삭제 정책 없음
create policy imp_fb_del on public.importance_feedback for delete to authenticated
  using (team_id is not null
    and ((select public.is_admin()) or ((select public.is_approved_user()) and team_id = (select public.my_team()))));
-- #226: anon은 SELECT만 (정책이 이미 막지만 권한도 맞춘다)
revoke insert, update, delete, truncate on public.importance_feedback from anon;
grant delete on public.importance_feedback to authenticated;

-- ⑤ E2: 팀 규칙은 그 팀 승인 계정 전원(종전 팀장만). 공통 규칙은 관리자만 그대로
drop policy if exists urgency_rules_ins on public.urgency_rules;
drop policy if exists urgency_rules_upd on public.urgency_rules;
create policy urgency_rules_ins on public.urgency_rules for insert to authenticated
  with check ((select public.is_admin())
    or (team_id is not null and (select public.is_approved_user()) and team_id = (select public.my_team())));
create policy urgency_rules_upd on public.urgency_rules for update to authenticated
  using ((select public.is_admin())
    or (team_id is not null and (select public.is_approved_user()) and team_id = (select public.my_team())))
  with check ((select public.is_admin())
    or (team_id is not null and (select public.is_approved_user()) and team_id = (select public.my_team())));
;
