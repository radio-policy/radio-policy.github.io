-- 20260925215419 news_known_items_rpc_234

-- #234 (2026-09-26, 개선안 §2-13 2단계): 뉴스 중복 대조를 후보만 DB에 묻는 1왕복으로.
-- 종전: 크롤러가 실행마다 news_feed·deleted_news·news_screen_cache 전량을 1,000행씩 47회 내려받아 대조.
-- 정확 일치만 본다 — '최근 N일' 창으로 좁히지 말 것(2026-08-03 재발송 사고). 결과는 jsonb 한 값(1,000행 상한 무관).
create or replace function public.news_known_items(p_urls text[], p_titles text[], p_include_deleted boolean default true)
returns jsonb
language sql
stable
set search_path = public, pg_temp
as $$
  select jsonb_build_object(
    'urls', coalesce((
      select jsonb_agg(u.url)
      from (select distinct x.url from unnest(coalesce(p_urls, '{}'::text[])) as x(url) where x.url <> '') u
      where u.url in (select n.url from public.news_feed n)
         or (p_include_deleted and u.url in (select d.url from public.deleted_news d))
    ), '[]'::jsonb),
    'titles', coalesce((
      select jsonb_agg(t.title)
      from (select distinct x.title from unnest(coalesce(p_titles, '{}'::text[])) as x(title) where x.title <> '') t
      where t.title in (select n.title from public.news_feed n)
         or (p_include_deleted and t.title in (select d.title from public.deleted_news d))
    ), '[]'::jsonb)
  );
$$;

comment on function public.news_known_items(text[], text[], boolean) is
  '#234 뉴스 중복 대조: 후보 url·제목 중 news_feed(+deleted_news) 에 이미 있는 것만 {urls,titles}로. 정확 일치, 기간 창 없음. service_role 전용.';

create or replace function public.news_screen_cache_lookup(p_urls text[], p_criteria_hash text)
returns jsonb
language sql
stable
set search_path = public, pg_temp
as $$
  select coalesce(jsonb_object_agg(c.url, c.title_hash), '{}'::jsonb)
  from public.news_screen_cache c
  where c.url = any(coalesce(p_urls, '{}'::text[]))
    and c.criteria_hash = p_criteria_hash;
$$;

comment on function public.news_screen_cache_lookup(text[], text) is
  '#234 선별 무관 캐시 대조: 후보 url 중 같은 기준문 지문으로 무관 판정된 것만 {url: title_hash}. service_role 전용.';

revoke all on function public.news_known_items(text[], text[], boolean) from public, anon, authenticated, service_role;
grant execute on function public.news_known_items(text[], text[], boolean) to service_role;
revoke all on function public.news_screen_cache_lookup(text[], text) from public, anon, authenticated, service_role;
grant execute on function public.news_screen_cache_lookup(text[], text) to service_role;;
