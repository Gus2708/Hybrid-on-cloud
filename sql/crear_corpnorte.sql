-- Corporación Norte: product embeddings, a similarity RPC and the app bridge table.
-- Run once in the Supabase SQL editor of the Serrucho project (same pattern as the
-- Maxcam tables: crear_maxcam_embedding.sql / crear_consultas_maxcam.sql).

create extension if not exists vector;

-- 1) Embeddings (same model and dimensions as productos_embedding)
create table if not exists public.corpnorte_embedding (
    codigo        text primary key,
    nombre        text not null,
    marca         text,
    categoria     text,
    subcategoria  text,
    hash_desc     text not null,
    embedding     vector(1536) not null,
    modelo        text not null,
    actualizado_en timestamptz not null default now()
);

create index if not exists idx_corpnorte_embedding_hnsw
    on public.corpnorte_embedding using hnsw (embedding vector_cosine_ops);

-- Supplier data: no direct access for anon/authenticated; reads go through the RPC.
alter table public.corpnorte_embedding enable row level security;
revoke all on public.corpnorte_embedding from anon, authenticated;

create or replace function public.corpnorte_equivalentes(
    p_codigo_interno text,
    p_limite int default 3,
    p_umbral float default 0.5
)
returns table (codigo text, nombre text, marca text, similitud float)
language sql
stable
security definer
set search_path = public, extensions
as $$
    select m.codigo, m.nombre, m.marca,
           1 - (m.embedding <=> p.embedding) as similitud
    from public.productos_embedding p
    cross join lateral (
        select * from public.corpnorte_embedding
        order by embedding <=> p.embedding
        limit p_limite
    ) m
    where p.codigo_interno = p_codigo_interno
      and 1 - (m.embedding <=> p.embedding) >= p_umbral
    order by similitud desc;
$$;

revoke all on function public.corpnorte_equivalentes(text, int, float) from public;
grant execute on function public.corpnorte_equivalentes(text, int, float) to anon, authenticated, service_role;

-- 2) Bridge table: Serrucho Go asks, the local listener answers
create table if not exists public.consultas_corpnorte (
    id             uuid primary key default gen_random_uuid(),
    codigo_interno text not null,
    status         text not null default 'pendiente'
                   check (status in ('pendiente', 'procesando', 'listo', 'error')),
    resultado      jsonb,
    error          text,
    creado_en      timestamptz not null default now(),
    actualizado_en timestamptz not null default now()
);

create index if not exists idx_consultas_corpnorte_cola
    on public.consultas_corpnorte (creado_en) where status in ('pendiente', 'procesando');
create index if not exists idx_consultas_corpnorte_codigo
    on public.consultas_corpnorte (codigo_interno, creado_en desc);

alter table public.consultas_corpnorte enable row level security;
revoke all on public.consultas_corpnorte from anon, authenticated;
grant select, insert on public.consultas_corpnorte to authenticated;

drop policy if exists consultas_corpnorte_select on public.consultas_corpnorte;
create policy consultas_corpnorte_select on public.consultas_corpnorte
    for select to authenticated using (true);

drop policy if exists consultas_corpnorte_insert on public.consultas_corpnorte;
create policy consultas_corpnorte_insert on public.consultas_corpnorte
    for insert to authenticated
    with check (status = 'pendiente' and resultado is null and error is null);
