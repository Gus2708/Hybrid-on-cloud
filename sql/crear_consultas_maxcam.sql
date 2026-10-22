-- Bridge table: Serrucho Go asks "is this product available at Maxcam BQ?",
-- the local listener (backend serrucho/listener_maxcam.py) answers it.
-- Run once in the Supabase SQL editor of the Serrucho project.

create table if not exists public.consultas_maxcam (
    id             uuid primary key default gen_random_uuid(),
    codigo_interno text not null,
    status         text not null default 'pendiente'
                   check (status in ('pendiente', 'procesando', 'listo', 'error')),
    resultado      jsonb,
    error          text,
    creado_en      timestamptz not null default now(),
    actualizado_en timestamptz not null default now()
);

create index if not exists idx_consultas_maxcam_cola
    on public.consultas_maxcam (creado_en) where status in ('pendiente', 'procesando');
create index if not exists idx_consultas_maxcam_codigo
    on public.consultas_maxcam (codigo_interno, creado_en desc);

-- Employees (authenticated) can create requests and read answers. Only the listener
-- (service_role, bypasses RLS) can change status/resultado; the answer carries
-- supplier prices, so anon gets nothing.
alter table public.consultas_maxcam enable row level security;
revoke all on public.consultas_maxcam from anon, authenticated;
grant select, insert on public.consultas_maxcam to authenticated;

drop policy if exists consultas_maxcam_select on public.consultas_maxcam;
create policy consultas_maxcam_select on public.consultas_maxcam
    for select to authenticated using (true);

drop policy if exists consultas_maxcam_insert on public.consultas_maxcam;
create policy consultas_maxcam_insert on public.consultas_maxcam
    for insert to authenticated
    with check (status = 'pendiente' and resultado is null and error is null);
