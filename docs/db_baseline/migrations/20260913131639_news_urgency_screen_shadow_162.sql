-- 20260913131639 news_urgency_screen_shadow_162

-- #162 긴급도 그림자 기록 (2026-09-13)
-- 선별 콜(_screen_batch_haiku)은 관련성과 함께 등급도 내놓지만, save_new_items의 ⑤단계가
-- classify_urgency 결과로 전건을 덮어써 그 값이 버려진다(#84 이후 의도된 동작).
-- 이 컬럼은 버려지던 값을 **기록만** 한다 — 저장되는 urgency·importance와 알림 경로는 불변.
-- 2주 뒤 urgency_screen × urgency 혼동행렬로 "선별=참고면 개별 콜 생략" 가능 여부를 결정한다.
-- 빈 문자열 = 선별이 등급을 안 냈거나(모델 생략) 판정 경로를 안 탄 것(인사 자동통과·키워드 폴백).
alter table public.news_feed add column if not exists urgency_screen text;
comment on column public.news_feed.urgency_screen is
  '선별 콜이 매긴 등급(그림자 기록, #162). 저장 등급은 urgency — 이 값은 판정·알림에 쓰이지 않는다.';;
