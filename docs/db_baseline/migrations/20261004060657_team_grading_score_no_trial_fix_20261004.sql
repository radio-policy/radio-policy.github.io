-- 20261004060657 team_grading_score_no_trial_fix_20261004

-- #277 S3 — team_grading_score를 다시 채점 없이(p_trial null) 부르면 'record "tr" is not assigned yet'(55000)으로 실패하던 것.
-- PL/pgSQL은 CASE의 안 쓰는 갈래라도 record 칸(tr.id …)을 값으로 넘기려다 오류를 낸다 — 시험 객체를 if 안에서 만들어 둔다.
-- 계산·반환 모양은 그대로(v 1).
create or replace function public.team_grading_score(p_set bigint, p_trial bigint default null)
 returns jsonb language plpgsql stable security definer set search_path to '' set row_security to 'off' as $$
declare
  s record;
  tr record;
  v_trial jsonb := null;
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
    v_trial := jsonb_build_object('id', tr.id, 'kind', tr.kind, 'status', tr.status, 'judged_at', tr.judged_at,
                                  'cost_usd', tr.cost_usd);
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
    'trial', v_trial,
    'grader_set', v_grader is not null,
    'is_grader', v_grader is not null and v_grader = auth.uid(),
    'tune', coalesce(v_tune, '{}'::jsonb),
    'check', coalesce(v_check, '{}'::jsonb),
    'advice', v_advice);
end $$;
revoke all on function public.team_grading_score(bigint, bigint) from public, anon, authenticated, service_role;
grant execute on function public.team_grading_score(bigint, bigint) to authenticated, service_role;;
