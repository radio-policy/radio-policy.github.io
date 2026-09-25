-- 20260909103629 remove_report_draft_feature

-- #142 (2026-09-09) 보고서 초안 제안 기능 삭제 — 사내 보고서를 외부 서버에 두지 않는다(운영자 결정).
-- 삭제 시점 실측: report_samples 0행 / report_feedback 0행 / report_directives 0행 / report_style_rules 1행(증류 규칙 캐시).
drop function if exists public.match_report_samples(vector, double precision, integer, text);
drop function if exists public.match_report_samples(vector, float, int, text);
drop function if exists public.match_report_samples;
drop table if exists public.report_feedback;
drop table if exists public.report_directives;
drop table if exists public.report_style_rules;
drop table if exists public.report_samples;;
