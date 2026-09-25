-- 20260924123026 b5_search_chunks_keywords_greedy

-- B-5 (#207): search_chunks_keywords 확정판 — 앞 키워드가 집은 청크는 뒤 키워드가 다시 집지 않는다(키워드당 '새 청크' p_per_kw건).
-- 실측: 겹침 허용판은 10키워드 40칸이 8~10청크로 뭉쳤고(질문 키워드를 가장 많이 담은 한 청크가 매 키워드의 1위), 이 판은
-- 같은 질문에서 고시 4조·14조(재할당의 신청)·시행령 11조·별표 1 등 40칸을 서로 다른 청크로 채웠다.
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
$$;;
