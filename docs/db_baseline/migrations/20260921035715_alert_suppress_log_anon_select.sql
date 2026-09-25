-- 20260921035715 alert_suppress_log_anon_select

-- 사내판 다리(export_news.py, anon 키)가 '알림 대표 여부'를 읽을 수 있도록 SELECT 정책 추가.
-- 내용은 공개 기사 제목·URL·겹친 키워드뿐이고, 쓰기는 서비스 키(크롤러)만 한다.
create policy alert_suppress_log_sel on public.alert_suppress_log
  for select to anon, authenticated using (true);;
