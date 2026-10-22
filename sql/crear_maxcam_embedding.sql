-- Maxcam catalog embeddings (same model/dimensions as productos_embedding) and an
-- RPC that returns the closest Maxcam products for a Serrucho product.
-- Run once in the Supabase SQL editor of the Serrucho project.

create extension if not exists vector;

create table if not exists public.maxcam_embedding (
    sku           text primary key,
    nombre        text not null,
    marca         text,
    rubro         text,
    rubro_hijo    text,
    codigo_alt    text,
    hash_desc     text not null,
    embedding     vector(1536) not null,
    modelo        text not null,
    actualizado_en timestamptz not null default now()
);

create index if not exists idx_maxcam_embedding_hnsw
    on public.maxcam_embedding using hnsw (embedding vector_cosine_ops);

-- Supplier data: no direct access for anon/authenticated. Writes come from the
-- service_role key (bypasses RLS); reads go through the RPC below.
alter table public.maxcam_embedding enable row level security;
revoke all on public.maxcam_embedding from anon, authenticated;

-- Closest Maxcam products to a Serrucho product (by its stored embedding).
-- Returns only identification fields, never prices or stock.
create or replace function public.maxcam_equivalentes(
    p_codigo_interno text,
    p_limite int default 3,
    p_umbral float default 0.5
)
returns table (sku text, nombre text, marca text, similitud float)
language sql
stable
security definer
set search_path = public, extensions
as $$
    select m.sku, m.nombre, m.marca,
           1 - (m.embedding <=> p.embedding) as similitud
    from public.productos_embedding p
    cross join lateral (
        select * from public.maxcam_embedding
        order by embedding <=> p.embedding
        limit p_limite
    ) m
    where p.codigo_interno = p_codigo_interno
      and 1 - (m.embedding <=> p.embedding) >= p_umbral
    order by similitud desc;
$$;

revoke all on function public.maxcam_equivalentes(text, int, float) from public;
grant execute on function public.maxcam_equivalentes(text, int, float) to anon, authenticated, service_role;
