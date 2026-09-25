-- 20260924122701 b5_search_keyword_rpcs

-- B-5 (#207, 2026-09-24, 운영자 결정 (가)): 자문 키워드 팬아웃을 서버 RPC로 통합 + 결정적 선별
-- 규칙: 키워드마다 '질문 키워드를 몇 개 담았나' → 그 키워드가 조문 제목에 있나 → 조문(제N조)인가 → id.
-- 한국어 키워드는 strpos(대소문자 없음, ilike의 4배 빠름), 영문 포함 키워드만 ilike. 2~3자 한국어는 trgm GIN 후보가
-- 전체의 40%라 비트맵 경로가 오히려 느려(실측 4.5s) 함수 안에서는 비트맵을 끈다(pkey/status 인덱스 순차 걷기).

create or replace function public.search_chunks_keywords(p_keywords text[], p_per_kw integer default 4)
returns table(kw_ord integer, id bigint, doc_name text, doc_category text, chunk_index integer,
              content text, notice_no text, article_no text, effective_date text)
language sql stable
set enable_bitmapscan = off
as $$
with kws as (
  select kw, ord::int as ord, (kw ~ '[A-Za-z]') as ci
  from unnest(p_keywords) with ordinality as k(kw, ord)
),
m as materialized (
  select c.id, c.article_no, kk.kw_ords, kk.t_ords
  from document_chunks c
  cross join lateral (
    select array_agg(x.ord order by x.ord) filter (where x.hit)  as kw_ords,
           array_agg(x.ord order by x.ord) filter (where x.thit) as t_ords
    from (
      select k.ord,
             case when k.ci then c.content ilike '%' || k.kw || '%' else strpos(c.content, k.kw) > 0 end as hit,
             case when k.ci then coalesce(c.article_no, '') ilike '%' || k.kw || '%' else strpos(coalesce(c.article_no, ''), k.kw) > 0 end as thit
      from kws k
    ) x
  ) kk
  where c.is_approved and c.status = 'current' and kk.kw_ords is not null
),
pick as (
  select k.ord as kw_ord, t.id, t.rn
  from kws k
  cross join lateral (
    select m.id,
           row_number() over (order by cardinality(m.kw_ords) desc,
                                       coalesce(k.ord = any(m.t_ords), false) desc,
                                       (m.article_no ~ '^\d+조') desc,
                                       m.id) as rn
    from m
    where k.ord = any(m.kw_ords)
    order by rn
    limit p_per_kw
  ) t
)
select p.kw_ord, c.id, c.doc_name, c.doc_category, c.chunk_index, c.content, c.notice_no, c.article_no, c.effective_date
from pick p
join document_chunks c on c.id = p.id
order by p.kw_ord, p.rn;
$$;

create or replace function public.search_law_articles_kw(p_keywords text[], p_title_limit integer default 40, p_content_limit integer default 10)
returns table(kw_ord integer, hit_col text, id bigint, doc_name text, article_no text, content text)
language sql stable
set enable_bitmapscan = off
as $$
with kws as (
  select kw, ord::int as ord, (kw ~ '[A-Za-z]') as ci
  from unnest(p_keywords) with ordinality as k(kw, ord)
),
m as materialized (
  select c.id, kk.t_ords, kk.c_ords
  from document_chunks c
  cross join lateral (
    select array_agg(x.ord order by x.ord) filter (where x.thit) as t_ords,
           array_agg(x.ord order by x.ord) filter (where x.hit)  as c_ords
    from (
      select k.ord,
             case when k.ci then c.content ilike '%' || k.kw || '%' else strpos(c.content, k.kw) > 0 end as hit,
             case when k.ci then c.article_no ilike '%' || k.kw || '%' else strpos(c.article_no, k.kw) > 0 end as thit
      from kws k
    ) x
  ) kk
  where c.is_approved and c.status = 'current' and c.article_no is not null
    and c.doc_name !~* '\.(pdf|md|docx|hwp)$'
    and (kk.t_ords is not null or kk.c_ords is not null)
),
pick as (
  select k.ord as kw_ord, t.hit_col, t.id, t.rn
  from kws k
  cross join lateral (
    (select 'title'::text as hit_col, m.id,
            row_number() over (order by cardinality(m.t_ords) desc, coalesce(cardinality(m.c_ords), 0) desc, m.id) as rn
     from m where k.ord = any(m.t_ords)
     order by rn limit p_title_limit)
    union all
    (select 'content'::text, m.id,
            row_number() over (order by cardinality(m.c_ords) desc, coalesce(cardinality(m.t_ords), 0) desc, m.id) as rn
     from m where k.ord = any(m.c_ords)
     order by rn limit p_content_limit)
  ) t
)
select p.kw_ord, p.hit_col, c.id, c.doc_name, c.article_no, c.content
from pick p
join document_chunks c on c.id = p.id
order by p.kw_ord, (p.hit_col = 'title') desc, p.rn;
$$;

-- 법령 동향: 종전 클라이언트 로직(법령별 최신 1건 → 입법예고 전부 + 시행예정 + 최근 p_days일 → 공포일 내림차순 p_limit건)을 서버에서
create or replace function public.law_track_recent(p_days integer default 180, p_limit integer default 25)
returns table(law_nm text, law_type text, ann_type text, public_dt text, enf_dt text, summary text)
language sql stable
as $$
  with latest as (
    select distinct on (case when a.law_type = 'lsAnc' then 'lsAnc::' || coalesce(a.law_nm, '') else coalesce(a.law_nm, '') end)
           a.law_nm, a.law_type, a.ann_type, a.public_dt, a.enf_dt, a.summary
    from law_amendments a
    order by case when a.law_type = 'lsAnc' then 'lsAnc::' || coalesce(a.law_nm, '') else coalesce(a.law_nm, '') end,
             regexp_replace(coalesce(a.public_dt, ''), '\D', '', 'g') desc
  )
  select l.law_nm, l.law_type, l.ann_type, l.public_dt, l.enf_dt, l.summary
  from latest l
  where l.law_type = 'lsAnc'
     or regexp_replace(coalesce(l.enf_dt, ''), '\D', '', 'g') >= to_char(now() at time zone 'Asia/Seoul', 'YYYYMMDD')
     or regexp_replace(coalesce(l.public_dt, ''), '\D', '', 'g') >= to_char((now() at time zone 'Asia/Seoul') - make_interval(days => p_days), 'YYYYMMDD')
  order by regexp_replace(coalesce(l.public_dt, ''), '\D', '', 'g') desc
  limit p_limit;
$$;

grant execute on function public.search_chunks_keywords(text[], integer) to anon, authenticated, service_role;
grant execute on function public.search_law_articles_kw(text[], integer, integer) to anon, authenticated, service_role;
grant execute on function public.law_track_recent(integer, integer) to anon, authenticated, service_role;;
