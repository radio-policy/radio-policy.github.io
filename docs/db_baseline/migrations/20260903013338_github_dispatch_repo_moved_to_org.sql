-- 20260903013338 github_dispatch_repo_moved_to_org

-- 2026-09-03: GitHub 저장소가 youjinwoong/radio-policy-ai → radio-policy/radio-policy.github.io (조직)로 이전.
-- Vault github_pat도 조직 소유 fine-grained 토큰으로 교체됨. 두 함수의 workflow_dispatch 경로만 새 저장소로 바꾼다.

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
END;$function$;

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
$function$;;
