-- triggers — tools_db_baseline.py가 실DB에서 생성(손으로 고치지 말 것), 비밀 마스킹됨

CREATE TRIGGER on_auth_user_created AFTER INSERT ON auth.users FOR EACH ROW EXECUTE FUNCTION handle_new_user();

CREATE TRIGGER trg_limit_anon_lawmap_request BEFORE INSERT ON lawmap_proposals FOR EACH ROW EXECUTE FUNCTION limit_anon_lawmap_request();

CREATE TRIGGER trg_notify_lawmap_request AFTER INSERT ON lawmap_proposals FOR EACH ROW EXECUTE FUNCTION notify_lawmap_request();

CREATE TRIGGER news_feed_edit_guard_trg BEFORE UPDATE ON news_feed FOR EACH ROW EXECUTE FUNCTION news_feed_edit_guard();

CREATE TRIGGER team_criteria_before BEFORE INSERT OR UPDATE ON team_criteria FOR EACH ROW EXECUTE FUNCTION team_criteria_before();

CREATE TRIGGER team_grading_answers_touch BEFORE INSERT OR UPDATE ON team_grading_answers FOR EACH ROW EXECUTE FUNCTION team_grading_answers_touch();

CREATE TRIGGER team_grading_sets_guard BEFORE INSERT OR UPDATE ON team_grading_sets FOR EACH ROW EXECUTE FUNCTION team_grading_sets_guard();

CREATE TRIGGER team_grading_trial_items_touch BEFORE INSERT OR UPDATE ON team_grading_trial_items FOR EACH ROW EXECUTE FUNCTION team_grading_trial_items_touch();

CREATE TRIGGER team_grading_trials_guard BEFORE INSERT OR UPDATE ON team_grading_trials FOR EACH ROW EXECUTE FUNCTION team_grading_trials_guard();

CREATE TRIGGER team_urgency_touch BEFORE INSERT OR UPDATE ON team_urgency FOR EACH ROW EXECUTE FUNCTION team_urgency_touch();

CREATE TRIGGER teams_grader_check BEFORE UPDATE OF grader_user_id ON teams FOR EACH ROW EXECUTE FUNCTION teams_grader_check();

CREATE TRIGGER tech_terms_updated_at BEFORE UPDATE ON tech_terms FOR EACH ROW EXECUTE FUNCTION update_tech_terms_updated_at();

CREATE TRIGGER urgency_rule_verdicts_requester BEFORE INSERT ON urgency_rule_verdicts FOR EACH ROW EXECUTE FUNCTION urgency_rule_verdicts_requester();

CREATE TRIGGER urgency_rules_sentence_rev BEFORE INSERT OR UPDATE ON urgency_rules FOR EACH ROW EXECUTE FUNCTION urgency_rules_sentence_rev();

CREATE TRIGGER urgency_rules_touch BEFORE INSERT OR UPDATE ON urgency_rules FOR EACH ROW EXECUTE FUNCTION urgency_rules_touch();
