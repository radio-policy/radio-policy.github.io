-- 20261004043420 team_grading_s1_20261004

-- #277 팀 채점 S1(설계 local_docs/팀채점_설계_261004.md §3·§5·§7·§10·§11) — 표 6개·점수 RPC·대표·기준문 팀 편집·
-- 큐 topic team·사내 다리 RPC team_rules_export. anon 회수(설계 §5-4 ③)는 사내 「첫 회차 정상」 회신 뒤 별도 마이그레이션.
-- 외래키 주의(#266-보론): teams↔profiles 사이에 외래키를 더 만들지 않는다(PostgREST 묶음 모호 → 로그인 불가 전례) —
-- teams.grader_user_id·답 user_id·요청자 칸은 외래키 없이 트리거·함수로 확인한다.

-- ── 0. 공용 도우미(SECURITY DEFINER — EXECUTE는 authenticated·service_role만, #186) ─────────────────
create or replace function public.grading_team_visible(p_team smallint)
 returns boolean language sql stable security definer set search_path to '' as $$
  -- 읽기 범위 = 관리자 · 그 팀 승인 계정 · 그 실의 실장(팀 없음·실 지정, 읽기만) — team_urgency_sel과 같은 꼴
  select public.is_admin()
      or (public.is_approved_user() and p_team = public.my_team())
      or (public.is_approved_user() and public.my_division() is not null
          and exists (select 1 from public.teams t where t.id = p_team and t.division = public.my_division()))
$$;

-- ── 1. 대표(teams.grader_user_id) — 외래키 없음(위 주의), anon 4칸 GRANT에 넣지 않음(#253) ─────────────
alter table public.teams add column if not exists grader_user_id uuid;

create or replace function public.team_grader_uid(p_team smallint)
 returns uuid language sql stable security definer set search_path to '' as $$
  -- 그 팀의 채점 대표 — 지정됐고 그 팀의 승인·활성 계정일 때만(비활성·다른 팀으로 옮김·삭제 = 없음, 설계 §5-2·§11-10)
  select t.grader_user_id from public.teams t
    join public.profiles p on p.user_id = t.grader_user_id
   where t.id = p_team and p.team_id = t.id and p.approved and p.active
$$;


create or replace function public.teams_grader_check()
 returns trigger language plpgsql security definer set search_path to '' as $$
begin
  if new.grader_user_id is not null and new.grader_user_id is distinct from old.grader_user_id
     and not exists (select 1 from public.profiles p
                      where p.user_id = new.grader_user_id and p.team_id = new.id and p.approved and p.active) then
    raise exception 'TEAM_GRADER_NOT_MEMBER' using errcode = '23514',
      hint = '채점 대표는 그 팀의 승인·활성 계정만 지정할 수 있습니다';
  end if;
  return new;
end $$;
drop trigger if exists teams_grader_check on public.teams;
create trigger teams_grader_check before update of grader_user_id on public.teams
  for each row execute function public.teams_grader_check();

-- ── 2. team_criteria — 옮기지 못한 줄(unconverted) + 팀 UPDATE(설계 §2-2·§5-3) ────────────────────
alter table public.team_criteria add column if not exists unconverted text not null default '';
alter table public.team_criteria drop constraint if exists team_criteria_unconverted_check;
alter table public.team_criteria add constraint team_criteria_unconverted_check check (char_length(unconverted) <= 2000);
grant select (unconverted) on public.team_criteria to authenticated;      -- 쓰기는 service_role만(칸 GRANT 밖)

drop policy if exists team_criteria_upd on public.team_criteria;
create policy team_criteria_upd on public.team_criteria for update to authenticated
  using ((select public.is_admin()) or ((select public.is_approved_user()) and team_id = (select public.my_team())))
  with check ((select public.is_admin()) or ((select public.is_approved_user()) and team_id = (select public.my_team())));

drop policy if exists team_criteria_history_sel on public.team_criteria_history;
create policy team_criteria_history_sel on public.team_criteria_history for select to authenticated
  using ((select public.is_admin())
         or ((select public.is_approved_user()) and team_id = (select public.my_team()))
         or ((select public.is_approved_user()) and (select public.my_division()) is not null
             and team_id in (select t.id from public.teams t where t.division = (select public.my_division()))));

-- ── 3. 채점 세트 ────────────────────────────────────────────────────────────────────────────────
create table if not exists public.team_grading_sets (
  id bigint generated always as identity not null,
  team_id smallint not null references public.teams(id) on delete cascade,
  status text not null default 'requested',
  requested_by uuid,
  built_at timestamptz,
  pool_from timestamptz,
  pool_to timestamptz,
  pool_thin boolean not null default false,
  noise_mismatch integer,
  noise_compared integer,
  seed bigint,
  build_attempts smallint not null default 0,
  note text not null default '',
  created_at timestamptz not null default now(),
  closed_at timestamptz,
  constraint team_grading_sets_pkey primary key (id),
  constraint team_grading_sets_status_check check (status in
    ('requested','building','open','scored','applied','closed','too_small','no_rules','failed'))
);
alter table public.team_grading_sets enable row level security;
-- 팀당 진행 중 세트는 하나(요청·만드는 중·열림·채점 중)
create unique index if not exists team_grading_sets_active_uq on public.team_grading_sets (team_id)
  where status in ('requested','building','open','scored');

create or replace function public.grading_set_team(p_set bigint)
 returns smallint language sql stable security definer set search_path to '' as $$
  select team_id from public.team_grading_sets where id = p_set
$$;


create or replace function public.team_grading_sets_guard()
 returns trigger language plpgsql security definer set search_path to '' as $$
declare
  n int;
begin
  -- service_role(크롤러)·SQL, 또는 시험 트리거가 바꾸는 상태(open→scored, →applied: 트리거 깊이 2) — 제한 없음
  if auth.uid() is null or (tg_op = 'UPDATE' and pg_trigger_depth() > 1) then
    return new;
  end if;
  if tg_op = 'INSERT' then
    -- 요청만: 상태·만든 값은 서버가 정한다. 관리자가 아니면 팀당 월 2회(KST, 설계 §7-7)
    perform pg_advisory_xact_lock(hashtext('team_grading_sets'), new.team_id);
    if not public.is_admin() then
      select count(*) into n from public.team_grading_sets
       where team_id = new.team_id
         and created_at >= (date_trunc('month', now() at time zone 'Asia/Seoul') at time zone 'Asia/Seoul');
      if n >= 2 then
        raise exception 'TEAM_GRADING_MONTHLY_CAP' using errcode = '54000', hint = '새 채점 세트는 팀당 한 달에 2번까지입니다';
      end if;
    end if;
    new.status := 'requested'; new.requested_by := auth.uid(); new.created_at := now();
    new.built_at := null; new.pool_from := null; new.pool_to := null; new.pool_thin := false;
    new.noise_mismatch := null; new.noise_compared := null; new.seed := null; new.build_attempts := 0;
    new.note := ''; new.closed_at := null;
    return new;
  end if;
  -- UPDATE: 팀은 열림·채점 중 → 닫기만(설계 §5-1)
  if not (old.status in ('open','scored') and new.status = 'closed') then
    raise exception 'TEAM_GRADING_SET_TRANSITION' using errcode = '23514', hint = '열린 세트를 닫는 것만 할 수 있습니다';
  end if;
  new.closed_at := now();
  return new;
end $$;
drop trigger if exists team_grading_sets_guard on public.team_grading_sets;
create trigger team_grading_sets_guard before insert or update on public.team_grading_sets
  for each row execute function public.team_grading_sets_guard();

create policy team_grading_sets_sel on public.team_grading_sets for select to authenticated
  using (public.grading_team_visible(team_id));
create policy team_grading_sets_ins on public.team_grading_sets for insert to authenticated
  with check ((select public.is_admin()) or ((select public.is_approved_user()) and team_id = (select public.my_team())));
create policy team_grading_sets_upd on public.team_grading_sets for update to authenticated
  using ((select public.is_approved_user()) and team_id = (select public.my_team()))
  with check ((select public.is_approved_user()) and team_id = (select public.my_team()));

-- ── 4. 세트 항목 — slot(고칠 몫/확인용)은 authenticated 칸 GRANT 밖(설계 §11-1) ─────────────────────
create table if not exists public.team_grading_items (
  set_id bigint not null references public.team_grading_sets(id) on delete cascade,
  news_id uuid not null references public.news_feed(id) on delete cascade,
  seq smallint not null,
  slot text not null,
  hit_kind_at_build text not null,
  common_level_at_build text not null,
  team_level_at_build text not null,
  team_source_at_build text not null,
  rule_id_at_build text,
  rule_sentence_at_build boolean not null default false,
  constraint team_grading_items_pkey primary key (set_id, news_id),
  constraint team_grading_items_slot_check check (slot in ('tune','check')),
  constraint team_grading_items_kind_check check (hit_kind_at_build in
    ('rule_changed','rule_same','word_hit_false','near','unrelated')),
  constraint team_grading_items_common_check check (common_level_at_build in ('긴급','보통','참고')),
  constraint team_grading_items_team_check check (team_level_at_build in ('긴급','보통','참고')),
  constraint team_grading_items_source_check check (team_source_at_build in ('common','rule','human','ai'))
);
alter table public.team_grading_items enable row level security;
create index if not exists team_grading_items_news_idx on public.team_grading_items (news_id);
create policy team_grading_items_sel on public.team_grading_items for select to authenticated
  using (public.grading_team_visible(public.grading_set_team(set_id)));

-- ── 5. 정답 — 본인 행만, 첫 시험 뒤(scored)엔 대표만(설계 §4-1·§11-2) ─────────────────────────────
create table if not exists public.team_grading_answers (
  set_id bigint not null,
  news_id uuid not null,
  user_id uuid not null default auth.uid(),
  answer text not null,
  updated_at timestamptz not null default now(),
  changed_after_lock boolean not null default false,
  constraint team_grading_answers_pkey primary key (set_id, news_id, user_id),
  constraint team_grading_answers_item_fkey foreign key (set_id, news_id)
    references public.team_grading_items(set_id, news_id) on delete cascade,
  constraint team_grading_answers_answer_check check (answer in ('긴급','보통','참고','모르겠음'))
);
alter table public.team_grading_answers enable row level security;

create or replace function public.grading_answer_open(p_set bigint)
 returns boolean language sql stable security definer set search_path to '' as $$
  select exists (select 1 from public.team_grading_sets s
                  where s.id = p_set and public.is_approved_user() and s.team_id = public.my_team()
                    and (s.status = 'open'
                         or (s.status = 'scored' and public.team_grader_uid(s.team_id) = auth.uid())))
$$;

create or replace function public.team_grading_answers_touch()
 returns trigger language plpgsql security definer set search_path to '' as $$
declare
  st text;
begin
  if tg_op = 'UPDATE' then            -- 열쇠는 못 바꾼다(upsert가 set_id·news_id를 함께 보내므로 칸 GRANT는 있다)
    new.set_id := old.set_id; new.news_id := old.news_id; new.user_id := old.user_id;
  elsif auth.uid() is not null then
    new.user_id := auth.uid();
  end if;
  select status into st from public.team_grading_sets where id = new.set_id;
  new.updated_at := now();
  new.changed_after_lock := (tg_op = 'UPDATE' and old.changed_after_lock) or coalesce(st = 'scored', false);
  return new;
end $$;
drop trigger if exists team_grading_answers_touch on public.team_grading_answers;
create trigger team_grading_answers_touch before insert or update on public.team_grading_answers
  for each row execute function public.team_grading_answers_touch();

create policy team_grading_answers_sel on public.team_grading_answers for select to authenticated
  using (public.grading_team_visible(public.grading_set_team(set_id)));
create policy team_grading_answers_ins on public.team_grading_answers for insert to authenticated
  with check (user_id = auth.uid() and public.grading_answer_open(set_id));
create policy team_grading_answers_upd on public.team_grading_answers for update to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid() and public.grading_answer_open(set_id));

-- ── 6. 시험(다시 채점) — 운영 규칙을 건드리지 않는 미리 재기(설계 §3-2) ─────────────────────────────
create table if not exists public.team_grading_trials (
  id bigint generated always as identity not null,
  set_id bigint not null references public.team_grading_sets(id) on delete cascade,
  team_id smallint not null,
  kind text not null default 'trial',
  candidates jsonb not null default '[]'::jsonb,
  status text not null default 'pending',
  applied_rev jsonb,
  cost_usd numeric(10,6) not null default 0,
  attempts smallint not null default 0,
  created_by uuid,
  created_at timestamptz not null default now(),
  judged_at timestamptz,
  applied_at timestamptz,
  copied_at timestamptz,
  note text not null default '',
  constraint team_grading_trials_pkey primary key (id),
  constraint team_grading_trials_kind_check check (kind in ('trial','noise')),
  constraint team_grading_trials_status_check check (status in ('pending','judged','applied','failed')),
  constraint team_grading_trials_cand_check check (jsonb_typeof(candidates) = 'array'
    and jsonb_array_length(candidates) <= 20 and octet_length(candidates::text) <= 40000),
  constraint team_grading_trials_applied_check check (applied_rev is null or jsonb_typeof(applied_rev) = 'object')
);
alter table public.team_grading_trials enable row level security;
create index if not exists team_grading_trials_set_idx on public.team_grading_trials (set_id);

create or replace function public.grading_trial_team(p_trial bigint)
 returns smallint language sql stable security definer set search_path to '' as $$
  select team_id from public.team_grading_trials where id = p_trial
$$;


create or replace function public.team_grading_trials_guard()
 returns trigger language plpgsql security definer set search_path to '' as $$
declare
  s record;
  n int;
  c jsonb;
begin
  if auth.uid() is null then          -- service_role(크롤러: noise 시험·판정 결과) — 제한 없음
    return new;
  end if;
  if tg_op = 'INSERT' then
    select id, team_id, status into s from public.team_grading_sets where id = new.set_id;
    if not found or s.team_id <> new.team_id or s.status not in ('open','scored') then
      raise exception 'TEAM_GRADING_TRIAL_SET' using errcode = '23514', hint = '열린 우리 팀 세트에서만 다시 채점할 수 있습니다';
    end if;
    if jsonb_typeof(new.candidates) <> 'array' or jsonb_array_length(new.candidates) not between 1 and 5 then
      raise exception 'TEAM_GRADING_TRIAL_CANDIDATES' using errcode = '23514', hint = '한 번에 바꾸는 규칙은 1~5개입니다';
    end if;
    for c in select value from jsonb_array_elements(new.candidates) loop
      if jsonb_typeof(c) <> 'object' or char_length(coalesce(c->>'sentence', '')) > 200 then
        raise exception 'TEAM_GRADING_TRIAL_CANDIDATES' using errcode = '23514', hint = '규칙 후보 모양이 맞지 않습니다';
      end if;
    end loop;
    -- 하루 5회(KST, 설계 §3-4) — 한도 셈은 잠금 뒤에(#104: read-modify-write 경합 방지)
    perform pg_advisory_xact_lock(hashtext('team_grading_trials'), new.team_id);
    select count(*) into n from public.team_grading_trials
     where team_id = new.team_id and kind = 'trial'
       and created_at >= (date_trunc('day', now() at time zone 'Asia/Seoul') at time zone 'Asia/Seoul');
    if n >= 5 then
      raise exception 'TEAM_GRADING_TRIAL_DAILY_CAP' using errcode = '54000', hint = '다시 채점은 팀당 하루 5번까지입니다';
    end if;
    new.kind := 'trial'; new.status := 'pending'; new.applied_rev := null; new.cost_usd := 0; new.attempts := 0;
    new.created_by := auth.uid(); new.created_at := now(); new.judged_at := null; new.applied_at := null;
    new.copied_at := null; new.note := '';
    -- 첫 시험부터 답 잠금(설계 §4-1 — 정답을 AI 결과에 맞추는 길 차단, 대표만 회색지대 해소)
    update public.team_grading_sets set status = 'scored' where id = new.set_id and status = 'open';
    return new;
  end if;
  -- UPDATE: 판정 끝난 시험을 적용으로만(칸 GRANT = status·applied_rev). 적용 = 세트 끝(확인용 공개)
  if not (old.kind = 'trial' and old.status = 'judged' and new.status = 'applied'
          and new.applied_rev is not null and jsonb_typeof(new.applied_rev) = 'object') then
    raise exception 'TEAM_GRADING_TRIAL_TRANSITION' using errcode = '23514', hint = '판정이 끝난 다시 채점만 적용할 수 있습니다';
  end if;
  select id, status into s from public.team_grading_sets where id = old.set_id;
  if not found or s.status not in ('open','scored') then
    raise exception 'TEAM_GRADING_TRIAL_SET' using errcode = '23514', hint = '이미 끝난 세트입니다';
  end if;
  new.applied_at := now(); new.copied_at := null;
  update public.team_grading_sets set status = 'applied', closed_at = now() where id = old.set_id;
  return new;
end $$;
drop trigger if exists team_grading_trials_guard on public.team_grading_trials;
create trigger team_grading_trials_guard before insert or update on public.team_grading_trials
  for each row execute function public.team_grading_trials_guard();

create policy team_grading_trials_sel on public.team_grading_trials for select to authenticated
  using (public.grading_team_visible(team_id));
create policy team_grading_trials_ins on public.team_grading_trials for insert to authenticated
  with check ((select public.is_approved_user()) and team_id = (select public.my_team()) and kind = 'trial');
create policy team_grading_trials_upd on public.team_grading_trials for update to authenticated
  using ((select public.is_approved_user()) and team_id = (select public.my_team()))
  with check ((select public.is_approved_user()) and team_id = (select public.my_team()));

-- ── 7. 시험 판정(크롤러만 씀) ───────────────────────────────────────────────────────────────────
create table if not exists public.team_grading_trial_verdicts (
  trial_id bigint not null references public.team_grading_trials(id) on delete cascade,
  cand_idx smallint not null,
  news_id uuid not null references public.news_feed(id) on delete cascade,
  verdict boolean not null,
  reason text not null default '',
  input_kind text not null default '',
  model text not null default '',
  cost_usd numeric(10,6) not null default 0,
  reused boolean not null default false,
  created_at timestamptz not null default now(),
  constraint team_grading_trial_verdicts_pkey primary key (trial_id, cand_idx, news_id),
  constraint team_grading_trial_verdicts_kind_check check (input_kind in ('','body','snippet','title'))
);
alter table public.team_grading_trial_verdicts enable row level security;
create index if not exists team_grading_trial_verdicts_news_idx on public.team_grading_trial_verdicts (news_id);
create policy team_grading_trial_verdicts_sel on public.team_grading_trial_verdicts for select to authenticated
  using (public.grading_team_visible(public.grading_trial_team(trial_id)));

-- ── 8. 시험 결과(브라우저가 낱말 결과 → 문장 판정 뒤 다시 씀) ───────────────────────────────────────
create table if not exists public.team_grading_trial_items (
  trial_id bigint not null references public.team_grading_trials(id) on delete cascade,
  news_id uuid not null references public.news_feed(id) on delete cascade,
  level_pred text not null,
  source_pred text not null,
  rule_pred text,
  hit_kind_pred text,
  rule_sentence_pred boolean not null default false,
  updated_at timestamptz not null default now(),
  constraint team_grading_trial_items_pkey primary key (trial_id, news_id),
  constraint team_grading_trial_items_level_check check (level_pred in ('긴급','보통','참고')),
  constraint team_grading_trial_items_source_check check (source_pred in ('common','rule','human','ai','cand')),
  constraint team_grading_trial_items_kind_check check (hit_kind_pred is null or hit_kind_pred in
    ('rule_changed','rule_same','word_hit_false','near','unrelated'))
);
alter table public.team_grading_trial_items enable row level security;
create index if not exists team_grading_trial_items_news_idx on public.team_grading_trial_items (news_id);

create or replace function public.grading_trial_item_ok(p_trial bigint, p_news uuid)
 returns boolean language sql stable security definer set search_path to '' as $$
  -- 쓰기 가능 = 우리 팀 승인 계정 · 그 시험이 trial이고 세트가 열림/채점 중 · 기사가 그 세트에 있음
  select exists (select 1 from public.team_grading_trials t
                   join public.team_grading_sets s on s.id = t.set_id
                   join public.team_grading_items i on i.set_id = s.id and i.news_id = p_news
                  where t.id = p_trial and t.kind = 'trial' and s.status in ('open','scored')
                    and public.is_approved_user() and t.team_id = public.my_team())
$$;

create or replace function public.team_grading_trial_items_touch()
 returns trigger language plpgsql security definer set search_path to '' as $$
begin
  if tg_op = 'UPDATE' then
    new.trial_id := old.trial_id; new.news_id := old.news_id;
  end if;
  new.updated_at := now();
  return new;
end $$;
drop trigger if exists team_grading_trial_items_touch on public.team_grading_trial_items;
create trigger team_grading_trial_items_touch before insert or update on public.team_grading_trial_items
  for each row execute function public.team_grading_trial_items_touch();

create policy team_grading_trial_items_sel on public.team_grading_trial_items for select to authenticated
  using (public.grading_team_visible(public.grading_trial_team(trial_id)));
create policy team_grading_trial_items_ins on public.team_grading_trial_items for insert to authenticated
  with check (public.grading_trial_item_ok(trial_id, news_id));
create policy team_grading_trial_items_upd on public.team_grading_trial_items for update to authenticated
  using (public.grading_trial_item_ok(trial_id, news_id))
  with check (public.grading_trial_item_ok(trial_id, news_id));

-- ── 9. 갈래·점수(설계 §4) — 점수는 서버가 계산, 확인용은 집계만(세트가 끝났거나 관리자면 기사별) ─────────
create or replace function public.grading_level_rank(p text)
 returns integer language sql immutable set search_path to '' as $$
  select case p when '긴급' then 2 when '보통' then 1 when '참고' then 0 end
$$;

create or replace function public.grading_branch(p_ans text, p_team text, p_common text, p_kind text,
                                                 p_sentence boolean, p_source text)
 returns text language sql immutable set search_path to '' as $$
  -- 틀린 갈래(설계 §4-4, AI 0). ok_common = 정답 = 팀 = 공통 / ok = 정답 = 팀(공통과 다름)
  select case
    when p_ans is null or p_team is null then null
    when p_ans = p_team then case when p_ans = p_common then 'ok_common' else 'ok' end
    when p_common = '긴급' and p_team <> '긴급' and p_ans = '긴급' then 'common_urgent_lowered'
    when p_source = 'human' then 'human'
    when public.grading_level_rank(p_ans) > public.grading_level_rank(p_team) then
      case when p_kind = 'word_hit_false' then 'miss_sentence'
           when p_kind in ('rule_changed','rule_same') then 'rule_level'
           else 'miss_word' end
    else
      case when p_kind in ('rule_changed','rule_same') then
             case when p_sentence then 'wide_sentence' else 'wide_word' end
           else 'common_high' end
  end
$$;

create or replace function public.team_grading_score(p_set bigint, p_trial bigint default null)
 returns jsonb language plpgsql stable security definer set search_path to '' set row_security to 'off' as $$
declare
  s record;
  tr record;
  v_admin boolean := public.is_admin();
  v_grader uuid;
  v_final boolean;
  v_tune jsonb;
  v_check jsonb;
  v_advice text := null;
  bc int; tc int; td int; tl int;
begin
  select * into s from public.team_grading_sets where id = p_set;
  if not found then
    raise exception 'TEAM_GRADING_SET_NOT_FOUND' using errcode = 'P0002';
  end if;
  if not public.grading_team_visible(s.team_id) then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  if p_trial is not null then
    select id, kind, status, judged_at, cost_usd into tr from public.team_grading_trials
     where id = p_trial and set_id = p_set;
    if not found then
      raise exception 'TEAM_GRADING_TRIAL_NOT_FOUND' using errcode = 'P0002';
    end if;
  end if;
  v_grader := public.team_grader_uid(s.team_id);
  v_final := s.status in ('applied','closed');

  with it as (
    select i.*,
      (select array_agg(distinct a.answer order by a.answer) from public.team_grading_answers a
        where a.set_id = i.set_id and a.news_id = i.news_id and a.answer <> '모르겠음') as known,
      (select a.answer from public.team_grading_answers a
        where a.set_id = i.set_id and a.news_id = i.news_id and a.user_id = v_grader) as g_ans,
      (select count(*) from public.team_grading_answers a
        where a.set_id = i.set_id and a.news_id = i.news_id) as n_ans
    from public.team_grading_items i where i.set_id = p_set
  ), c as (
    select it.*,
      coalesce(cardinality(known), 0) >= 2 as gray,
      case when coalesce(cardinality(known), 0) >= 2 then null
           when g_ans is not null then nullif(g_ans, '모르겠음')
           when coalesce(cardinality(known), 0) = 1 then known[1]
           else null end as ans
    from it
  ), x as (
    select c.*, ti.level_pred, ti.source_pred, ti.rule_pred, ti.hit_kind_pred, ti.rule_sentence_pred,
      public.grading_branch(c.ans, c.team_level_at_build, c.common_level_at_build, c.hit_kind_at_build,
                            c.rule_sentence_at_build, c.team_source_at_build) as base_branch,
      case when p_trial is null or ti.level_pred is null then null
           else public.grading_branch(c.ans, ti.level_pred, c.common_level_at_build, ti.hit_kind_pred,
                                      ti.rule_sentence_pred, ti.source_pred) end as trial_branch
    from c left join public.team_grading_trial_items ti on ti.trial_id = p_trial and ti.news_id = c.news_id
  ), agg as (
    select x.slot,
      jsonb_build_object(
        'n', count(*),
        'denom', count(*) filter (where ans is not null),
        'gray', count(*) filter (where gray),
        'unknown', count(*) filter (where not gray and ans is null and n_ans > 0),
        'unanswered', count(*) filter (where n_ans = 0),
        'base_match', count(*) filter (where ans is not null and ans = team_level_at_build),
        'common_match', count(*) filter (where ans is not null and ans = common_level_at_build),
        'trial_match', case when p_trial is null then null
                            else count(*) filter (where ans is not null and ans = level_pred) end,
        'trial_missing', case when p_trial is null then null else count(*) filter (where level_pred is null) end,
        'base_lowered', count(*) filter (where base_branch = 'common_urgent_lowered'),
        'trial_lowered', case when p_trial is null then null
                              else count(*) filter (where trial_branch = 'common_urgent_lowered') end,
        'base_branches', coalesce((select jsonb_object_agg(b, k) from (select x2.base_branch b, count(*) k from x x2
                            where x2.slot = x.slot and x2.base_branch is not null group by 1) q), '{}'::jsonb),
        'trial_branches', case when p_trial is null then null
                          else coalesce((select jsonb_object_agg(b, k) from (select x2.trial_branch b, count(*) k from x x2
                            where x2.slot = x.slot and x2.trial_branch is not null group by 1) q), '{}'::jsonb) end,
        'items', case when x.slot = 'tune' or v_final or v_admin then
          jsonb_agg(jsonb_build_object(
            'news_id', news_id, 'seq', seq, 'hit_kind', hit_kind_at_build,
            'common_level', common_level_at_build, 'team_level', team_level_at_build,
            'team_source', team_source_at_build, 'rule_id', rule_id_at_build, 'rule_sentence', rule_sentence_at_build,
            'answer', ans, 'answers', n_ans, 'gray', gray, 'base_branch', base_branch,
            'trial_level', level_pred, 'trial_source', source_pred, 'trial_rule', rule_pred,
            'trial_branch', trial_branch) order by seq)
          else null end
      ) as j
    from x group by x.slot
  )
  select (select j from agg where slot = 'tune'), (select j from agg where slot = 'check') into v_tune, v_check;

  if p_trial is not null and v_check is not null then
    bc := (v_check->>'base_match')::int; tc := (v_check->>'trial_match')::int;
    td := (v_check->>'denom')::int; tl := (v_check->>'trial_lowered')::int;
    -- 적용 권장(안내, 설계 §4-3): 확인용 분모 < 6 = 보류 / 확인용에 공통 긴급 내림 틀림 = 권장 안 함 /
    -- 기준선보다 2건 이상 나쁨 = 과적합 경고 / 기준선 이상 = 권장(같으면 화면이 「확인용 변화 없음」)
    v_advice := case when td < 6 then 'too_few'
                     when (v_check->>'trial_missing')::int > 0 then 'incomplete'
                     when tl > 0 then 'lowered'
                     when tc <= bc - 2 then 'worse'
                     when tc >= bc then 'recommend'
                     else 'neutral' end;
  end if;

  return jsonb_build_object(
    'v', 1,
    'set', jsonb_build_object('id', s.id, 'team_id', s.team_id, 'status', s.status, 'pool_thin', s.pool_thin,
                              'noise_mismatch', s.noise_mismatch, 'noise_compared', s.noise_compared,
                              'built_at', s.built_at, 'note', s.note),
    'trial', case when p_trial is null then null
             else jsonb_build_object('id', tr.id, 'kind', tr.kind, 'status', tr.status, 'judged_at', tr.judged_at,
                                     'cost_usd', tr.cost_usd) end,
    'grader_set', v_grader is not null,
    'is_grader', v_grader is not null and v_grader = auth.uid(),
    'tune', coalesce(v_tune, '{}'::jsonb),
    'check', coalesce(v_check, '{}'::jsonb),
    'advice', v_advice);
end $$;

-- ── 10. 큐 topic team + 구독자 워터마크(설계 §10-4 — 발송은 S3) ──────────────────────────────────
alter table public.subscriber_queue drop constraint if exists subscriber_queue_topic_check;
alter table public.subscriber_queue add constraint subscriber_queue_topic_check
  check (topic = any (array['urgent','assembly','kmcc','news','team']));
alter table public.subscriber_queue drop constraint if exists subscriber_queue_news_shape_check;
alter table public.subscriber_queue add constraint subscriber_queue_news_shape_check check (
  (topic = 'news' and audience ~ '^(c|t:[0-9]+|d:.+)$' and level = any (array['긴급','보통']) and news_url is not null)
  or (topic = 'team' and audience ~ '^t:[0-9]+$' and level is null and news_url is null)
  or (topic <> all (array['news','team']) and audience is null and level is null));
alter table public.telegram_subscribers add column if not exists last_team_sent_at timestamptz;

-- ── 11. 사내 다리 RPC — team_urgency_export(#269)와 같은 꼴(설계 §5-4 ①) ───────────────────────────
create or replace function public.team_rules_export(p_key text, p_since timestamptz default null)
 returns jsonb language plpgsql security definer set search_path to '' set row_security to 'off' as $$
declare
  v_secret text;
  v_rcap constant int := 2000;
  v_vcap constant int := 20000;
  v_rn int;
  v_vn int;
  v_rules jsonb;
  v_verd jsonb;
begin
  if coalesce(nullif(current_setting('request.method', true), ''), 'POST') <> 'POST' then
    raise exception 'team_rules_export: POST only' using errcode = '22023';
  end if;
  select decrypted_secret into v_secret
    from vault.decrypted_secrets where name = 'bridge_team_urgency_key';
  -- 맞을 때만 통과: Vault 값이 없거나 짧거나, 인자가 null이거나 다르면 오류(null 비교가 통과로 새지 않게)
  if v_secret is null or length(v_secret) < 32 or p_key is null or p_key <> v_secret then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  -- 팀 규칙 행 전부(꺼진 행 포함) — anon 13칸과 같은 칸, updated_by(계정 uuid) 없음
  with r as (select id, team_id, "position", mode, level, any_words, and_any, none_words, note, enabled,
                    updated_at, sentence, sentence_rev
               from public.urgency_rules where team_id is not null)
  select count(*), coalesce(jsonb_agg(to_jsonb(r) order by r.id), '[]'::jsonb) into v_rn, v_rules from r;
  if v_rn > v_rcap then
    raise exception 'team_rules_export: rules % > cap %', v_rn, v_rcap using errcode = '54000';
  end if;
  -- 판정 done 행 — anon 9칸과 같은 칸(requested_by·cost_usd 없음), p_since null = 전부
  with v as (select rule_id, sentence_rev, news_id, team_id, status, verdict, reason, input_kind, judged_at
               from public.urgency_rule_verdicts
              where status = 'done' and (p_since is null or judged_at >= p_since))
  select count(*), coalesce(jsonb_agg(to_jsonb(v) order by v.judged_at, v.rule_id, v.sentence_rev, v.news_id), '[]'::jsonb)
    into v_vn, v_verd from v;
  if v_vn > v_vcap then
    raise exception 'team_rules_export: verdicts % > cap %', v_vn, v_vcap using errcode = '54000';
  end if;
  return jsonb_build_object('v', 1, 'generated_at', now(), 'since', p_since,
                            'rules_total', v_rn, 'verdicts_total', v_vn, 'rules', v_rules, 'verdicts', v_verd);
end $$;

-- ── 12. GRANT(#214 — 역할별 명시, service_role 포함) ─────────────────────────────────────────────
revoke all on public.team_grading_sets from public, anon, authenticated, service_role;
grant all on public.team_grading_sets to service_role;
grant select on public.team_grading_sets to authenticated;
grant insert (team_id) on public.team_grading_sets to authenticated;
grant update (status) on public.team_grading_sets to authenticated;

revoke all on public.team_grading_items from public, anon, authenticated, service_role;
grant all on public.team_grading_items to service_role;
grant select (set_id, news_id, seq, hit_kind_at_build, common_level_at_build, team_level_at_build,
              team_source_at_build, rule_id_at_build, rule_sentence_at_build) on public.team_grading_items to authenticated;

revoke all on public.team_grading_answers from public, anon, authenticated, service_role;
grant all on public.team_grading_answers to service_role;
grant select on public.team_grading_answers to authenticated;
grant insert (set_id, news_id, answer) on public.team_grading_answers to authenticated;
grant update (set_id, news_id, answer) on public.team_grading_answers to authenticated;

revoke all on public.team_grading_trials from public, anon, authenticated, service_role;
grant all on public.team_grading_trials to service_role;
grant select on public.team_grading_trials to authenticated;
grant insert (set_id, team_id, candidates) on public.team_grading_trials to authenticated;
grant update (status, applied_rev) on public.team_grading_trials to authenticated;

revoke all on public.team_grading_trial_verdicts from public, anon, authenticated, service_role;
grant all on public.team_grading_trial_verdicts to service_role;
grant select on public.team_grading_trial_verdicts to authenticated;

revoke all on public.team_grading_trial_items from public, anon, authenticated, service_role;
grant all on public.team_grading_trial_items to service_role;
grant select on public.team_grading_trial_items to authenticated;
grant insert (trial_id, news_id, level_pred, source_pred, rule_pred, hit_kind_pred, rule_sentence_pred)
  on public.team_grading_trial_items to authenticated;
grant update (trial_id, news_id, level_pred, source_pred, rule_pred, hit_kind_pred, rule_sentence_pred)
  on public.team_grading_trial_items to authenticated;

revoke all on sequence public.team_grading_sets_id_seq from public, anon, authenticated, service_role;
grant usage, select on sequence public.team_grading_sets_id_seq to service_role, authenticated;
revoke all on sequence public.team_grading_trials_id_seq from public, anon, authenticated, service_role;
grant usage, select on sequence public.team_grading_trials_id_seq to service_role, authenticated;

-- 함수: 정책·RPC 도우미는 authenticated·service_role, 트리거 함수는 service_role만(호출자 권한 불필요),
-- 사내 다리 RPC는 anon·service_role(team_urgency_export와 같게)
revoke all on function public.team_grader_uid(smallint) from public, anon, authenticated, service_role;
grant execute on function public.team_grader_uid(smallint) to authenticated, service_role;
revoke all on function public.grading_team_visible(smallint) from public, anon, authenticated, service_role;
grant execute on function public.grading_team_visible(smallint) to authenticated, service_role;
revoke all on function public.grading_set_team(bigint) from public, anon, authenticated, service_role;
grant execute on function public.grading_set_team(bigint) to authenticated, service_role;
revoke all on function public.grading_trial_team(bigint) from public, anon, authenticated, service_role;
grant execute on function public.grading_trial_team(bigint) to authenticated, service_role;
revoke all on function public.grading_answer_open(bigint) from public, anon, authenticated, service_role;
grant execute on function public.grading_answer_open(bigint) to authenticated, service_role;
revoke all on function public.grading_trial_item_ok(bigint, uuid) from public, anon, authenticated, service_role;
grant execute on function public.grading_trial_item_ok(bigint, uuid) to authenticated, service_role;
revoke all on function public.team_grading_score(bigint, bigint) from public, anon, authenticated, service_role;
grant execute on function public.team_grading_score(bigint, bigint) to authenticated, service_role;
revoke all on function public.grading_level_rank(text) from public, anon, authenticated, service_role;
grant execute on function public.grading_level_rank(text) to service_role;
revoke all on function public.grading_branch(text, text, text, text, boolean, text) from public, anon, authenticated, service_role;
grant execute on function public.grading_branch(text, text, text, text, boolean, text) to service_role;
revoke all on function public.teams_grader_check() from public, anon, authenticated, service_role;
grant execute on function public.teams_grader_check() to service_role;
revoke all on function public.team_grading_sets_guard() from public, anon, authenticated, service_role;
grant execute on function public.team_grading_sets_guard() to service_role;
revoke all on function public.team_grading_answers_touch() from public, anon, authenticated, service_role;
grant execute on function public.team_grading_answers_touch() to service_role;
revoke all on function public.team_grading_trials_guard() from public, anon, authenticated, service_role;
grant execute on function public.team_grading_trials_guard() to service_role;
revoke all on function public.team_grading_trial_items_touch() from public, anon, authenticated, service_role;
grant execute on function public.team_grading_trial_items_touch() to service_role;
revoke all on function public.team_rules_export(text, timestamptz) from public, anon, authenticated, service_role;
grant execute on function public.team_rules_export(text, timestamptz) to anon, service_role;
;
