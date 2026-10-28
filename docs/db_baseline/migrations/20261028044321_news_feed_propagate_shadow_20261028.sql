-- 20261028044321 news_feed_propagate_shadow_20261028

-- #327 긴급도 내림 전파 그림자(판정_재보정_261028 §4, 결과_재보정_261030 §4 — 측정 미통과라 그림자).
-- 등급·큐·알림 값은 바꾸지 않는다 — 판정 결과만 두 칸에 남긴다. 기존 표의 칸 추가라 권한은 표 단위 GRANT를 따른다
-- (anon SELECT · authenticated UPDATE 칸 목록에는 넣지 않음 · service_role 전부 — urgency_check_capped와 같은 수준, #214).
-- 외래 키 없음: 원인 기사가 지워져도 이 칸이 삭제를 막거나 함께 바뀌면 안 된다(기록 칸).
alter table public.news_feed
  add column if not exists urgency_propagate_shadow_from uuid,
  add column if not exists urgency_propagate_shadow_at timestamptz;

comment on column public.news_feed.urgency_propagate_shadow_from is
  '그림자 내림 전파(#327): 재보도 대조가 같은 계기로 본 운영자 내림 기사의 news_feed.id. 그림자라 등급(urgency)은 바뀌지 않았다 — 「보통으로 저장됨」이 아니다.';
comment on column public.news_feed.urgency_propagate_shadow_at is
  '그림자 내림 전파(#327) 판정 시각 — 같음·다름 모두 채운다(같음이면 _from도 있음). null = 판정 안 함(후보 아님·건너뜀·실패).';;
