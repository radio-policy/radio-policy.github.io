-- 20260925161855 list_index_rpcs_4_3_2

-- §4-3-2 (#221) 목록 전용 RPC 4개 — 목록 화면이 원문 청크 전량을 받던 것을 대체.
-- 모두 jsonb 한 값으로 돌려준다: PostgREST max_rows=1000 이 집합 반환 RPC에도 걸려
-- 보도자료 1,142줄이 잘리기 때문(표 반환이면 142건 누락). SECURITY INVOKER(기본) — 브라우저가 anon으로
-- 이미 읽는 표와 같은 권한·RLS. 파싱 규칙은 app.js 종전 경로와 같게(제목 정규식은 브라우저가 그대로 적용).

-- ① 보도자료 목록: '##'로 시작하는 줄만 [doc_name, line] — id·줄 순서 유지(첫 등장 doc_name·동점 순서 보존)
create or replace function public.press_index()
returns jsonb
language sql stable
set search_path = public
as $$
  select coalesce(jsonb_agg(jsonb_build_array(c.doc_name, l.line) order by c.id, l.ord), '[]'::jsonb)
  from document_chunks c
  cross join lateral regexp_split_to_table(c.content, E'\n') with ordinality as l(line, ord)
  where c.doc_category = '보도자료'
    and c.content ~ '## [0-9]{6}'
    and left(l.line, 2) = '##'
$$;

-- ② 회의록 목록: 문서별로 청크를 이어 붙여 '## YYMMDD 제목' 섹션으로 자른 뒤
--    [doc_name, ymd, title, summary, src_url] — 요약은 섹션 앞 900자 안 첫 '요약:' 줄, URL은 섹션 안 첫 '(원문: URL)'
create or replace function public.minutes_index()
returns jsonb
language sql stable
set search_path = public
as $$
  with d as (
    select c.doc_name, string_agg(c.content, '' order by c.chunk_index) as full_text
    from document_chunks c
    where c.doc_category = '회의록'
    group by c.doc_name
  ), s as (
    select d.doc_name, t.sec, t.ord
    from d cross join lateral regexp_split_to_table(d.full_text, '\n(?=## \d{6} )') with ordinality as t(sec, ord)
  )
  select coalesce(jsonb_agg(jsonb_build_array(
           s.doc_name,
           substring(s.sec from '^## (\d{6}) '),
           substring(s.sec from '^## \d{6} ([^\r\n]+)'),
           substring(left(s.sec, 900) from '(?n)^요약:\s*(.+)$'),
           substring(s.sec from '\(원문:\s*(https?:[^\s)]+)\)'))
         order by s.doc_name, s.ord), '[]'::jsonb)
  from s
  where s.sec ~ '^## \d{6} [^\r\n]'
$$;

-- ③ 보도자료·회의록 상세 1건: 문서 전체 대신 그 날짜('## YYMMDD')로 시작하는 섹션들만 (제목 대조는 브라우저)
create or replace function public.doc_sections(p_doc text, p_ymd text)
returns jsonb
language sql stable
set search_path = public
as $$
  with f as (
    select string_agg(c.content, '' order by c.chunk_index) as t
    from document_chunks c
    where c.doc_name = p_doc
  )
  select coalesce(jsonb_agg(t.sec order by t.ord), '[]'::jsonb)
  from f cross join lateral regexp_split_to_table(f.t, '\n(?=## \d{6})') with ordinality as t(sec, ord)
  where p_ymd ~ '^\d{6}$'
    and left(t.sec, 9) = '## ' || p_ymd
$$;

-- ④ 발언자 드롭다운: 원표기별 건수 [speaker, n] — NFC·trim 병합은 브라우저가 종전 규칙(_nfc().trim())으로 한다
create or replace function public.speaker_index()
returns jsonb
language sql stable
set search_path = public
as $$
  select coalesce(jsonb_agg(jsonb_build_array(s.speaker, s.n)), '[]'::jsonb)
  from (select speaker, count(*) as n
        from assembly_speeches
        where speaker is not null
        group by speaker) s
$$;

-- 권한(#214·#186 규칙): PUBLIC 기본 EXECUTE를 걷고 3역할에 명시 부여
revoke all on function public.press_index()               from public;
revoke all on function public.minutes_index()             from public;
revoke all on function public.doc_sections(text, text)    from public;
revoke all on function public.speaker_index()             from public;
grant execute on function public.press_index()            to anon, authenticated, service_role;
grant execute on function public.minutes_index()          to anon, authenticated, service_role;
grant execute on function public.doc_sections(text, text) to anon, authenticated, service_role;
grant execute on function public.speaker_index()          to anon, authenticated, service_role;

notify pgrst, 'reload schema';;
