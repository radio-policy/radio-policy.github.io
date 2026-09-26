-- 20260926191132 speech_field_stats_248

-- #248 (2026-09-27) 과방위 회의록 발언 블록 분야 집계 — 발언자×회의별 건수·글자 수만(본문 저장 안 함), 낱말 규칙(AI 0회)
create table if not exists public.speech_field_stats (
  id bigint generated always as identity primary key,
  confer_num text not null,
  meeting_date date,
  meeting_title text,
  meeting_kind text,
  meeting_default text,
  speaker text not null,
  "position" text not null default '',
  n_blocks integer not null default 0,
  n_chars integer not null default 0,
  fields jsonb not null default '{}'::jsonb,
  field_chars jsonb not null default '{}'::jsonb,
  n_noise integer not null default 0,
  n_chair integer not null default 0,
  n_proc integer not null default 0,
  n_unclassified integer not null default 0,
  n_direct numeric not null default 0,
  n_inherit numeric not null default 0,
  n_default numeric not null default 0,
  src text,
  rules_version text not null,
  created_at timestamptz not null default now(),
  constraint speech_field_stats_uniq unique (confer_num, speaker, "position")
);
create index if not exists speech_field_stats_speaker_idx on public.speech_field_stats (speaker, meeting_date);
create index if not exists speech_field_stats_date_idx on public.speech_field_stats (meeting_date);
alter table public.speech_field_stats enable row level security;
create policy speech_field_stats_sel on public.speech_field_stats as permissive for select to anon, authenticated using (true);
revoke all on public.speech_field_stats from public, anon, authenticated, service_role;
grant select on public.speech_field_stats to anon, authenticated;
grant select, insert, update, delete on public.speech_field_stats to service_role;
revoke all on sequence public.speech_field_stats_id_seq from public, anon, authenticated, service_role;
grant usage, select on sequence public.speech_field_stats_id_seq to service_role;
comment on table public.speech_field_stats is '#248 과방위 회의록 발언 블록 분야 집계(발언자×회의). speech_fields.py 낱말 규칙, 본문은 저장소 밖 로컬 보관. 공개 여부는 app_config.speech_fields_public';
insert into public.app_config(key, value)
values ('speech_fields_public', '{"public": false, "rules_version": "v1-260927", "checked_at": null, "note": "공개 전 층화 검증 통과 시 true (#248)"}')
on conflict (key) do nothing;;
