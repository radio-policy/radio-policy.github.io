-- default_acl — tools_db_baseline.py가 실DB에서 생성(손으로 고치지 말 것), 비밀 마스킹됨

alter default privileges for role postgres in schema extensions revoke all on functions from public, anon, authenticated, service_role;
alter default privileges for role postgres in schema extensions grant EXECUTE on functions to public;

alter default privileges for role postgres in schema public revoke all on functions from public, anon, authenticated, service_role;
alter default privileges for role postgres in schema public grant EXECUTE on functions to service_role;

alter default privileges for role postgres in schema public revoke all on sequences from public, anon, authenticated, service_role;
alter default privileges for role postgres in schema public grant SELECT, UPDATE, USAGE on sequences to authenticated;
alter default privileges for role postgres in schema public grant SELECT, UPDATE, USAGE on sequences to service_role;

alter default privileges for role postgres in schema public revoke all on tables from public, anon, authenticated, service_role;
alter default privileges for role postgres in schema public grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on tables to authenticated;
alter default privileges for role postgres in schema public grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on tables to service_role;

alter default privileges for role postgres revoke all on functions from public, anon, authenticated, service_role;
