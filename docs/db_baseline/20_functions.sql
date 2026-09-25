-- functions — tools_db_baseline.py가 실DB에서 생성(손으로 고치지 말 것), 비밀 마스킹됨

set check_function_bodies = off;

CREATE OR REPLACE FUNCTION public.admin_delete_chat_log(p_id uuid)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'extensions'
AS $function$
DECLARE n integer;
BEGIN
  IF NOT public.is_admin() THEN
    RAISE EXCEPTION 'AUTH_FAILED';
  END IF;
  DELETE FROM chat_logs WHERE id = p_id;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.admin_delete_chat_log_v2(p_id uuid)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare n integer;
begin
  if not public.is_admin() then raise exception 'AUTH_FAILED'; end if;
  delete from public.chat_logs where id = p_id;
  get diagnostics n = row_count;
  return n;
end $function$
;

CREATE OR REPLACE FUNCTION public.admin_delete_custom_file(p_doc_name text)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'extensions'
AS $function$
DECLARE n integer;
BEGIN
  IF NOT public.is_admin() THEN
    RAISE EXCEPTION 'AUTH_FAILED';
  END IF;
  -- 카테고리 조건 필수 — 다른 카테고리의 동명 문서를 지우지 않기 위함
  DELETE FROM document_chunks
   WHERE doc_category = '추가지식' AND doc_name = p_doc_name;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.admin_delete_kb_document(p_doc_name text)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'extensions'
AS $function$
DECLARE n integer;
BEGIN
  IF NOT public.is_admin() THEN
    RAISE EXCEPTION 'AUTH_FAILED';
  END IF;
  DELETE FROM document_chunks WHERE doc_name = p_doc_name;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.admin_get_chat_log(p_id uuid)
 RETURNS TABLE(question text, answer text, category text, sources text, created_at timestamp with time zone)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'extensions'
AS $function$
begin
  IF NOT public.is_admin() THEN
    raise exception 'AUTH_FAILED';
  end if;
  return query select c.question, c.answer, c.category, c.sources, c.created_at
               from chat_logs c where c.id = p_id;
end $function$
;

CREATE OR REPLACE FUNCTION public.admin_insert_kb_chunks(p_doc_id bigint, p_contents text[], p_embeddings text[])
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'extensions'
AS $function$
DECLARE n integer; i integer;
BEGIN
  IF NOT public.is_admin() THEN
    RAISE EXCEPTION 'AUTH_FAILED';
  END IF;
  IF array_length(p_contents, 1) IS DISTINCT FROM array_length(p_embeddings, 1) THEN
    RAISE EXCEPTION 'LENGTH_MISMATCH';
  END IF;
  n := coalesce(array_length(p_contents, 1), 0);
  FOR i IN 1..n LOOP
    INSERT INTO kb_chunks (doc_id, chunk_idx, content, embedding)
    VALUES (p_doc_id, i - 1, p_contents[i], p_embeddings[i]::vector);
  END LOOP;
  RETURN n;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.admin_list_answer_feedback()
 RETURNS TABLE(fb_id bigint, channel text, rating smallint, reason text, fb_chat_id bigint, fb_created_at timestamp with time zone, fb_updated_at timestamp with time zone, log_id uuid, question text, answer text, category text, sources text, chunk_ids jsonb)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'extensions'
AS $function$
begin
  IF NOT public.is_admin() THEN
    raise exception 'AUTH_FAILED';
  end if;
  return query select f.id, f.channel, f.rating, f.reason, f.chat_id, f.created_at, f.updated_at,
                      c.id, c.question, c.answer, c.category, c.sources, c.chunk_ids
               from answer_feedback f left join chat_logs c on c.id = f.log_id
               order by f.created_at desc limit 500;
end $function$
;

CREATE OR REPLACE FUNCTION public.admin_list_chat_logs(p_limit integer DEFAULT 100)
 RETURNS TABLE(id uuid, question text, category text, created_at timestamp with time zone)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'extensions'
AS $function$
begin
  IF NOT public.is_admin() THEN
    raise exception 'AUTH_FAILED';
  end if;
  return query select c.id, c.question, c.category, c.created_at
               from chat_logs c
               where c.category is distinct from '텔레그램-조문조회'
               order by c.created_at desc
               limit least(greatest(p_limit, 1), 200);
end $function$
;

CREATE OR REPLACE FUNCTION public.admin_set_kb_approval(p_doc_name text, p_approved boolean)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'extensions'
AS $function$
DECLARE n integer;
BEGIN
  IF NOT public.is_admin() THEN
    RAISE EXCEPTION 'AUTH_FAILED';
  END IF;
  UPDATE document_chunks SET is_approved = p_approved WHERE doc_name = p_doc_name;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.admin_update_chunk_embeddings(p_ids bigint[], p_embeddings text[])
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'extensions'
AS $function$
DECLARE n integer := 0; i integer;
BEGIN
  IF NOT public.is_admin() THEN
    RAISE EXCEPTION 'AUTH_FAILED';
  END IF;
  IF array_length(p_ids, 1) IS DISTINCT FROM array_length(p_embeddings, 1) THEN
    RAISE EXCEPTION 'LENGTH_MISMATCH';
  END IF;
  FOR i IN 1..coalesce(array_length(p_ids, 1), 0) LOOP
    UPDATE document_chunks SET embedding = p_embeddings[i]::vector WHERE id = p_ids[i];
    n := n + 1;
  END LOOP;
  RETURN n;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.admin_upsert_kb_document(p_dedup_key text, p_title text, p_concept_type text, p_family text, p_law_type text, p_law_number text, p_enforcement_date text, p_competent_authority text, p_path text, p_description text, p_body_md text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'extensions'
AS $function$
DECLARE new_id bigint;
BEGIN
  IF NOT public.is_admin() THEN
    RAISE EXCEPTION 'AUTH_FAILED';
  END IF;
  IF p_path IS NULL OR p_title IS NULL OR p_body_md IS NULL THEN
    RAISE EXCEPTION 'MISSING_FIELDS';
  END IF;
  -- 동일 path 재적재는 덮어쓰기(idempotent) — cascade로 kb_chunks도 정리
  DELETE FROM kb_documents WHERE path = p_path;
  -- add_law.py의 on_readd_rule과 동일: 같은 dedup_key의 기존 current(다른 법령번호)는 superseded 처리
  IF p_dedup_key IS NOT NULL AND p_dedup_key <> '' THEN
    UPDATE kb_documents
       SET status = 'superseded', superseded_by = p_law_number
     WHERE dedup_key = p_dedup_key AND status = 'current'
       AND law_number IS DISTINCT FROM p_law_number;
  END IF;
  INSERT INTO kb_documents
    (dedup_key, title, concept_type, family, law_type, law_number, enforcement_date,
     competent_authority, status, path, description, body_md)
  VALUES
    (nullif(p_dedup_key,''), p_title, nullif(p_concept_type,''), nullif(p_family,''),
     nullif(p_law_type,''), nullif(p_law_number,''), nullif(p_enforcement_date,''),
     nullif(p_competent_authority,''), 'current', p_path, nullif(p_description,''), p_body_md)
  RETURNING id INTO new_id;
  RETURN new_id;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.batch_update_embeddings(p_ids bigint[], p_embeddings text[])
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
  i int;
BEGIN
  FOR i IN 1..array_length(p_ids, 1) LOOP
    UPDATE document_chunks
    SET embedding = p_embeddings[i]::vector(1024)
    WHERE id = p_ids[i];
  END LOOP;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.charge_ai_usage(p_user uuid, p_kind text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_day   date := (now() at time zone 'Asia/Seoul')::date;   -- KST 일자 = 리셋 기준
  v_hour  timestamptz := date_trunc('hour', now());
  v_prof  public.profiles%rowtype;
  v_team  public.teams%rowtype;
  v_used  int;
  v_hour_used int := 0;
  v_team_used int := 0;
  v_team_limit int := null;
begin
  if p_kind not in ('advisory','general') then
    return jsonb_build_object('ok', false, 'reason', 'bad_kind');
  end if;

  -- fail-closed: 승인·활성 상태가 아니면 어떤 호출도 통과시키지 않는다
  select * into v_prof from public.profiles
    where user_id = p_user and approved and active;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_approved');
  end if;

  -- 같은 팀의 동시 요청을 직렬화(팀 합산 한도가 경쟁으로 넘어가는 것 방지)
  perform pg_advisory_xact_lock(hashtext('aiq-' || coalesce(v_prof.team_id, 0)::text));

  insert into public.advisory_usage as u (user_id, day, kind, count)
  values (p_user, v_day, p_kind, 1)
  on conflict (user_id, day, kind) do update set count = u.count + 1
  returning u.count into v_used;

  if p_kind = 'general' then
    -- 경량 호출은 한도 대상이 아니고 남용 방지 백스톱만.
    -- #152(2026-09-10): 300→100/일 + 시간당 60. 관측된 정상 최대가 30/일이라 3배 여유.
    -- KB 대량 등록 등 정당한 대량 작업은 관리자 profile.unlimited로 우회한다(지침 참조).
    insert into public.ai_usage_hour as h (user_id, hour, count)
    values (p_user, v_hour, 1)
    on conflict (user_id, hour) do update set count = h.count + 1
    returning h.count into v_hour_used;

    if (v_used > 100 or v_hour_used > 60) and not v_prof.unlimited then
      update public.advisory_usage set count = count - 1
        where user_id = p_user and day = v_day and kind = p_kind;
      update public.ai_usage_hour set count = count - 1
        where user_id = p_user and hour = v_hour;
      return jsonb_build_object('ok', false,
        'reason', case when v_hour_used > 60 then 'hourly_backstop' else 'general_backstop' end,
        'used', v_used, 'hour_used', v_hour_used);
    end if;
    return jsonb_build_object('ok', true);
  end if;

  -- 개인 한도
  if not v_prof.unlimited and v_used > v_prof.daily_limit then
    update public.advisory_usage set count = count - 1
      where user_id = p_user and day = v_day and kind = p_kind;
    return jsonb_build_object('ok', false, 'reason', 'member_limit',
      'used', v_prof.daily_limit, 'limit', v_prof.daily_limit);
  end if;

  -- 팀 합산 한도 (개인 잔여가 있어도 팀이 소진되면 차단)
  if v_prof.team_id is not null then
    select * into v_team from public.teams where id = v_prof.team_id;
    if found and not v_team.unlimited then
      v_team_limit := v_team.daily_limit;
      select coalesce(sum(u.count), 0) into v_team_used
        from public.advisory_usage u
        join public.profiles p on p.user_id = u.user_id
       where p.team_id = v_prof.team_id and u.day = v_day and u.kind = 'advisory';
      if v_team_used > v_team.daily_limit then
        update public.advisory_usage set count = count - 1
          where user_id = p_user and day = v_day and kind = p_kind;
        return jsonb_build_object('ok', false, 'reason', 'team_limit',
          'team_used', v_team.daily_limit, 'team_limit', v_team.daily_limit,
          'team_name', v_team.name);
      end if;
    end if;
  end if;

  return jsonb_build_object('ok', true, 'used', v_used, 'limit', v_prof.daily_limit,
    'team_used', v_team_used, 'team_limit', v_team_limit, 'unlimited', v_prof.unlimited);
end $function$
;

CREATE OR REPLACE FUNCTION public.chat_logs_month_count()
 RETURNS integer
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'public', 'extensions'
AS $function$
  select count(*)::int from chat_logs
  where created_at >= date_trunc('month', now() at time zone 'Asia/Seoul');
$function$
;

CREATE OR REPLACE FUNCTION public.check_ai_usage_burst()
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_day date := (now() at time zone 'Asia/Seoul')::date;
  v_general int; v_advisory int; v_prev text; tok text; msg text;
begin
  select coalesce(sum(count) filter (where kind='general'),0),
         coalesce(sum(count) filter (where kind='advisory'),0)
    into v_general, v_advisory
    from public.advisory_usage where day = v_day;
  if v_general <= 100 then return; end if;
  select note into v_prev from public.system_health where key = 'ai_burst_alert';
  if v_prev = v_day::text then return; end if;           -- 하루 1회
  select decrypted_secret into tok from vault.decrypted_secrets where name = 'telegram_bot_token';
  if tok is null then return; end if;
  msg := '⚠️ [AI 호출 폭주] 오늘 대시보드 일반(Haiku) 호출 ' || v_general || '회 (평소 5~30), 자문 ' || v_advisory ||
         '회. 화면 자동 호출 버그나 대량 등록이 의심됩니다 — 운영 상태 탭 확인. 대량 작업은 세션에서(비용 0).';
  perform net.http_post(
    url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
    body    := jsonb_build_object('chat_id', '<OPERATOR_CHAT_ID>', 'text', msg),
    headers := '{"Content-Type":"application/json"}'::jsonb);
  insert into public.system_health (key, updated_at, note) values ('ai_burst_alert', now(), v_day::text)
    on conflict (key) do update set updated_at = now(), note = v_day::text;
end $function$
;

CREATE OR REPLACE FUNCTION public.check_briefing_health()
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
  today_kst date;
  b         record;
  msg       text;
  tok       text;
BEGIN
  today_kst := (NOW() AT TIME ZONE 'Asia/Seoul')::date;

  SELECT length(content) AS len,
         (content LIKE '%[저장 결과]%') AS has_tail
    INTO b
    FROM daily_briefings
   WHERE briefing_date = today_kst;

  IF b IS NULL THEN
    msg := '⚠️ [헬스체크] ' || today_kst::text || ' 모닝 브리핑이 10:00 KST까지 생성되지 않았습니다. GitHub Actions 확인 필요.';
  ELSIF b.len < 1500 THEN
    msg := '⚠️ [헬스체크] ' || today_kst::text || ' 브리핑이 너무 짧습니다(' || b.len || '자). 생성 실패나 간이 브리핑일 수 있습니다.';
  ELSIF NOT b.has_tail THEN
    msg := '⚠️ [헬스체크] ' || today_kst::text || ' 브리핑에 [저장 결과] 꼬리표가 없습니다 — 길이 제한에서 잘렸을 가능성이 큽니다(' || b.len || '자).';
  ELSE
    RETURN;
  END IF;

  SELECT decrypted_secret INTO tok FROM vault.decrypted_secrets WHERE name = 'telegram_bot_token';
  IF tok IS NULL THEN RETURN; END IF;

  PERFORM net.http_post(
    url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
    body    := jsonb_build_object('chat_id', '<OPERATOR_CHAT_ID>', 'text', msg),
    headers := '{"Content-Type": "application/json"}'::jsonb
  );
END;
$function$
;

CREATE OR REPLACE FUNCTION public.check_news_health()
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
  last_news    timestamptz;
  last_crawl   timestamptz;
  hours_stale  numeric;
  crawl_stale  numeric;
  crawler_ok   boolean;
  tok          text;
  msg          text;
BEGIN
  SELECT max(created_at) INTO last_news FROM news_feed;
  hours_stale := EXTRACT(EPOCH FROM (now() - coalesce(last_news, 'epoch')))/3600;

  -- 크롤러 heartbeat: 최근 3시간 내 실행 기록이 있으면 '크롤러 정상'으로 간주
  SELECT updated_at INTO last_crawl FROM system_health WHERE key = 'last_crawl_run';
  crawl_stale := EXTRACT(EPOCH FROM (now() - coalesce(last_crawl, 'epoch')))/3600;
  crawler_ok  := (last_crawl IS NOT NULL AND crawl_stale < 3);

  -- 뉴스가 14h+ 멈췄을 때:
  --  · 크롤러도 안 돎 → 진짜 고장 → 경고
  --  · 크롤러는 도는데 새 뉴스만 없음 → 30h 전까지 침묵(주말 오경보 방지), 30h+면 조용한 실패 의심 → 경고
  IF last_news IS NULL
     OR (hours_stale >= 14 AND NOT crawler_ok)
     OR (hours_stale >= 30) THEN

    SELECT decrypted_secret INTO tok FROM vault.decrypted_secrets WHERE name = 'telegram_bot_token';
    IF tok IS NULL THEN RETURN; END IF;

    msg := '⚠️ [헬스체크] 뉴스 수집이 ' || round(hours_stale, 1) ||
           '시간째 멈춰 있습니다 (마지막 입력: ' ||
           coalesce(to_char(last_news AT TIME ZONE 'Asia/Seoul', 'MM-DD HH24:MI') || ' KST', '없음') || '). ' ||
           CASE WHEN crawler_ok
                THEN '크롤러는 정상 실행 중이나 새 기사가 없습니다 — NAVER 키·필터 점검 권장.'
                ELSE '크롤러도 미실행 — 크롤러/Supabase 트리거(crawl-trigger-hourly)·GitHub Actions 확인 필요.'
           END;

    PERFORM net.http_post(
      url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
      body    := jsonb_build_object('chat_id', '<OPERATOR_CHAT_ID>', 'text', msg),
      headers := '{"Content-Type":"application/json"}'::jsonb
    );
  END IF;
END;$function$
;

CREATE OR REPLACE FUNCTION public.dispatch_github_workflow(p_workflow text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
BEGIN
  PERFORM net.http_post(
    url := 'https://api.github.com/repos/radio-policy/radio-policy.github.io/actions/workflows/'||p_workflow||'/dispatches',
    body := jsonb_build_object('ref','main'),
    headers := jsonb_build_object(
      'Authorization','Bearer '||(SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name='github_pat'),
      'Accept','application/vnd.github+json',
      'User-Agent','supabase-pg-cron-radiopolicy',
      'X-GitHub-Api-Version','2022-11-28'
    )
  );
END;$function$
;

CREATE OR REPLACE FUNCTION public.doc_sections(p_doc text, p_ymd text)
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SET search_path TO 'public'
AS $function$
  with f as (
    select string_agg(c.content, '' order by c.chunk_index) as t
    from document_chunks c
    where c.doc_name = p_doc
  )
  select coalesce(jsonb_agg(t.sec order by t.ord), '[]'::jsonb)
  from f cross join lateral regexp_split_to_table(f.t, '\n(?=## \d{6})') with ordinality as t(sec, ord)
  where p_ymd ~ '^\d{6}$'
    and left(t.sec, 9) = '## ' || p_ymd
$function$
;

CREATE OR REPLACE FUNCTION public.fetch_pending_articles(p_pairs jsonb, p_limit integer DEFAULT 16)
 RETURNS TABLE(law_name text, enf_date text, law_no text, pending_doc text, current_doc text, article_no text, content text)
 LANGUAGE sql
 STABLE
AS $function$
  WITH want AS (
    SELECT DISTINCT e->>'doc' AS doc, e->>'key' AS akey
    FROM jsonb_array_elements(p_pairs) e
    WHERE coalesce(e->>'doc','') <> '' AND coalesce(e->>'key','') <> ''
  ), art AS (
    SELECT p.law_name, p.enf_date, p.law_no, p.doc_name AS pending_doc,
           p.watch_doc_name AS current_doc, c.article_no, w.akey,
           string_agg(c.content, E'\n' ORDER BY c.chunk_index) AS content
    FROM want w
    JOIN law_pending p
      ON p.watch_doc_name = w.doc AND p.sync_state IN ('detected', 'loaded')
    JOIN document_chunks c
      ON c.doc_name = p.doc_name AND c.status = 'pending'
     AND public.norm_article_key(c.article_no) = w.akey
    GROUP BY 1,2,3,4,5,6,7
  ), dedup AS (
    SELECT art.*,
           lag(regexp_replace(content, '\s+', '', 'g'))
             OVER (PARTITION BY current_doc, akey ORDER BY enf_date, article_no) AS prev_norm
    FROM art
  )
  SELECT law_name, enf_date, law_no, pending_doc, current_doc, article_no, content
  FROM dedup
  WHERE content !~ '^제[0-9]+조(의[0-9]+)?\s*삭제'
    AND (prev_norm IS NULL OR prev_norm <> regexp_replace(content, '\s+', '', 'g'))
  ORDER BY enf_date, article_no
  LIMIT p_limit;
$function$
;

CREATE OR REPLACE FUNCTION public.get_my_quota()
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_day date := (now() at time zone 'Asia/Seoul')::date;
  v_prof public.profiles%rowtype;
  v_team public.teams%rowtype;
  v_used int := 0; v_team_used int := 0;
begin
  select * into v_prof from public.profiles where user_id = auth.uid();
  if not found then return jsonb_build_object('ok', false, 'reason', 'no_profile'); end if;

  select coalesce(count, 0) into v_used from public.advisory_usage
   where user_id = auth.uid() and day = v_day and kind = 'advisory';

  if v_prof.team_id is not null then
    select * into v_team from public.teams where id = v_prof.team_id;
    select coalesce(sum(u.count), 0) into v_team_used
      from public.advisory_usage u join public.profiles p on p.user_id = u.user_id
     where p.team_id = v_prof.team_id and u.day = v_day and u.kind = 'advisory';
  end if;

  return jsonb_build_object(
    'ok', true, 'approved', v_prof.approved, 'active', v_prof.active, 'role', v_prof.role,
    'unlimited', v_prof.unlimited,
    'used', coalesce(v_used, 0), 'limit', v_prof.daily_limit,
    'team_name', v_team.name, 'team_used', coalesce(v_team_used, 0),
    'team_limit', v_team.daily_limit, 'team_unlimited', coalesce(v_team.unlimited, false));
end $function$
;

CREATE OR REPLACE FUNCTION public.gh_api_get(p_path text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
declare rid bigint;
begin
  select net.http_get(
    url := 'https://api.github.com' || p_path,
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'github_pat'),
      'Accept', 'application/vnd.github+json',
      'User-Agent', 'supabase-pg-cron-radiopolicy',
      'X-GitHub-Api-Version', '2022-11-28')
  ) into rid;
  return rid;
end;$function$
;

CREATE OR REPLACE FUNCTION public.handle_new_user()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_name text := coalesce(new.raw_user_meta_data->>'name', '');
  tok text;
begin
  insert into public.profiles (user_id, name)
  values (new.id, v_name)
  on conflict (user_id) do nothing;

  begin
    select decrypted_secret into tok from vault.decrypted_secrets where name = 'telegram_bot_token';
    if tok is not null then
      perform net.http_post(
        url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
        body    := jsonb_build_object(
          'chat_id', '<OPERATOR_CHAT_ID>',
          'text', '🆕 대시보드 가입 신청' || E'\n'
               || '이름: ' || coalesce(nullif(v_name, ''), '(미입력)') || E'\n'
               || '이메일: ' || coalesce(new.email, '?') || E'\n'
               || '→ 대시보드 설정 > 계정 관리에서 팀·역할 지정 후 승인'
        ),
        headers := '{"Content-Type":"application/json"}'::jsonb,
        timeout_milliseconds := 10000
      );
    end if;
  exception when others then
    raise warning '[가입 알림 실패(가입은 정상)] %', sqlerrm;
  end;

  return new;
end $function$
;

CREATE OR REPLACE FUNCTION public.insert_kb_chunks(p_doc_id bigint, p_contents text[], p_embeddings text[])
 RETURNS integer
 LANGUAGE plpgsql
AS $function$
declare i int; n int;
begin
  n := coalesce(array_length(p_contents,1),0);
  for i in 1..n loop
    insert into public.kb_chunks(doc_id, chunk_idx, content, embedding)
    values (p_doc_id, i-1, p_contents[i], p_embeddings[i]::vector);
  end loop;
  return n;
end; $function$
;

CREATE OR REPLACE FUNCTION public.is_admin()
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select exists (select 1 from profiles
                 where user_id = auth.uid() and role = 'admin' and approved and active) $function$
;

CREATE OR REPLACE FUNCTION public.is_approved_user()
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select exists (select 1 from profiles
                 where user_id = auth.uid() and approved and active)
$function$
;

CREATE OR REPLACE FUNCTION public.is_issue_editor()
 RETURNS boolean
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select exists (
    select 1 from public.profiles p
    where p.user_id = auth.uid()
      and p.approved and p.active
      and (p.role = 'admin' or p.can_edit_issues)
  );
$function$
;

CREATE OR REPLACE FUNCTION public.is_leader()
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select exists (select 1 from profiles
                 where user_id = auth.uid() and role = 'leader' and approved and active) $function$
;

CREATE OR REPLACE FUNCTION public.kb_doc_names(p_status text DEFAULT NULL::text, p_category text DEFAULT NULL::text)
 RETURNS TABLE(doc_name text, doc_category text)
 LANGUAGE sql
 STABLE
 SET search_path TO 'public', 'pg_catalog'
AS $function$
  select c.doc_name, min(c.doc_category) as doc_category
  from public.document_chunks c
  where (p_status is null or c.status = p_status)
    and (p_category is null or c.doc_category = p_category)
  group by c.doc_name
  order by c.doc_name;
$function$
;

CREATE OR REPLACE FUNCTION public.law_track_recent(p_days integer DEFAULT 180, p_limit integer DEFAULT 25)
 RETURNS TABLE(law_nm text, law_type text, ann_type text, public_dt text, enf_dt text, summary text)
 LANGUAGE sql
 STABLE
AS $function$
  with latest as (
    select distinct on (case when a.law_type = 'lsAnc' then 'lsAnc::' || coalesce(a.law_nm, '') else coalesce(a.law_nm, '') end)
           a.law_nm, a.law_type, a.ann_type, a.public_dt, a.enf_dt, a.summary
    from law_amendments a
    order by case when a.law_type = 'lsAnc' then 'lsAnc::' || coalesce(a.law_nm, '') else coalesce(a.law_nm, '') end,
             regexp_replace(coalesce(a.public_dt, ''), '\D', '', 'g') desc
  )
  select l.law_nm, l.law_type, l.ann_type, l.public_dt, l.enf_dt, l.summary
  from latest l
  where l.law_type = 'lsAnc'
     or regexp_replace(coalesce(l.enf_dt, ''), '\D', '', 'g') >= to_char(now() at time zone 'Asia/Seoul', 'YYYYMMDD')
     or regexp_replace(coalesce(l.public_dt, ''), '\D', '', 'g') >= to_char((now() at time zone 'Asia/Seoul') - make_interval(days => p_days), 'YYYYMMDD')
  order by regexp_replace(coalesce(l.public_dt, ''), '\D', '', 'g') desc
  limit p_limit;
$function$
;

CREATE OR REPLACE FUNCTION public.lawmap_snapshot()
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SET search_path TO 'public'
AS $function$
  select jsonb_build_object(
    'nodes', (
      select coalesce(jsonb_agg(jsonb_build_object(
        'id', id, 'name', name, 'node_type', node_type,
        'description', description, 'doc_name', doc_name, 'source', source
      ) order by id), '[]'::jsonb)
      from law_graph_nodes
    ),
    'edges', (
      select coalesce(jsonb_agg(jsonb_build_object(
        'id', id, 'source_id', source_id, 'target_id', target_id,
        'relation_type', relation_type, 'description', description,
        'source', source, 'weight', weight
      ) order by id), '[]'::jsonb)
      from law_graph_edges
    )
  );
$function$
;

CREATE OR REPLACE FUNCTION public.limit_anon_lawmap_request()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  n_hour int;
  n_open int;
begin
  if new.origin is distinct from 'request' or new.created_by is not null then
    return new;
  end if;
  select count(*) into n_hour from lawmap_proposals
   where origin = 'request' and created_by is null and created_at > now() - interval '1 hour';
  if n_hour >= 10 then
    raise exception '관계도 추가 요청이 한 시간에 너무 많이 들어왔습니다. 잠시 후 다시 시도해 주세요.';
  end if;
  select count(*) into n_open from lawmap_proposals
   where origin = 'request' and created_by is null and status = 'pending';
  if n_open >= 20 then
    raise exception '미처리 요청이 많습니다. 운영자 검토 후 다시 시도해 주세요.';
  end if;
  return new;
end $function$
;

CREATE OR REPLACE FUNCTION public.list_kb_documents()
 RETURNS TABLE(doc_category text, doc_name text, chunks bigint, embedded bigint, approved boolean, status text)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT min(doc_category) AS doc_category, doc_name, count(*) AS chunks,
         count(*) FILTER (WHERE embedding IS NOT NULL) AS embedded,
         bool_and(is_approved) AS approved,
         min(status) AS status
  FROM document_chunks
  WHERE doc_category IS DISTINCT FROM '보도자료'
  GROUP BY doc_name
  ORDER BY doc_name;
$function$
;

CREATE OR REPLACE FUNCTION public.list_kb_guide_docs()
 RETURNS TABLE(id bigint, title text, path text, description text, concept_type text, competent_authority text, chunks bigint, has_table boolean)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select d.id, d.title, d.path, d.description,
         d.concept_type, d.competent_authority,
         coalesce(c.n, 0) as chunks,
         (d.body_md ~ '\n\s*\|.*\|') as has_table
  from kb_documents d
  left join (select doc_id, count(*) n from kb_chunks group by doc_id) c on c.doc_id = d.id
  where d.status = 'current'
  order by d.path;
$function$
;

CREATE OR REPLACE FUNCTION public.match_chunks_semantic(query_embedding vector, match_threshold double precision DEFAULT 0.5, match_count integer DEFAULT 8, only_current boolean DEFAULT true)
 RETURNS TABLE(id bigint, doc_name text, doc_category text, chunk_index integer, content text, notice_no text, article_no text, effective_date text, similarity double precision)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET "hnsw.ef_search" TO '100'
AS $function$
  SELECT
    id, doc_name, doc_category, chunk_index, content,
    notice_no, article_no, effective_date,
    (1 - (embedding <=> query_embedding))::float AS similarity
  FROM document_chunks
  WHERE embedding IS NOT NULL
    AND is_approved
    AND (NOT only_current OR status = 'current')
    AND (1 - (embedding <=> query_embedding)) > match_threshold
  ORDER BY embedding <=> query_embedding
  LIMIT match_count;
$function$
;

CREATE OR REPLACE FUNCTION public.match_chunks_semantic_exact(query_embedding vector, match_threshold double precision DEFAULT 0.5, match_count integer DEFAULT 8, only_current boolean DEFAULT true)
 RETURNS TABLE(id bigint, doc_name text, doc_category text, chunk_index integer, content text, notice_no text, article_no text, effective_date text, similarity double precision)
 LANGUAGE sql
 STABLE SECURITY DEFINER
AS $function$
  select
    id, doc_name, doc_category, chunk_index, content,
    notice_no, article_no, effective_date,
    (1 - (embedding <=> query_embedding))::float as similarity
  from document_chunks
  where embedding is not null
    and is_approved
    and (not only_current or status = 'current')
    and (1 - (embedding <=> query_embedding)) > match_threshold
  order by (embedding <=> query_embedding) + 0.0
  limit match_count;
$function$
;

CREATE OR REPLACE FUNCTION public.match_chunks_semantic_in_doc(query_embedding vector, p_doc_name text, match_count integer DEFAULT 12)
 RETURNS TABLE(id bigint, doc_name text, chunk_index integer, content text, article_no text, similarity double precision)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select id, doc_name, chunk_index, content, article_no,
         (1 - (embedding <=> query_embedding))::float as similarity
  from document_chunks
  where doc_name = p_doc_name
    and embedding is not null
  order by embedding <=> query_embedding
  limit match_count;
$function$
;

CREATE OR REPLACE FUNCTION public.match_kb_chunks_semantic(query_embedding vector, match_threshold double precision DEFAULT 0.35, match_count integer DEFAULT 6, only_current boolean DEFAULT true)
 RETURNS TABLE(doc_id bigint, title text, law_type text, law_number text, enforcement_date text, status text, concept_type text, path text, chunk_idx integer, content text, similarity double precision)
 LANGUAGE sql
 STABLE
 SET "hnsw.ef_search" TO '100'
AS $function$
  select d.id, d.title, d.law_type, d.law_number, d.enforcement_date,
         d.status, d.concept_type, d.path, c.chunk_idx, c.content,
         (1 - (c.embedding <=> query_embedding))::float as similarity
  from public.kb_chunks c
  join public.kb_documents d on d.id = c.doc_id
  where c.embedding is not null
    and (not only_current or d.status = 'current')
    and (1 - (c.embedding <=> query_embedding)) > match_threshold
  order by c.embedding <=> query_embedding
  limit match_count;
$function$
;

CREATE OR REPLACE FUNCTION public.match_law_articles_semantic(query_embedding vector, match_threshold double precision DEFAULT 0.0, match_count integer DEFAULT 8, only_current boolean DEFAULT true)
 RETURNS TABLE(id bigint, doc_name text, doc_category text, chunk_index integer, content text, notice_no text, article_no text, effective_date text, similarity double precision)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET "hnsw.ef_search" TO '300'
AS $function$
  select id, doc_name, doc_category, chunk_index, content,
         notice_no, article_no, effective_date,
         (1 - dist)::float as similarity
  from (
    select id, doc_name, doc_category, chunk_index, content, notice_no, article_no, effective_date,
           (embedding <=> query_embedding) as dist
    from document_chunks
    where embedding is not null
      and is_approved
      and (not only_current or status = 'current')
      and article_no is not null
    order by embedding <=> query_embedding
    limit greatest(match_count * 30, 300)
  ) c
  where (1 - dist) > match_threshold
  order by
    dist
    - (case when article_no ~ '^\d+조' then 0.08 else 0 end)
    + (case when article_no ~ '^(부칙|서식|별지)' then 0.05 else 0 end)
    + (case when doc_name ~* '\.(pdf|md|docx|hwp)$' then 0.10 else 0 end)
  limit match_count;
$function$
;

CREATE OR REPLACE FUNCTION public.match_news_semantic(query_embedding vector, match_count integer DEFAULT 8)
 RETURNS TABLE(id uuid, title text, published_at timestamp with time zone, url text, similarity double precision)
 LANGUAGE sql
 STABLE
AS $function$
  select n.id, n.title, n.published_at, n.url,
         1 - (ne.embedding <=> query_embedding) as similarity
  from news_embeddings ne join news_feed n on n.id = ne.news_id
  order by ne.embedding <=> query_embedding
  limit match_count;
$function$
;

CREATE OR REPLACE FUNCTION public.minutes_index()
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SET search_path TO 'public'
AS $function$
  with d as (
    select c.doc_name, string_agg(c.content, '' order by c.chunk_index) as full_text
    from document_chunks c
    where c.doc_category = '회의록'
    group by c.doc_name
  ), s as (
    select d.doc_name, t.sec, t.ord
    from d cross join lateral regexp_split_to_table(d.full_text, '\n(?=## \d{6} )') with ordinality as t(sec, ord)
  )
  select coalesce(jsonb_agg(jsonb_build_array(
           s.doc_name,
           substring(s.sec from '^## (\d{6}) '),
           substring(s.sec from '^## \d{6} ([^\r\n]+)'),
           substring(left(s.sec, 900) from '(?n)^요약:\s*(.+)$'),
           substring(s.sec from '\(원문:\s*(https?:[^\s)]+)\)'))
         order by s.doc_name, s.ord), '[]'::jsonb)
  from s
  where s.sec ~ '^## \d{6} [^\r\n]'
$function$
;

CREATE OR REPLACE FUNCTION public.my_team()
 RETURNS smallint
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select team_id from profiles where user_id = auth.uid() $function$
;

CREATE OR REPLACE FUNCTION public.news_feed_edit_guard()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
begin
  -- 서버 쪽 경로(크롤러·PC 스크립트·마이그레이션)는 검사 대상이 아니다
  if current_user in ('service_role', 'postgres', 'supabase_admin', 'supabase_auth_admin') then
    return new;
  end if;

  if (new.importance is distinct from old.importance
      or new.urgency is distinct from old.urgency
      or new.locked  is distinct from old.locked)
     and not public.is_admin() then
    raise exception '뉴스 중요도·잠금 변경은 관리자만 가능합니다(팀별 중요도 기능 준비 중)'
      using errcode = '42501';
  end if;

  return new;
end $function$
;

CREATE OR REPLACE FUNCTION public.norm_article_key(a text)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE
AS $function$
  SELECT (regexp_match(regexp_replace(coalesce(a, ''), '^제', ''),
                       '^([0-9]+조(?:의[0-9]+)?)'))[1];
$function$
;

CREATE OR REPLACE FUNCTION public.notify_lawmap_request()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  tok text;
  who text;
begin
  if new.origin is distinct from 'request' then
    return new;
  end if;
  if new.created_by is null then
    who := '비로그인 · ' || coalesce(nullif(new.requester, ''), '(이름 미입력)') || ' (자기 기재, 미확인)';
  else
    who := coalesce(nullif(new.requester, ''), '(미상)');
  end if;
  begin
    select decrypted_secret into tok from vault.decrypted_secrets where name = 'telegram_bot_token';
    if tok is not null then
      perform net.http_post(
        url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
        body    := jsonb_build_object(
          'chat_id', '<OPERATOR_CHAT_ID>',
          'text', '🗺️ 관계도 추가 요청' || E'\n'
               || '요청자: ' || who || E'\n'
               || '주제: ' || coalesce(nullif(new.topic, ''), '(미입력)') || E'\n'
               || coalesce(nullif(new.question, ''), '(사유 없음)') || E'\n'
               || '→ 대시보드 법령 관계도 > 검토 대기에서 처리'
        ),
        headers := '{"Content-Type":"application/json"}'::jsonb,
        timeout_milliseconds := 10000
      );
    end if;
  exception when others then
    raise warning '[관계도 요청 알림 실패(요청은 정상 저장)] %', sqlerrm;
  end;
  return new;
end $function$
;

CREATE OR REPLACE FUNCTION public.ops_ai_usage_today()
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_day date := (now() at time zone 'Asia/Seoul')::date;
  v_from timestamptz := (v_day::timestamp at time zone 'Asia/Seoul');
  r jsonb;
begin
  if not public.is_admin() then return jsonb_build_object('ok', false, 'reason', 'not_admin'); end if;
  select jsonb_build_object('ok', true,
    'advisory', coalesce((select sum(count) from public.advisory_usage where day = v_day and kind='advisory'),0),
    'general',  coalesce((select sum(count) from public.advisory_usage where day = v_day and kind='general'),0),
    'general_yday', coalesce((select sum(count) from public.advisory_usage where day = v_day - 1 and kind='general'),0),
    'tokens', coalesce((select jsonb_agg(t) from (
        select host, count(*) calls, sum(input_tokens) input_tokens, sum(cache_read) cache_read,
               sum(cache_write) cache_write, sum(output_tokens) output_tokens
          from public.api_usage where ts >= v_from group by host order by host) t), '[]'::jsonb)
  ) into r;
  return r;
end $function$
;

CREATE OR REPLACE FUNCTION public.ops_system_prompt_hash()
 RETURNS jsonb
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public', 'pg_catalog'
AS $function$
  select coalesce(
    (select jsonb_build_object('ok', true, 'len', length(value),
                               'sha256', encode(sha256(convert_to(value, 'UTF8')), 'hex'))
       from app_config where key = 'system_prompt'),
    jsonb_build_object('ok', false));
$function$
;

CREATE OR REPLACE FUNCTION public.pending_versions_for_docs(p_docs text[])
 RETURNS TABLE(law_name text, current_doc text, law_no text, enf_date text, loaded boolean)
 LANGUAGE sql
 STABLE
AS $function$
  SELECT p.law_name, p.watch_doc_name, p.law_no, p.enf_date,
         (p.sync_state = 'loaded')
  FROM law_pending p
  WHERE p.sync_state IN ('detected', 'loaded')
    AND p.watch_doc_name = ANY(p_docs)
  ORDER BY p.law_name, p.enf_date;
$function$
;

CREATE OR REPLACE FUNCTION public.press_index()
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SET search_path TO 'public'
AS $function$
  select coalesce(jsonb_agg(jsonb_build_array(c.doc_name, l.line) order by c.id, l.ord), '[]'::jsonb)
  from document_chunks c
  cross join lateral regexp_split_to_table(c.content, E'\n') with ordinality as l(line, ord)
  where c.doc_category = '보도자료'
    and c.content ~ '## [0-9]{6}'
    and left(l.line, 2) = '##'
$function$
;

CREATE OR REPLACE FUNCTION public.refund_ai_usage(p_user uuid, p_kind text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare v_day date := (now() at time zone 'Asia/Seoul')::date;
begin
  update public.advisory_usage set count = count - 1
   where user_id = p_user and day = v_day and kind = p_kind and count > 0;
end $function$
;

CREATE OR REPLACE FUNCTION public.search_chunks_keywords(p_keywords text[], p_per_kw integer DEFAULT 4)
 RETURNS TABLE(kw_ord integer, id bigint, doc_name text, doc_category text, chunk_index integer, content text, notice_no text, article_no text, effective_date text)
 LANGUAGE sql
 STABLE
 SET enable_bitmapscan TO 'off'
AS $function$
with recursive kws as (
  select kw, ord::int as ord, (kw ~ '[A-Za-z]') as ci
  from unnest(p_keywords) with ordinality as k(kw, ord)
),
m as materialized (
  select c.id, c.article_no, (c.doc_name ~ '전파|통신|무선|주파수') as dom, kk.kw_ords, kk.t_ords
  from document_chunks c
  cross join lateral (
    select array_agg(x.ord order by x.ord) filter (where x.hit)  as kw_ords,
           array_agg(x.ord order by x.ord) filter (where x.thit) as t_ords
    from (
      select k.ord,
             case when k.ci then c.content ilike '%' || k.kw || '%' else strpos(c.content, k.kw) > 0 end as hit,
             case when k.ci then coalesce(c.article_no, '') ilike '%' || k.kw || '%' else strpos(coalesce(c.article_no, ''), k.kw) > 0 end as thit
      from kws k
    ) x
  ) kk
  where c.is_approved and c.status = 'current' and kk.kw_ords is not null
),
g(kord, picked, out_ids) as (
  select 0, '{}'::bigint[], '{}'::bigint[]
  union all
  select g.kord + 1, g.picked || s.ids, s.ids
  from g
  cross join lateral (
    select coalesce(array_agg(z.id order by z.rn), '{}') as ids
    from (
      select m.id,
             row_number() over (order by cardinality(m.kw_ords) desc,
                                         coalesce((g.kord + 1) = any(m.t_ords), false) desc,
                                         (m.article_no ~ '^\d+조') desc,
                                         m.dom desc,
                                         m.id) as rn
      from m
      where (g.kord + 1) = any(m.kw_ords) and not (m.id = any(g.picked))
    ) z
    where z.rn <= p_per_kw
  ) s
  where g.kord < (select count(*) from kws)
)
select g.kord, c.id, c.doc_name, c.doc_category, c.chunk_index, c.content, c.notice_no, c.article_no, c.effective_date
from g
cross join lateral unnest(g.out_ids) with ordinality as u(id, rn)
join document_chunks c on c.id = u.id
where g.kord > 0
order by g.kord, u.rn;
$function$
;

CREATE OR REPLACE FUNCTION public.search_chunks_trgm(query_text text, match_threshold double precision DEFAULT 0.12, match_count integer DEFAULT 8, only_current boolean DEFAULT true)
 RETURNS TABLE(id bigint, doc_name text, doc_category text, chunk_index integer, content text, notice_no text, article_no text, effective_date text, trgm_score double precision)
 LANGUAGE sql
 STABLE SECURITY DEFINER
AS $function$
  SELECT
    id, doc_name, doc_category, chunk_index, content,
    notice_no, article_no, effective_date,
    extensions.word_similarity(query_text, content)::float AS trgm_score
  FROM document_chunks
  WHERE is_approved
    AND (NOT only_current OR status = 'current')
    AND extensions.word_similarity(query_text, content) > match_threshold
  ORDER BY trgm_score DESC
  LIMIT match_count;
$function$
;

CREATE OR REPLACE FUNCTION public.search_documents_by_keywords(keywords text[], match_count integer DEFAULT 5)
 RETURNS TABLE(id bigint, doc_name text, doc_category text, content text, score integer)
 LANGUAGE plpgsql
 STABLE
AS $function$
declare
  kw text;
  cond_parts text[] := '{}';
  score_parts text[] := '{}';
  sql_str text;
begin
  foreach kw in array keywords loop
    cond_parts := array_append(cond_parts,
      format('lower(content) like %L', '%' || lower(kw) || '%'));
    score_parts := array_append(score_parts,
      format('(case when lower(content) like %L then 1 else 0 end)', '%' || lower(kw) || '%'));
  end loop;

  sql_str := format(
    'select id, doc_name, doc_category, content,
            (%s)::int as score
     from document_chunks
     where %s
     order by (%s) desc, length(content) asc
     limit %s',
    array_to_string(score_parts, ' + '),
    array_to_string(cond_parts, ' or '),
    array_to_string(score_parts, ' + '),
    match_count
  );

  return query execute sql_str;
end;
$function$
;

CREATE OR REPLACE FUNCTION public.search_kb_chunks_trgm(query_text text, match_threshold double precision DEFAULT 0.10, match_count integer DEFAULT 6, only_current boolean DEFAULT true)
 RETURNS TABLE(doc_id bigint, title text, law_type text, law_number text, enforcement_date text, status text, concept_type text, path text, chunk_idx integer, content text, trgm_score double precision)
 LANGUAGE sql
 STABLE
AS $function$
  select d.id, d.title, d.law_type, d.law_number, d.enforcement_date,
         d.status, d.concept_type, d.path, c.chunk_idx, c.content,
         extensions.word_similarity(query_text, c.content)::float as trgm_score
  from public.kb_chunks c
  join public.kb_documents d on d.id = c.doc_id
  where (not only_current or d.status = 'current')
    and extensions.word_similarity(query_text, c.content) > match_threshold
  order by trgm_score desc
  limit match_count;
$function$
;

CREATE OR REPLACE FUNCTION public.search_law_articles_kw(p_keywords text[], p_title_limit integer DEFAULT 40, p_content_limit integer DEFAULT 10)
 RETURNS TABLE(kw_ord integer, hit_col text, id bigint, doc_name text, article_no text, content text)
 LANGUAGE sql
 STABLE
 SET enable_bitmapscan TO 'off'
AS $function$
with kws as (
  select kw, ord::int as ord, (kw ~ '[A-Za-z]') as ci
  from unnest(p_keywords) with ordinality as k(kw, ord)
),
m as materialized (
  select c.id, (c.doc_name ~ '전파|통신|무선|주파수') as dom, kk.t_ords, kk.c_ords
  from document_chunks c
  cross join lateral (
    select array_agg(x.ord order by x.ord) filter (where x.thit) as t_ords,
           array_agg(x.ord order by x.ord) filter (where x.hit)  as c_ords
    from (
      select k.ord,
             case when k.ci then c.content ilike '%' || k.kw || '%' else strpos(c.content, k.kw) > 0 end as hit,
             case when k.ci then c.article_no ilike '%' || k.kw || '%' else strpos(c.article_no, k.kw) > 0 end as thit
      from kws k
    ) x
  ) kk
  where c.is_approved and c.status = 'current' and c.article_no is not null
    and c.doc_name !~* '\.(pdf|md|docx|hwp)$'
    and (kk.t_ords is not null or kk.c_ords is not null)
),
pick as (
  select k.ord as kw_ord, t.hit_col, t.id, t.rn
  from kws k
  cross join lateral (
    (select 'title'::text as hit_col, m.id,
            row_number() over (order by cardinality(m.t_ords) desc, coalesce(cardinality(m.c_ords), 0) desc, m.dom desc, m.id) as rn
     from m where k.ord = any(m.t_ords)
     order by rn limit p_title_limit)
    union all
    (select 'content'::text, m.id,
            row_number() over (order by cardinality(m.c_ords) desc, coalesce(cardinality(m.t_ords), 0) desc, m.dom desc, m.id) as rn
     from m where k.ord = any(m.c_ords)
     order by rn limit p_content_limit)
  ) t
)
select p.kw_ord, p.hit_col, c.id, c.doc_name, c.article_no, c.content
from pick p
join document_chunks c on c.id = p.id
order by p.kw_ord, (p.hit_col = 'title') desc, p.rn;
$function$
;

CREATE OR REPLACE FUNCTION public.speaker_index()
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SET search_path TO 'public'
AS $function$
  select coalesce(jsonb_agg(jsonb_build_array(s.speaker, s.n)), '[]'::jsonb)
  from (select speaker, count(*) as n
        from assembly_speeches
        where speaker is not null
        group by speaker) s
$function$
;

CREATE OR REPLACE FUNCTION public.submit_answer_feedback(p_log_id uuid, p_rating smallint, p_reason text DEFAULT NULL::text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'extensions'
AS $function$
declare v_channel text;
begin
  if p_rating not in (1,-1) then raise exception 'BAD_RATING'; end if;
  select channel into v_channel from chat_logs where id = p_log_id;
  if v_channel is null then raise exception 'LOG_NOT_FOUND'; end if;
  insert into answer_feedback (log_id, channel, rating, reason)
  values (p_log_id, v_channel, p_rating, p_reason)
  on conflict (log_id) do update
    set rating = excluded.rating,
        reason = coalesce(excluded.reason, answer_feedback.reason),
        updated_at = now();
end $function$
;

CREATE OR REPLACE FUNCTION public.trigger_admin_report()
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
begin
  perform net.http_post(
    url := 'https://zwkjedumfuhodckmtxxn.supabase.co/functions/v1/admin-daily-report',
    body := '{}'::jsonb,
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'x-cron-secret', (select decrypted_secret from vault.decrypted_secrets where name = 'admin_report_cron_secret')
    )
  );
end;
$function$
;

CREATE OR REPLACE FUNCTION public.trigger_briefing_if_missing()
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
  today_kst date;
  briefing_exists boolean;
BEGIN
  today_kst := (NOW() AT TIME ZONE 'Asia/Seoul')::date;
  SELECT EXISTS (SELECT 1 FROM daily_briefings WHERE briefing_date = today_kst) INTO briefing_exists;
  IF NOT briefing_exists THEN
    PERFORM net.http_post(
      url := 'https://api.github.com/repos/radio-policy/radio-policy.github.io/actions/workflows/morning_briefing.yml/dispatches',
      body := jsonb_build_object('ref','main'),
      headers := jsonb_build_object(
        'Authorization', 'Bearer ' || (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name='github_pat'),
        'Accept','application/vnd.github+json',
        'User-Agent','supabase-pg-cron-radiopolicy',
        'X-GitHub-Api-Version','2022-11-28'
      )
    );
  END IF;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.trigger_subscriber_briefing()
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
begin
  perform net.http_post(
    url := 'https://zwkjedumfuhodckmtxxn.supabase.co/functions/v1/send-subscriber-briefing',
    body := '{}'::jsonb,
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'x-cron-secret', (select decrypted_secret from vault.decrypted_secrets where name = 'subscriber_cron_secret')
    )
  );
end;
$function$
;

CREATE OR REPLACE FUNCTION public.update_tech_terms_updated_at()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.urgency_rules_touch()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'public'
AS $function$
begin
  new.updated_at := now();
  new.updated_by := coalesce(auth.uid(), new.updated_by);
  return new;
end $function$
;

CREATE OR REPLACE FUNCTION public.watchdog_scan(p_dry_run boolean DEFAULT true)
 RETURNS text
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  r         record;
  probs     text[] := '{}';
  keys      text[] := '{}';
  fail_n    text;
  cur_set   text;
  prev_set  text;
  prev_keys text[] := '{}';
  new_keys  text[] := '{}';
  lines     text[] := '{}';
  tok       text;
  msg       text;
  now_kst   text;
  i         int;
begin
  now_kst := to_char(now() at time zone 'Asia/Seoul', 'MM-DD HH24:MI');

  for r in
    select t.key, t.thresh_h, t.label,
           sh.updated_at, sh.note,
           extract(epoch from (now() - sh.updated_at))/3600 as age_h
    from watchdog_targets t
    left join system_health sh on sh.key = t.key
    where t.active
    order by t.key
  loop
    if r.updated_at is null then
      probs := probs || (r.label || ': heartbeat 없음');
      keys  := keys  || (r.key || ':missing');
    elsif r.age_h >= r.thresh_h then
      probs := probs || (r.label || ' ' || round(r.age_h, 1) || 'h 무갱신(임계 ' || round(r.thresh_h) || 'h)');
      keys  := keys  || (r.key || ':late');
    end if;

    if r.note ~ '(fail|failed)=[1-9]' or r.note ~ '실패\s+[1-9]' then
      fail_n := coalesce(substring(r.note from '(?:fail|failed)=([0-9]+)'),
                         substring(r.note from '실패\s+([0-9]+)'), '?');
      probs := probs || (r.label || ' 실패 ' || fail_n || '건 (note: ' || r.note || ')');
      keys  := keys  || (r.key || ':fail');
    end if;

    if r.note ~ 'outdated=[1-9]' then
      fail_n := substring(r.note from 'outdated=([0-9]+)');
      probs := probs || (r.label || ' — 지식베이스가 구버전인 법령 ' || fail_n ||
                         '건 (law_sync.py 로 현행화 필요)');
      keys  := keys  || (r.key || ':outdated');
    end if;
  end loop;

  if array_length(probs, 1) is null then
    insert into system_health(key, note, updated_at)
      values ('watchdog_alert_state', 'ok', now())
      on conflict (key) do update set note = 'ok', updated_at = now();
    return 'ok: 이상 없음 (' || now_kst || ' KST)';
  end if;

  select string_agg(x, ',' order by x) into cur_set from unnest(keys) as x;
  select note into prev_set from system_health where key = 'watchdog_alert_state';
  if prev_set is null or prev_set = 'ok' then
    prev_keys := '{}';
  elsif prev_set ~ '^[0-9a-f]{32}$' then
    prev_keys := keys;                      -- 종전 md5 서명 — 이전 집합을 모르므로 전부 '계속'으로(전환 직후 재알림 억제)
  else
    prev_keys := string_to_array(prev_set, ',');
  end if;
  new_keys := array(select x from unnest(keys) as x where not (x = any(prev_keys)));

  insert into system_health(key, note, updated_at)
    values ('watchdog_alert_state', cur_set, now())
    on conflict (key) do update set note = excluded.note, updated_at = now();

  if array_length(new_keys, 1) is null then
    return 'suppressed(새 이상 항목 없음) | ' || array_to_string(probs, ' | ');
  end if;

  for i in 1..array_length(probs, 1) loop
    lines := lines || ((case when keys[i] = any(new_keys) then '🆕 ' else '(계속) ' end) || probs[i]);
  end loop;
  msg := '⚠️ [워치독] 파이프라인 이상 감지 (' || now_kst || ' KST):' || chr(10) ||
         '- ' || array_to_string(lines, chr(10) || '- ');
  if not p_dry_run then
    select decrypted_secret into tok from vault.decrypted_secrets where name = 'telegram_bot_token';
    if tok is not null then
      perform net.http_post(
        url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
        body    := jsonb_build_object('chat_id', '<OPERATOR_CHAT_ID>', 'text', msg),
        headers := '{"Content-Type": "application/json"}'::jsonb
      );
    end if;
  end if;
  return (case when p_dry_run then '[dry-run] 발송생략 ' else 'sent ' end) || array_to_string(lines, ' | ');
end;
$function$
;
