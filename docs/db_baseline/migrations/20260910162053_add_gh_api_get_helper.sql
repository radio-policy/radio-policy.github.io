-- 20260910162053 add_gh_api_get_helper

-- #154 진단용: GitHub REST GET 을 Vault PAT 로 보내고 pg_net 요청 id 를 돌려준다. 응답은 net._http_response 에서 id 로 읽는다.
-- (Actions 잡 로그 API 는 302 라 못 읽고, check-runs annotations 로 요약을 읽는 #113 방식의 재사용 도구. PAT 는 함수 밖으로 나오지 않는다.)
create or replace function public.gh_api_get(p_path text)
returns bigint
language plpgsql
security definer
as $$
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
end;$$;
revoke all on function public.gh_api_get(text) from public, anon, authenticated;;
