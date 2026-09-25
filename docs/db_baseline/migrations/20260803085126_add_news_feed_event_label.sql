-- 20260803085126 add_news_feed_event_label

alter table public.news_feed add column if not exists event text;
comment on column public.news_feed.event is 'Haiku 선별 시 함께 판정하는 사건 라벨(12~25자). 대시보드 뉴스 그룹핑에 사용. 판정 실패/미판정은 빈 문자열.';;
