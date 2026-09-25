-- role_settings — tools_db_baseline.py가 실DB에서 생성(손으로 고치지 말 것), 비밀 마스킹됨

alter role anon set statement_timeout = '3s';

alter role authenticated set statement_timeout = '15s';

alter role authenticator set lock_timeout = '8s';

alter role authenticator set statement_timeout = '8s';

alter role service_role set statement_timeout = '15s';
