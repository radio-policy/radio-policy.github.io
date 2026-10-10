-- 20261010142645 anon_closed_20261010

-- anon_closed_20261010 — 시스템 평가 ④ 보안 구현 A (판정 local_docs/시스템평가_261010/보안_판정.md §3 Q1·Q2·Q3·Q6②·Q7, §4 A)
-- 한 트랜잭션: 정책 분리(A-4)와 함수 회수(A-3)가 같은 트랜잭션이어야 그 사이 비로그인 importance_feedback 읽기가 안 깨진다.

-- A-1 anon 표 권한: SELECT만 남김. 예외 lawmap_proposals INSERT(비로그인 관계도 요청, 정책 lawmap_proposals_ins_anon).
revoke insert, update, delete, truncate, references, trigger, maintain on all tables in schema public from anon;
grant insert on public.lawmap_proposals to anon;
revoke update (is_read) on public.news_feed from anon;   -- 표 단위 회수가 함께 걷지만 명시(쓰는 곳 0)
-- A-1b 정책이 하나도 없는 service_role 전용 9표의 anon SELECT(지금도 빈 목록, 읽는 곳 0 — app.js·사내 다리·Edge 확인).
--   판정 Q7 ㉡ 「anon GRANT는 있는데 정책이 하나도 없는 표」와 맞춘다(Fable 짧은 점검 Q-f (가), 10-10).
revoke select on public.changes, public.daily_briefings_backup, public.documents, public.kmcc_press_verdict,
  public.news_screen_cache, public.subscriber_queue, public.system_status, public.telegram_subscribers,
  public.telegram_updates from anon;

-- A-2 anon 시퀀스 권한 전부(lawmap_proposals.id는 uuid라 예외 없음)
revoke all on all sequences in schema public from anon;

-- A-4 imp_fb_sel 분리 — anon 분기에 권한 함수가 없게(함수 회수보다 먼저 적음, 같은 트랜잭션)
drop policy imp_fb_sel on public.importance_feedback;
create policy imp_fb_sel_anon on public.importance_feedback for select to anon
  using (team_id is null);
create policy imp_fb_sel_auth on public.importance_feedback for select to authenticated
  using (team_id is null or (select public.is_admin()) or team_id = (select public.my_team()));

-- A-3 SECURITY DEFINER 24개 anon·PUBLIC 실행권 회수(authenticated·service_role 유지)
--   A 관리자 RPC 11
revoke execute on function public.admin_delete_chat_log(uuid) from anon, public;
revoke execute on function public.admin_delete_chat_log_v2(uuid) from anon, public;
revoke execute on function public.admin_delete_custom_file(text) from anon, public;
revoke execute on function public.admin_delete_kb_document(text) from anon, public;
revoke execute on function public.admin_get_chat_log(uuid) from anon, public;
revoke execute on function public.admin_insert_kb_chunks(bigint, text[], text[]) from anon, public;
revoke execute on function public.admin_list_answer_feedback() from anon, public;
revoke execute on function public.admin_list_chat_logs(integer) from anon, public;
revoke execute on function public.admin_set_kb_approval(text, boolean) from anon, public;
revoke execute on function public.admin_update_chunk_embeddings(bigint[], text[]) from anon, public;
revoke execute on function public.admin_upsert_kb_document(text, text, text, text, text, text, text, text, text, text, text) from anon, public;
--   B 운영 조회 1
revoke execute on function public.ops_ai_usage_today() from anon, public;
--   C 자기 권한 조회 7
revoke execute on function public.is_admin() from anon, public;
revoke execute on function public.is_approved_user() from anon, public;
revoke execute on function public.is_issue_editor() from anon, public;
revoke execute on function public.is_leader() from anon, public;
revoke execute on function public.my_team() from anon, public;
revoke execute on function public.my_division() from anon, public;
revoke execute on function public.get_my_quota() from anon, public;
--   F·G 2
revoke execute on function public.chat_logs_month_count() from anon, public;
revoke execute on function public.submit_answer_feedback(uuid, smallint, text) from anon, public;
--   I 트리거 3 — 발화 때 EXECUTE 검사 없음(team_criteria_before가 증거), service_role만 남김
revoke execute on function public.handle_new_user() from anon, authenticated, public;
revoke execute on function public.notify_lawmap_request() from anon, authenticated, public;
revoke execute on function public.limit_anon_lawmap_request() from anon, authenticated, public;

-- A-5 기본 권한(postgres 소유 새 객체). 넷째·다섯째 줄은 구현 창 사실 정정(Fable 짧은 점검 Q-a·Q-b, 10-10):
--   함수의 PUBLIC EXECUTE는 Postgres 내장 기본값(acldefault)이라 스키마 단위로는 빠지지 않는다 → 전역 한 줄.
--   전역 행은 postgres가 만드는 모든 스키마에 걸리므로 extensions 스키마는 PUBLIC을 되돌려 오늘과 같게 둔다
--   (postgres 소유 확장 pgcrypto·uuid-ossp·pg_stat_statements를 설치·갱신할 때 함수가 42501로 깨지지 않게).
alter default privileges for role postgres in schema public revoke all on tables from anon;
alter default privileges for role postgres in schema public revoke all on sequences from anon;
alter default privileges for role postgres in schema public revoke execute on functions from anon, authenticated;
alter default privileges for role postgres revoke execute on functions from public;
alter default privileges for role postgres in schema extensions grant execute on functions to public;

--   자가 확인 — 임시 표·시퀀스·함수를 만들어 기본 권한을 본 뒤 지운다(같은 트랜잭션)
do $$
begin
  create table public._acl_probe_20261010 (id int);
  create sequence public._acl_probe_seq_20261010;
  create function public._acl_probe_fn_20261010() returns int language sql as 'select 1';
  if has_table_privilege('anon', 'public._acl_probe_20261010', 'SELECT')
     or has_table_privilege('anon', 'public._acl_probe_20261010', 'INSERT')
     or has_sequence_privilege('anon', 'public._acl_probe_seq_20261010', 'USAGE')
     or has_function_privilege('anon', 'public._acl_probe_fn_20261010()', 'EXECUTE')
     or has_function_privilege('authenticated', 'public._acl_probe_fn_20261010()', 'EXECUTE')
     or has_function_privilege('public', 'public._acl_probe_fn_20261010()', 'EXECUTE') then
    raise exception 'A-5 self-check: new object still open to anon/authenticated/public';
  end if;
  if not has_function_privilege('service_role', 'public._acl_probe_fn_20261010()', 'EXECUTE')
     or not has_table_privilege('service_role', 'public._acl_probe_20261010', 'SELECT')
     or not has_table_privilege('authenticated', 'public._acl_probe_20261010', 'SELECT') then
    raise exception 'A-5 self-check: service_role/authenticated table default lost';
  end if;
  drop function public._acl_probe_fn_20261010();
  drop sequence public._acl_probe_seq_20261010;
  drop table public._acl_probe_20261010;
  -- extensions 스키마 행은 PUBLIC EXECUTE를 가져야 한다(오늘과 같은 결과)
  if not exists (select 1 from pg_default_acl d cross join lateral aclexplode(d.defaclacl) x
                  where d.defaclrole = 'postgres'::regrole and d.defaclnamespace = 'extensions'::regnamespace
                    and d.defaclobjtype = 'f' and x.grantee = 0 and x.privilege_type = 'EXECUTE') then
    raise exception 'A-5 self-check: extensions schema lost PUBLIC EXECUTE default';
  end if;
end $$;

-- A-6 뷰 2 security_invoker(원본 document_chunks·kb_quality_ack 정책이 anon·authenticated true라 결과 같음)
alter view public.kb_quality_low_docs set (security_invoker = on);
alter view public.kb_quality_article_parse set (security_invoker = on);

-- A-7 service_role 전용 표 2(#214: 역할별 명시 GRANT, authenticated 표 기본값은 그대로라 명시 회수)
create table public.bridge_export_log (
  id bigint generated always as identity primary key,
  fn text not null,
  at timestamptz not null default now(),
  ua text,
  ip text
);
create index bridge_export_log_at_idx on public.bridge_export_log (at);
alter table public.bridge_export_log enable row level security;
revoke all on public.bridge_export_log from anon, authenticated, public;
grant select, insert, delete on public.bridge_export_log to service_role;
revoke all on sequence public.bridge_export_log_id_seq from anon, authenticated, public;
grant usage, select on sequence public.bridge_export_log_id_seq to service_role;
comment on table public.bridge_export_log is
  '비밀값 RPC 3개(people_export·team_rules_export·team_urgency_export) 성공 호출 기록 — 키 대조 통과 직후 INSERT. 90일 보존(security_audit()이 지움). service_role 전용(#29x)';

create table public.security_audit_log (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  hash text not null,
  lines jsonb,                       -- 지문이 바뀐 회차만 전체 줄(그 밖은 null — 표가 커지지 않게)
  violations jsonb not null default '[]'::jsonb,
  changed boolean not null
);
create index security_audit_log_at_idx on public.security_audit_log (at);
alter table public.security_audit_log enable row level security;
revoke all on public.security_audit_log from anon, authenticated, public;
grant select on public.security_audit_log to service_role;
revoke all on sequence public.security_audit_log_id_seq from anon, authenticated, public;
grant usage, select on sequence public.security_audit_log_id_seq to service_role;
comment on table public.security_audit_log is
  'security_audit() 권한 지문 기록(직전 값과 비교해 변화 1회 알림) — 90일 보존. service_role 읽기 전용, 쓰기는 함수(소유자)만(#29x)';

-- 구현 창 정정: 판정은 app_config(bridge_known_sources·secret_expiry)를 적었으나 app_config_sel이 anon에 열려
-- 사내 다리 출구 IP가 공개된다(판정 새 금지 조항 ③과 같은 이유) → service_role 전용 설정 표.
create table public.security_config (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now()
);
alter table public.security_config enable row level security;
revoke all on public.security_config from anon, authenticated, public;
grant select, insert, update on public.security_config to service_role;
comment on table public.security_config is
  'security_audit()이 읽는 설정(bridge_known_sources·secret_expiry) — service_role 전용, anon·authenticated 권한 없음(사내 다리 출처 비공개, #29x)';
;
