-- 20260803125129 law_graph_edges_allow_delegation_source

alter table public.law_graph_edges drop constraint law_graph_edges_source_check;
alter table public.law_graph_edges add constraint law_graph_edges_source_check
  check (source = any (array['family','citation','seed','ai','thdcmp','delegation']));;
