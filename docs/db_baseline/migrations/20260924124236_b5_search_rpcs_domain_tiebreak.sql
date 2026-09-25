-- 20260924124236 b5_search_rpcs_domain_tiebreak

-- B-5 (#208, 2026-09-24, 운영자 결정 (가)) 확정판 — 자문 키워드 팬아웃 서버 RPC.
-- 선별 규칙: 질문 키워드를 많이 담은 청크 → 그 키워드가 조문 제목에 있는 청크 → 조문(제N조) → 전파·통신 계열 문서(DOMAIN_DOC_RE와 동일: 전파|통신|무선|주파수) → id.
-- 도메인 동점 처리는 1차 A/B에서 '신고·기한·면제' 같은 일반어 조합이 지방세법·공정거래법·공사업법 조문을 끌어오던 3문항(q08·q14·q17)의 보정.
-- 한국어 키워드는 strpos(대소문자 없음), 영문 포함 키워드만 ilike. 2~3자 한국어는 trgm GIN 후보가 전체의 40%라 비트맵 경로가 오히려 느려(4.5s) 함수 안에서는 끈다.

create or replace function public.search_chunks_keywords(p_keywords text[], p_per_kw integer default 4)
returns table(kw_ord integer, id bigint, doc_name text, doc_category text, chunk_index integer,
              content text, notice_no text, article_no text, effective_date text)
language sql stable
set enable_bitmapscan = off
as $$
with recursive kws as (
  select kw, ord::int as ord, (kw ~ '[A-Za-z]') as ci
  from unnest(p_keywords) with ordinality as k(kw, ord)
),
m as materialized (
  select c.id, c.article_no, (c.doc_name ~ '전파|통신|무선|주파수') as dom, kk.kw_ords, kk.t_ords
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
g(kord, picked, out_ids) as (
  select 0, '{}'::bigint[], '{}'::bigint[]
  union all
  select g.kord + 1, g.picked || s.ids, s.ids
  from g
  cross join lateral (
    select coalesce(array_agg(z.id order by z.rn), '{}') as ids
    from (
      select m.id,
             row_number() over (order by cardinality(m.kw_ords) desc,
                                         coalesce((g.kord + 1) = any(m.t_ords), false) desc,
                                         (m.article_no ~ '^\d+조') desc,
                                         m.dom desc,
                                         m.id) as rn
      from m
      where (g.kord + 1) = any(m.kw_ords) and not (m.id = any(g.picked))
    ) z
    where z.rn <= p_per_kw
  ) s
  where g.kord < (select count(*) from kws)
)
select g.kord, c.id, c.doc_name, c.doc_category, c.chunk_index, c.content, c.notice_no, c.article_no, c.effective_date
from g
cross join lateral unnest(g.out_ids) with ordinality as u(id, rn)
join document_chunks c on c.id = u.id
where g.kord > 0
order by g.kord, u.rn;
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
  select c.id, (c.doc_name ~ '전파|통신|무선|주파수') as dom, kk.t_ords, kk.c_ords
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
            row_number() over (order by cardinality(m.t_ords) desc, coalesce(cardinality(m.c_ords), 0) desc, m.dom desc, m.id) as rn
     from m where k.ord = any(m.t_ords)
     order by rn limit p_title_limit)
    union all
    (select 'content'::text, m.id,
            row_number() over (order by cardinality(m.c_ords) desc, coalesce(cardinality(m.t_ords), 0) desc, m.dom desc, m.id) as rn
     from m where k.ord = any(m.c_ords)
     order by rn limit p_content_limit)
  ) t
)
select p.kw_ord, p.hit_col, c.id, c.doc_name, c.article_no, c.content
from pick p
join document_chunks c on c.id = p.id
order by p.kw_ord, (p.hit_col = 'title') desc, p.rn;
$$;;
