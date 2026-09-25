-- triggers — tools_db_baseline.py가 실DB에서 생성(손으로 고치지 말 것), 비밀 마스킹됨

CREATE TRIGGER on_auth_user_created AFTER INSERT ON auth.users FOR EACH ROW EXECUTE FUNCTION handle_new_user();

CREATE TRIGGER trg_limit_anon_lawmap_request BEFORE INSERT ON lawmap_proposals FOR EACH ROW EXECUTE FUNCTION limit_anon_lawmap_request();

CREATE TRIGGER trg_notify_lawmap_request AFTER INSERT ON lawmap_proposals FOR EACH ROW EXECUTE FUNCTION notify_lawmap_request();

CREATE TRIGGER news_feed_edit_guard_trg BEFORE UPDATE ON news_feed FOR EACH ROW EXECUTE FUNCTION news_feed_edit_guard();

CREATE TRIGGER tech_terms_updated_at BEFORE UPDATE ON tech_terms FOR EACH ROW EXECUTE FUNCTION update_tech_terms_updated_at();

CREATE TRIGGER urgency_rules_touch BEFORE INSERT OR UPDATE ON urgency_rules FOR EACH ROW EXECUTE FUNCTION urgency_rules_touch();
