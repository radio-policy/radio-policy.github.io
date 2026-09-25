-- extensions — tools_db_baseline.py가 실DB에서 생성(손으로 고치지 말 것), 비밀 마스킹됨

create extension if not exists "uuid-ossp" with schema extensions;

create extension if not exists pg_cron with schema pg_catalog;

create extension if not exists pg_net with schema public;

create extension if not exists pg_stat_statements with schema extensions;

create extension if not exists pg_trgm with schema extensions;

create extension if not exists pgcrypto with schema extensions;

create extension if not exists supabase_vault with schema vault;

create extension if not exists vector with schema public;
