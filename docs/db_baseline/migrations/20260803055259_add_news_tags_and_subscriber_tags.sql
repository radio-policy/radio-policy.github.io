-- 20260803055259 add_news_tags_and_subscriber_tags

alter table public.news_feed            add column if not exists tags text[];
alter table public.telegram_subscribers add column if not exists tags text[] not null default '{}'::text[];
alter table public.subscriber_queue     add column if not exists news_url text;
alter table public.subscriber_queue     add column if not exists tags text[];

comment on column public.news_feed.tags is
  '분야 태그. spectrum|market|regulation|security|ai|legislation. NULL/빈배열 = 미판정.
   category와 별개 축 — category는 해외 규제동향 메뉴(app.js:7090)가 쓰므로 손대지 않는다. (#76)';
comment on column public.telegram_subscribers.tags is
  '관심 분야. 빈 배열 = 전체 수신(기본값·하위호환). 6개 전부 선택 시에도 빈 배열로 정규화. (#76)';
comment on column public.subscriber_queue.news_url is
  '기사 단위 행의 식별자 겸 판별자. NOT NULL = 기사 1건 행, NULL = 구버전 묶음 행 또는
   assembly 알림 → 태그 필터 미적용·원문 그대로 발송. (#76)';;
