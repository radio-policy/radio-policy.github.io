-- 20260923163927 news_feed_update_columns_limit

-- #191: 로그인 계정의 news_feed UPDATE를 화면이 실제로 쓰는 칸으로 한정(제목·url·출처·날짜 등 수정 불가).
REVOKE UPDATE ON public.news_feed FROM authenticated;
GRANT UPDATE (is_read, content, summary, impact_analysis, impact_analyzed_at, locked, importance, urgency)
  ON public.news_feed TO authenticated;
-- anon은 UPDATE 정책이 없어 이미 막혀 있다. 남은 칸 권한도 정리(읽음 표시만 유지).
REVOKE UPDATE (content, summary) ON public.news_feed FROM anon;;
