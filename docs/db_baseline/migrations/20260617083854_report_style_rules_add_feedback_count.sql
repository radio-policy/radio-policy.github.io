-- 20260617083854 report_style_rules_add_feedback_count

alter table report_style_rules add column if not exists feedback_count int default 0;;
