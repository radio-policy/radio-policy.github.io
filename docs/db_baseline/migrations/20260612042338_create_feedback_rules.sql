-- 20260612042338 create_feedback_rules

-- 긴급도 피드백 증류 규칙 캐시 (단일 행, crawler.py가 피드백 10건 추가 시마다 재생성)
CREATE TABLE IF NOT EXISTS feedback_rules (
  id int PRIMARY KEY,
  rules text,
  feedback_count int NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now()
);;
