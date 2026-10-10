-- 20261010144649 definer_search_path_dispatch_20261010

-- definer_search_path_dispatch_20261010 — 보안 구현 C-1 (판정 Q6 ③(a))
-- 두 함수 본문은 이미 vault.·net.·pg_catalog 이름만 쓴다 → 본문 그대로, search_path만 고정.
-- 적용 전 되돌리는 시험(새 정의로 1회 실행 → 큐 적재 확인 → 전체 롤백) 통과(10-10 23:4x).
-- 통과: 다음 */10 crawl-trigger-hourly의 net._http_response 204 + daily_crawl 성공. 실패 시 즉시
--   alter function public.dispatch_github_workflow(text) reset search_path;  alter function public.gh_api_get(text) reset search_path;
alter function public.dispatch_github_workflow(text) set search_path = '';
alter function public.gh_api_get(text) set search_path = '';;
