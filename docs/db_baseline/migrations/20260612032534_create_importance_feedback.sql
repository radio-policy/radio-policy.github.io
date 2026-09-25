-- 20260612032534 create_importance_feedback

-- 긴급도 사용자 피드백 — 크롤러 분류 few-shot 학습용 (영구 보존)
CREATE TABLE IF NOT EXISTS importance_feedback (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  news_id uuid UNIQUE,
  title text,
  summary text,
  ai_importance text,
  user_importance text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);;
