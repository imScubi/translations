create extension if not exists vector with schema extensions;

create table if not exists public.chunks (
    id text primary key,
    content text not null,
    context text not null,
    metadata jsonb not null default '{}'::jsonb,
    url text not null,
    revision_id bigint not null,
    content_hash text not null,
    embedding extensions.vector(1024),
    tsv tsvector generated always as (
        setweight(to_tsvector('english', coalesce(context, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(content, '')), 'B')
    ) stored,
    updated_at timestamptz not null default now()
);

create index if not exists chunks_embedding_hnsw
    on public.chunks using hnsw (embedding extensions.vector_cosine_ops)
    with (m = 16, ef_construction = 64);

create index if not exists chunks_tsv_gin on public.chunks using gin (tsv);
create index if not exists chunks_metadata_gin on public.chunks using gin (metadata jsonb_path_ops);
create index if not exists chunks_page_idx on public.chunks ((metadata->>'page'));
create index if not exists chunks_content_type_idx on public.chunks ((metadata->>'content_type'));

alter table public.chunks enable row level security;

create or replace function public.hybrid_search(
    query_text text,
    query_embedding extensions.vector(1024),
    match_count int default 10,
    filter_region text default null,
    filter_character text default null,
    filter_content_type text default null,
    full_text_weight float default 1.0,
    semantic_weight float default 1.0,
    rrf_k int default 60
)
returns table (
    id text,
    content text,
    context text,
    metadata jsonb,
    url text,
    revision_id bigint,
    score double precision,
    fts_rank bigint,
    semantic_rank bigint
)
language sql
stable
set search_path = public, extensions
as $$
with filtered as (
    select c.*
    from chunks c
    where (filter_region is null or c.metadata->'regions' ? filter_region)
      and (filter_character is null or c.metadata->'characters' ? filter_character)
      and (filter_content_type is null or c.metadata->>'content_type' = filter_content_type)
),
full_text as (
    select f.id,
           row_number() over (order by ts_rank_cd(f.tsv, websearch_to_tsquery('english', query_text)) desc) as rank_ix
    from filtered f
    where f.tsv @@ websearch_to_tsquery('english', query_text)
    order by rank_ix
    limit least(match_count, 50) * 4
),
semantic as (
    select f.id,
           row_number() over (order by f.embedding <=> query_embedding) as rank_ix
    from filtered f
    where f.embedding is not null
    order by rank_ix
    limit least(match_count, 50) * 4
)
select c.id,
       c.content,
       c.context,
       c.metadata,
       c.url,
       c.revision_id,
       coalesce(1.0 / (rrf_k + ft.rank_ix), 0.0) * full_text_weight +
       coalesce(1.0 / (rrf_k + s.rank_ix), 0.0) * semantic_weight as score,
       ft.rank_ix as fts_rank,
       s.rank_ix as semantic_rank
from full_text ft
full outer join semantic s on ft.id = s.id
join chunks c on c.id = coalesce(ft.id, s.id)
order by score desc
limit least(match_count, 50);
$$;

revoke execute on function public.hybrid_search from anon, authenticated;
