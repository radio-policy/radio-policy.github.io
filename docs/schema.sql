-- ============================================================================
--  전파정책 AI — 데이터베이스 설치 스크립트 (schema.sql)  [배포용 / 강의용]
-- ----------------------------------------------------------------------------
--  사용법 (각 수강생이 자기 Supabase 프로젝트에서 1회 실행)
--    1) Supabase 대시보드 → 왼쪽 메뉴 'SQL Editor' → 'New query'
--    2) 이 파일 내용 전체를 복사해서 편집창에 붙여넣기
--    3) 오른쪽 아래 'Run' 클릭 → 초록색 'Success' 확인
--    4) 'Table Editor'에서 표(news_feed, law_amendments, document_chunks ...)가
--       생겼는지 확인하면 완료
--
--  주의
--    * 이 스크립트는 '표 구조'만 만듭니다. 데이터는 들어있지 않습니다(정상).
--    * 임베딩(AI 검색)은 1024차원(Voyage voyage-4-lite) 기준입니다.
--    * Edge Function(voyage-embed), Storage 키, API 키는 별도 단계에서 설정합니다.
--    * 키 값(claude_key 등)은 이 파일에 적지 말고, 각자 콘솔에서 입력하세요.
-- ============================================================================


-- ===========================================================================
-- 0. 확장(EXTENSION) — AI 검색(vector) + 한글 유사검색(pg_trgm)
-- ===========================================================================
create extension if not exists vector  with schema extensions;   -- pgvector (임베딩)
create extension if not exists pg_trgm with schema extensions;   -- 부분문자열 유사검색


-- ===========================================================================
-- 1. 테이블 (TABLES)
-- ===========================================================================

-- 1-1) 뉴스 피드 -------------------------------------------------------------
create table if not exists public.news_feed (
  id                 uuid primary key default gen_random_uuid(),
  title              text not null,
  source             text,
  category           text,
  url                text,
  is_read            boolean default false,
  published_at       timestamptz,
  created_at         timestamptz default now(),
  content            text,
  content_fetched_at timestamptz,
  briefed_date       date,
  summary            text,
  importance         text default '참고',
  urgency            text default '참고',
  locked             boolean not null default false
);
comment on table public.news_feed is '뉴스 본문·요약·긴급도(15일 유지). 내부값 긴급/보통/참고';

-- 1-2) 삭제 기사 블록리스트(재수집 방지) -------------------------------------
create table if not exists public.deleted_news (
  id         bigint generated always as identity primary key,
  url        text,
  title      text,
  deleted_at timestamptz not null default now()
);

-- 1-3) 긴급도 수동 수정 학습 데이터 ------------------------------------------
create table if not exists public.importance_feedback (
  id              bigint generated always as identity primary key,
  news_id         uuid unique,
  title           text,
  summary         text,
  ai_importance   text,
  user_importance text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- 1-4) 피드백 증류 규칙 캐시(단일 행 id=1) -----------------------------------
create table if not exists public.feedback_rules (
  id             integer primary key,
  rules          text,
  feedback_count integer not null default 0,
  updated_at     timestamptz not null default now()
);

-- 1-5) 일일 브리핑 원문 ------------------------------------------------------
create table if not exists public.daily_briefings (
  id           uuid primary key default gen_random_uuid(),
  briefing_date date unique not null,
  content      text not null,
  news_count   integer default 0,
  terms_count  integer default 0,
  created_at   timestamptz default now()
);

-- 1-6) 법령·고시·입법예고 ----------------------------------------------------
create table if not exists public.law_amendments (
  id               uuid primary key default gen_random_uuid(),
  law_id           text unique not null,
  law_nm           text not null,
  law_type         text not null,             -- law/bylaw/rules/admrul/lsAnc
  ann_type         text,
  public_dt        text,
  enf_dt           text,
  public_no        text,
  matched_keywords text[],
  link_url         text,
  prev_public_dt   text,
  created_at       timestamptz default now(),
  updated_at       timestamptz default now(),
  summary          text
);

-- 1-7) 국회 법안 -------------------------------------------------------------
create table if not exists public.assembly_bills (
  id               uuid primary key default gen_random_uuid(),
  bill_id          text unique not null,
  bill_no          text,
  bill_name        text not null,
  proposer         text,
  committee        text,
  proc_result      text default '접수',
  propose_dt       text,
  proc_dt          text,
  age              integer default 22,
  matched_keywords text[],
  link_url         text,
  prev_proc_result text,
  created_at       timestamptz default now(),
  updated_at       timestamptz default now(),
  summary          text,
  -- 국회 입법예고 추적 (2026-08-02, 배경역사 #56)
  notice_end_dt    text,                     -- 의견등록 마감일 'YYYY-MM-DD' (진행중 API NOTI_ED_DT)
  notice_url       text,                     -- pal.assembly.go.kr 상세 링크
  notice_alert_stage smallint default 0      -- 0=미알림 1=시작알림됨 2=D-3알림됨 (발송 성공 시에만 갱신)
);
comment on table public.assembly_bills is '국회 의안 모니터링 — 전파/통신 관련 법안 추적';

-- 1-8) RAG 청크(법령·고시·보도자료) — 임베딩 1024 ---------------------------
create table if not exists public.document_chunks (
  id             bigint generated by default as identity primary key,
  doc_name       text not null,
  doc_category   text,
  chunk_index    integer,
  content        text not null,
  created_at     timestamptz default now(),
  notice_no      text,
  article_no     text,
  effective_date text,
  embedding      extensions.vector(1024),
  file_path      text,
  is_approved    boolean not null default true,
  -- 법령 버전 추적 (migration law_version_tracking, 2026-07-29)
  law_id         text,                                -- 법제처 법령ID/행정규칙ID (API 적재본만)
  law_mst        text,                                -- 법령일련번호/행정규칙일련번호
  status         text not null default 'current'      -- current | pending(시행예정) | superseded(구버전)
);
create index if not exists idx_document_chunks_status on public.document_chunks(status);
create index if not exists idx_document_chunks_law    on public.document_chunks(law_id, status);
-- 백필 조회(embedding IS NULL) 가속 — 부분 인덱스 없이는 Seq Scan 5초+ (2026-07-30 실측)
create index if not exists document_chunks_embedding_null_idx
  on public.document_chunks (id) where embedding is null;

-- 1-9) 보고서 샘플(형식·톤 학습용, 청킹 안 함) ------------------------------
create table if not exists public.report_samples (
  id          bigint generated always as identity primary key,
  title       text not null,
  report_type text,                           -- 정책검토/규제영향/동향보고/기타
  content     text not null,
  summary     text,
  embedding   extensions.vector(1024),
  created_at  timestamptz default now()
);

-- 1-10) 보고서 스타일 가이드 캐시(단일 행 id=1) ------------------------------
create table if not exists public.report_style_rules (
  id             integer primary key default 1,
  rules          text,
  sample_count   integer default 0,
  updated_at     timestamptz default now(),
  feedback_count integer default 0
);

-- 1-11) 보고서 '항상 적용' 영구 지시 ----------------------------------------
create table if not exists public.report_directives (
  id         bigint generated always as identity primary key,
  directive  text not null,
  created_at timestamptz default now()
);

-- 1-12) 보고서 피드백(편집-diff 학습 데이터) --------------------------------
create table if not exists public.report_feedback (
  id         bigint generated always as identity primary key,
  request    text,
  draft      text,
  final      text,
  rating     smallint,
  created_at timestamptz default now()
);

-- 1-13) 팀 추가 지식(수동 입력) ---------------------------------------------
create table if not exists public.custom_knowledge (
  id         bigint generated by default as identity primary key,
  title      text not null,
  content    text not null,
  category   text default '일반',
  tags       text[] default '{}',
  created_at timestamptz default now(),
  is_active  boolean default true
);

-- 1-14) 기술 용어 사전 -------------------------------------------------------
create table if not exists public.tech_terms (
  id            uuid primary key default gen_random_uuid(),
  term          text unique not null,
  term_en       text,
  category      text default '기타',
  definition    text,
  description   text,
  diagram_html  text,
  source        text,
  source_url    text,
  related_terms text[],
  is_reviewed   boolean default false,
  created_at    timestamp default now(),
  updated_at    timestamp default now()
);

-- 1-15) 지식베이스 문서 메타(법령/고시/ITU-R 등) ----------------------------
create table if not exists public.documents (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  type       text check (type = any (array[
               '법령','고시','ITU-R','전파법','전파법_시행령','전파법_시행규칙',
               '전기통신사업법','전기통신사업법_시행령','방송통신발전기본법',
               '방송통신발전기본법_시행령','기술기준','적합성평가','주파수할당',
               '주파수분배표','전자파','정보통신망법','정보통신기반시설','방송통신설비'])),
  version    text,
  file_url   text,
  file_path  text,
  status     text default '최신' check (status = any (array['최신','업로드필요','개정예고'])),
  updated_at timestamptz default now()
);

-- 1-16) 변경 이력 -----------------------------------------------------------
create table if not exists public.changes (
  id          uuid primary key default gen_random_uuid(),
  doc_name    text not null,
  change_type text check (change_type = any (array['개정','폐지','제정','예고'])),
  description text,
  source_url  text,
  detected_at timestamptz default now()
);

-- 1-17) 시스템 상태(키-값) ---------------------------------------------------
create table if not exists public.system_status (
  key        text primary key,
  value      text,
  updated_at timestamptz default now()
);

-- 1-18) 앱 설정(키-값) — claude_key 등은 콘솔에서 직접 입력 -----------------
create table if not exists public.app_config (
  key   text primary key,
  value text not null
);

-- 1-19) AI 자문 이력 ---------------------------------------------------------
-- 2026-08-20(#103)부터 **네 경로 공통 정본 답변 로그**다: 대시보드 자문 + 텔레그램 /ask +
-- /law 자연어 + /law 조문 직조회. channel은 만족도 집계 축, chunk_ids는 그때 실제로
-- 프롬프트에 들어간 근거(document_chunks.id) — 불만족 건 사후 분석의 재료.
create table if not exists public.chat_logs (
  id         uuid primary key default gen_random_uuid(),
  question   text not null,
  answer     text not null,
  category   text,
  sources    text,
  channel    text,      -- telegram_ask | telegram_law | dashboard
  chat_id    bigint,    -- 텔레그램 이용자 (대시보드는 null)
  chunk_ids  jsonb,     -- 근거 청크 id 배열
  created_at timestamptz default now()
);

-- 1-20) 답변 만족도 (#103) ---------------------------------------------------
-- 세 경로 공통. log_id 유니크 + upsert라 재투표는 행이 늘지 않고 마지막 값으로 갱신된다.
-- channel을 비정규화해 함께 두는 이유: 자문 이력이 삭제돼도(FK는 set null) 경로별 통계는 남아야 한다.
-- **RLS 켜고 anon 정책을 주지 않는다** — 대시보드는 공개 페이지라 남의 평점·사유가 노출되면 안 된다.
-- 쓰기는 submit_answer_feedback RPC, 읽기는 admin_list_answer_feedback(비밀번호) 전용.
create table if not exists public.answer_feedback (
  id         bigint generated always as identity primary key,
  log_id     uuid unique references public.chat_logs(id) on delete set null,
  channel    text not null check (channel in ('telegram_ask','telegram_law','dashboard')),
  rating     smallint not null check (rating in (1,-1)),
  reason     text,      -- 대시보드 👎 사유 한 줄 (텔레그램은 버튼만이라 null)
  chat_id    bigint,    -- 텔레그램 투표자
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_answer_feedback_channel on public.answer_feedback (channel, rating);
alter table public.answer_feedback enable row level security;


-- ===========================================================================
-- 2. 인덱스 (INDEXES) — 검색 속도 + AI 시맨틱 검색(HNSW)
-- ===========================================================================
create unique index if not exists idx_news_feed_url_unique on public.news_feed using btree (url); -- 중복 방지(고유) — 실DB와 동일(UNIQUE). 크롤러는 upsert(on_conflict='url')와 한 쌍
create index if not exists idx_news_feed_locked          on public.news_feed using btree (locked) where (locked = true);

create index if not exists assembly_bills_proc_result_idx on public.assembly_bills using btree (proc_result);
create index if not exists assembly_bills_propose_dt_idx  on public.assembly_bills using btree (propose_dt desc);

create index if not exists law_amendments_law_type_idx    on public.law_amendments using btree (law_type);
create index if not exists law_amendments_public_dt_idx   on public.law_amendments using btree (public_dt);

create index if not exists document_chunks_category_idx   on public.document_chunks using btree (doc_category);
create index if not exists document_chunks_doc_name_idx   on public.document_chunks using btree (doc_name);
create index if not exists document_chunks_content_idx    on public.document_chunks using gin (to_tsvector('simple', content));
create index if not exists document_chunks_content_trgm_idx on public.document_chunks using gin (content extensions.gin_trgm_ops);
create index if not exists document_chunks_embedding_hnsw_idx
  on public.document_chunks using hnsw (embedding extensions.vector_cosine_ops) with (m = '16', ef_construction = '64');

create index if not exists report_samples_embedding_idx
  on public.report_samples using hnsw (embedding extensions.vector_cosine_ops);

create index if not exists tech_terms_category_idx on public.tech_terms using btree (category);
create index if not exists tech_terms_term_idx     on public.tech_terms using btree (term);
create index if not exists tech_terms_content_idx  on public.tech_terms using gin
  (to_tsvector('simple', (((term || ' ') || coalesce(definition,'')) || ' ') || coalesce(description,'')));


-- ===========================================================================
-- 3. 검색 함수 (RPC) — 대시보드 AI 자문 / 보고서 초안이 호출
-- ===========================================================================

-- 3-1) 시맨틱(벡터) 검색 -----------------------------------------------------
-- only_current 기본 true — 구버전(superseded)·시행예정본(pending) 제외.
-- ⚠ 인자 추가 시 구 시그니처를 반드시 DROP할 것. 인자 수가 다르면 CREATE OR REPLACE는
--    새 오버로드를 만들고, 호출부가 옛 인자 수로 부르면 필터 없는 쪽이 조용히 쓰인다(배경역사 #31 후속2).
create or replace function public.match_chunks_semantic(
  query_embedding extensions.vector,
  match_threshold double precision default 0.5,
  match_count integer default 8,
  only_current boolean default true)
returns table(id bigint, doc_name text, doc_category text, chunk_index integer,
  content text, notice_no text, article_no text, effective_date text, similarity double precision)
language sql stable security definer
as $$
  select id, doc_name, doc_category, chunk_index, content,
         notice_no, article_no, effective_date,
         (1 - (embedding <=> query_embedding))::float as similarity
  from public.document_chunks
  where embedding is not null and is_approved
    and (not only_current or status = 'current')
    and (1 - (embedding <=> query_embedding)) > match_threshold
  order by embedding <=> query_embedding
  limit match_count;
$$;

-- 3-2) 부분문자열(trgm) 검색 -------------------------------------------------
create or replace function public.search_chunks_trgm(
  query_text text,
  match_threshold double precision default 0.12,
  match_count integer default 8,
  only_current boolean default true)
returns table(id bigint, doc_name text, doc_category text, chunk_index integer,
  content text, notice_no text, article_no text, effective_date text, trgm_score double precision)
language sql stable security definer
as $$
  select id, doc_name, doc_category, chunk_index, content,
         notice_no, article_no, effective_date,
         extensions.word_similarity(query_text, content)::float as trgm_score
  from public.document_chunks
  where is_approved
    and (not only_current or status = 'current')
    and extensions.word_similarity(query_text, content) > match_threshold
  order by trgm_score desc
  limit match_count;
$$;

-- 3-2b) 승인 직후 임베딩 저장 (관리자 비밀번호 검증) ---------------------------
-- anon은 document_chunks UPDATE가 RLS로 막혀 있고 batch_update_embeddings는
-- service_role 전용이므로, admin_set_kb_approval과 동일한 SHA-256 검증 통로를 둠.
-- 대시보드 승인 버튼 → voyage-embed(문서 모드) → 이 RPC로 저장. (배경역사 #23)
create or replace function public.admin_update_chunk_embeddings(
  p_ids bigint[], p_embeddings text[], p_pwd text)
returns integer
language plpgsql security definer
set search_path to 'public', 'extensions'
as $$
declare n integer := 0; i integer;
begin
  if encode(digest(p_pwd, 'sha256'), 'hex') is distinct from '<관리자 비밀번호 SHA-256 — 실DB에만>' then
    raise exception 'AUTH_FAILED';
  end if;
  if array_length(p_ids, 1) is distinct from array_length(p_embeddings, 1) then
    raise exception 'LENGTH_MISMATCH';
  end if;
  for i in 1..coalesce(array_length(p_ids, 1), 0) loop
    update document_chunks set embedding = p_embeddings[i]::vector where id = p_ids[i];
    n := n + 1;
  end loop;
  return n;
end;
$$;

-- 3-3) 보고서 샘플 시맨틱 검색 -----------------------------------------------
create or replace function public.match_report_samples(
  query_embedding extensions.vector,
  match_count integer default 2,
  filter_type text default null)
returns table(id bigint, title text, report_type text, content text, similarity double precision)
language sql stable
as $$
  select rs.id, rs.title, rs.report_type, rs.content,
         1 - (rs.embedding <=> query_embedding) as similarity
  from public.report_samples rs
  where rs.embedding is not null
    and (filter_type is null or rs.report_type = filter_type)
  order by rs.embedding <=> query_embedding
  limit match_count;
$$;

-- 3-4) 지식베이스 문서 목록 --------------------------------------------------
-- status 포함 — UI가 현행본만 기본 표시하고 구버전·시행예정을 토글로 감춘다(2026-07-30)
create or replace function public.list_kb_documents()
returns table(doc_category text, doc_name text, chunks bigint, embedded bigint,
  approved boolean, status text)
language sql stable
as $$
  select min(doc_category) as doc_category, doc_name, count(*) as chunks,
         count(*) filter (where embedding is not null) as embedded,
         bool_and(is_approved) as approved,
         min(status) as status
  from public.document_chunks
  where doc_category is distinct from '보도자료'
  group by doc_name
  order by doc_name;
$$;

-- ===========================================================================
-- 3b. 법령 자동 현행화 (law_watch.py / law_sync.py, 2026-07-29~30)
-- ===========================================================================

-- 감시 레지스트리 — 등재본 vs 법제처 현행본 대조 결과 (매일 11시 GitHub Actions)
create table if not exists public.law_watch (
  id                bigserial primary key,
  doc_name          text unique not null,     -- 등재 문서명(document_chunks.doc_name)
  law_name          text,
  law_type_token    text,                     -- 법률/대통령령/부령/고시 …
  api_target        text,                     -- law | admrul
  law_id            text,
  registered_mst    text, registered_law_no text, registered_enf text,
  latest_mst        text, latest_law_no     text, latest_enf     text,
  pending_mst       text, pending_law_no    text, pending_enf    text,  -- 요약(가장 이른 1건) — 전체는 law_pending
  watch_status      text,                     -- watching | unmatched | excluded
  sync_status       text,                     -- current | outdated | unknown
  approved_at       timestamptz, approved_mst text,
  last_checked_at   timestamptz,
  note              text,
  created_at        timestamptz default now(),
  updated_at        timestamptz default now()
);

-- 시행예정본 추적(1:N — 정보통신망법처럼 시행일이 3개 걸리는 다단 시행 수용)
create table if not exists public.law_pending (
  id              bigserial primary key,
  law_name        text not null,
  law_id          text,
  law_type_token  text,
  api_target      text not null default 'law',
  watch_doc_name  text,                       -- 감시 기준이 된 현행 등재본
  mst             text not null,              -- (MST, 시행일)이 통합본 식별자 — 같은 MST가 시행일별 통합본을 가짐
  law_no          text,
  enf_date        text not null,              -- YYYYMMDD
  doc_name        text,                       -- 적재된 경우 document_chunks.doc_name(status='pending')
  sync_state      text not null default 'detected',  -- detected | loaded | promoted | obsolete
  note            text,
  detected_at     timestamptz not null default now(),
  loaded_at       timestamptz, promoted_at timestamptz,
  updated_at      timestamptz not null default now(),
  constraint law_pending_uniq unique (law_name, mst, enf_date)
);
create index if not exists law_pending_state_idx on public.law_pending (sync_state, enf_date);
create index if not exists law_pending_law_idx   on public.law_pending (law_name, enf_date);

-- 3b-1) 조번호 정규화 — article_no의 제목을 떼고 번호만("48조의3(침해사고…)" → "48조의3")
create or replace function public.norm_article_key(a text)
returns text language sql immutable as $$
  select (regexp_match(regexp_replace(coalesce(a, ''), '^제', ''),
                       '^([0-9]+조(?:의[0-9]+)?)'))[1];
$$;

-- 3b-2) Phase 3 — 인용된 현행 조문에 대응하는 시행예정 조문 (자문·보고서 초안이 호출)
-- (doc, key) 쌍으로 매칭 — 배열 2개를 따로 받으면 교차곱 오매칭이 난다
create or replace function public.fetch_pending_articles(
  p_pairs jsonb,                              -- [{"doc":"<현행 doc_name>","key":"48조의3"}, ...]
  p_limit integer default 16)
returns table(law_name text, enf_date text, law_no text, pending_doc text,
  current_doc text, article_no text, content text)
language sql stable as $$
  with want as (
    select distinct e->>'doc' as doc, e->>'key' as akey
    from jsonb_array_elements(p_pairs) e
    where coalesce(e->>'doc','') <> '' and coalesce(e->>'key','') <> ''
  ), art as (
    select p.law_name, p.enf_date, p.law_no, p.doc_name as pending_doc,
           p.watch_doc_name as current_doc, c.article_no, w.akey,
           string_agg(c.content, E'\n' order by c.chunk_index) as content
    from want w
    join law_pending p on p.watch_doc_name = w.doc and p.sync_state in ('detected','loaded')
    join document_chunks c on c.doc_name = p.doc_name and c.status = 'pending'
     and public.norm_article_key(c.article_no) = w.akey
    group by 1,2,3,4,5,6,7
  ), dedup as (
    select art.*, lag(regexp_replace(content, '\s+', '', 'g'))
      over (partition by current_doc, akey order by enf_date, article_no) as prev_norm
    from art
  )
  select law_name, enf_date, law_no, pending_doc, current_doc, article_no, content
  from dedup
  where content !~ '^제[0-9]+조(의[0-9]+)?\s*삭제'
    and (prev_norm is null or prev_norm <> regexp_replace(content, '\s+', '', 'g'))
  order by enf_date, article_no
  limit p_limit;
$$;

-- 3b-3) 인용 문서에 걸린 시행예정 일정(조문 매칭 없이도 시행 일정은 알림)
create or replace function public.pending_versions_for_docs(p_docs text[])
returns table(law_name text, current_doc text, law_no text, enf_date text, loaded boolean)
language sql stable as $$
  select p.law_name, p.watch_doc_name, p.law_no, p.enf_date, (p.sync_state = 'loaded')
  from law_pending p
  where p.sync_state in ('detected','loaded') and p.watch_doc_name = any(p_docs)
  order by p.law_name, p.enf_date;
$$;

-- 3b-4) 법령 개정 DIFF — law_diff_gen.py가 조문 단위 비교 + AI 분석 결과를 저장 (2026-08-02)
--       diff_kind='pending'은 시행예정본 vs 현행 등재본 비교, 'promoted'는 시행일 도래로
--       승격된 판 — 같은 (law_name,new_doc)의 pending 분석 행을 AI 재호출 없이 전환한다.
create table if not exists public.law_diffs (
  id           bigserial primary key,
  law_name     text not null,
  law_id       text,
  mst          text,
  law_no       text,
  enf_date     text,                        -- YYYYMMDD
  diff_kind    text not null default 'pending',  -- proposed(입법예고 단계) | pending | promoted
  origin       text default 'gov',           -- 'gov'=행정부 입법예고/법제처 | 'assembly'=국회 입법예고(new_doc=의안번호, enf_date=의견마감일)
  base_doc     text,                        -- 비교 기준(현행 등재본) doc_name
  new_doc      text not null,               -- 비교 대상(시행예정/승격본) doc_name
  summary      text,                        -- AI 요약 (전부개정 시 "수동 비교 권장" 프리셋)
  impact       text,                        -- 통신사 정책 관점 영향 분석
  urgency      text,                        -- high | medium | low
  articles     jsonb,                       -- [{article_no, change('modified'|'added'|'deleted'), before, after, impact}]
  stats        jsonb,                       -- {modified, added, deleted}
  model        text,                        -- 분석에 쓴 모델명
  analyzed_at  timestamptz,
  created_at   timestamptz default now(),
  updated_at   timestamptz default now(),
  unique (law_name, new_doc, diff_kind)
);


-- ===========================================================================
-- 4. 초기 단일행 시드 (캐시 테이블) — 없으면 코드가 기대하는 id=1 행 생성
-- ===========================================================================
insert into public.report_style_rules (id) values (1) on conflict (id) do nothing;
insert into public.feedback_rules (id, feedback_count) values (1, 0) on conflict (id) do nothing;


-- ===========================================================================
-- 5. RLS(행 보안) — 보고서/지식/자문 테이블만 활성 + anon 전체 정책
--    (대시보드는 anon 키로 접근하므로 정책이 있어야 동작)
-- ===========================================================================
do $$
declare t text;
begin
  foreach t in array array[
    'document_chunks','report_samples','report_style_rules',
    'report_directives','report_feedback','chat_logs']
  loop
    execute format('alter table public.%I enable row level security;', t);
    execute format($p$create policy "anon_all_%1$s" on public.%1$I
                       for all to anon using (true) with check (true);$p$, t);
  end loop;
exception when duplicate_object then null;   -- 정책이 이미 있으면 무시
end $$;


-- ===========================================================================
-- 6. Storage 버킷 (uploads, private) — 원본 파일 보관
-- ===========================================================================
insert into storage.buckets (id, name, public)
values ('uploads', 'uploads', false)
on conflict (id) do nothing;

do $$
begin
  create policy "uploads_anon_all" on storage.objects
    for all to anon
    using (bucket_id = 'uploads') with check (bucket_id = 'uploads');
exception when duplicate_object then null;
end $$;


-- ============================================================================
--  regulatory-kb (OKF 법령 요약 레이어) — kb_documents / kb_chunks
--  document_chunks(조문 원문)와 별개 레이어. 조문 인용은 그쪽, 요약·실무는 이쪽.
--  임베딩은 voyage-law-2(1024). 적재: import_regulatory_kb.py / add_law.py. (배경역사 #21)
-- ============================================================================
create table if not exists public.kb_documents (
  id bigint generated by default as identity primary key,
  dedup_key text, title text not null, concept_type text, family text,
  law_type text, law_number text, enforcement_date text, competent_authority text,
  status text not null default 'current', superseded_by text,
  path text not null, description text, body_md text, created_at timestamptz default now()
);
create unique index if not exists kb_documents_path_uidx on public.kb_documents(path);
create index if not exists kb_documents_dedup_key_idx on public.kb_documents(dedup_key);
create index if not exists kb_documents_status_idx on public.kb_documents(status);

create table if not exists public.kb_chunks (
  id bigint generated by default as identity primary key,
  doc_id bigint not null references public.kb_documents(id) on delete cascade,
  chunk_idx integer, content text not null, embedding vector(1024), created_at timestamptz default now()
);
create index if not exists kb_chunks_doc_id_idx on public.kb_chunks(doc_id);
create index if not exists kb_chunks_content_trgm_idx on public.kb_chunks using gin (content gin_trgm_ops);
create index if not exists kb_chunks_embedding_hnsw_idx on public.kb_chunks using hnsw (embedding vector_cosine_ops) with (m='16', ef_construction='64');

alter table public.kb_documents enable row level security;
alter table public.kb_chunks enable row level security;
-- 정책: kb_documents_anon_select / kb_chunks_anon_select (for select to anon using(true)).
-- RPC: match_kb_chunks_semantic / search_kb_chunks_trgm (기본 only_current=true) / insert_kb_chunks(적재용).

-- ============================================================================
--  여기까지 'Run' 성공이면 데이터베이스 준비 완료!
--
--  남은 설정 (SQL 아님 — 콘솔/단계에서)
--   (A) Anthropic 키 등록: 대시보드가 app_config.claude_key 를 읽습니다.
--        예) insert into public.app_config(key,value)
--               values ('claude_key','sk-ant-여기에-본인-키');   -- 직접 입력
--   (B) Edge Function 'voyage-embed' 배포 + Secrets(VOYAGE_API_KEY) 설정
--   (C) GitHub Secrets 입력 후 Actions 워크플로우 'Enable'
--
--  [참고/선택] 고급 자동복구(pg_cron + GitHub PAT 디스패치, 무음실패 알림)는
--  운영자 저장소(repo)·Vault에 종속된 기능이라 이 배포본에서는 제외했습니다.
--  필요하면 강사가 별도 안내합니다.
-- ============================================================================

-- ═══════════════════════════════════════════════════════════════════════════
-- KB 품질 지표 뷰 (2026-08-02, 개선⑫ — 운영 상태 탭 'KB 품질' 카드가 조회)
--   저품질 등재(본문 부실·조문 미파싱)를 우연이 아니라 상시로 드러내기 위한 것.
-- ═══════════════════════════════════════════════════════════════════════════
create or replace view public.kb_quality_low_docs as
select doc_name, doc_category, sum(length(content))::int as chars, count(*)::int as chunks
from public.document_chunks where status='current'
group by doc_name, doc_category order by chars asc limit 15;

create or replace view public.kb_quality_article_parse as
select doc_name, count(*)::int as total_chunks,
  (count(*) filter (where article_no is not null and article_no <> ''))::int as parsed_chunks,
  round(100.0*(count(*) filter (where article_no is not null and article_no <> ''))/count(*),1) as parse_pct
from public.document_chunks
where status='current'
  and doc_category not in ('보도자료','기타','회의록','해외동향','추가지식','ITU-R')
group by doc_name having count(*) >= 3
order by parse_pct asc limit 15;

grant select on public.kb_quality_low_docs, public.kb_quality_article_parse to anon, authenticated;
