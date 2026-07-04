-- ============================================================================
--  cambios_solicitados — Canal App -> Local (write-back hacia HybridLite)
-- ----------------------------------------------------------------------------
--  La app "El Serrucho Go" inserta aquí una solicitud de cambio (precio o stock).
--  El backend (listener_writeback.py) la detecta, la aplica en HybridLite vía
--  automatización de UI, y marca el resultado. El sync normal luego sube el
--  cambio confirmado de vuelta a la tabla `productos`, cerrando el ciclo.
--
--  Ejecutar en: Supabase > SQL Editor.
-- ============================================================================

create table if not exists public.cambios_solicitados (
    id              uuid primary key default gen_random_uuid(),

    -- Qué se quiere cambiar
    tipo            text not null check (tipo in ('precio', 'stock')),
    codigo_producto text not null,                 -- TPC_CODIGOPRODUCTO / EIN_CODIGOPRODUCTO

    -- Valores (según el tipo)
    valor_nuevo     numeric,        -- tipo='precio': nuevo PVP con impuesto
    delta           numeric,        -- tipo='stock' : ajuste +/- de existencia
    motivo          text,           -- obligatorio para ajustes de stock (auditoría)

    -- Estado del procesamiento
    status          text not null default 'pendiente'
                    check (status in ('pendiente','aplicando','aplicado','error','rechazado')),
    resultado       text,           -- mensaje de éxito o detalle del error
    intentos        int  not null default 0,

    -- Trazabilidad
    solicitado_por  text,           -- usuario/dispositivo que originó el cambio
    solicitado_en   timestamptz not null default now(),
    aplicado_en     timestamptz,

    -- Snapshot del valor anterior (para revertir/auditar)
    valor_anterior  numeric
);

create index if not exists idx_cambios_status   on public.cambios_solicitados (status);
create index if not exists idx_cambios_producto on public.cambios_solicitados (codigo_producto);

-- ----------------------------------------------------------------------------
--  RLS — mismo modelo que `comandos_remotos`: la app y el backend usan anon key.
--  Ajusta a tu política de seguridad real antes de producción.
-- ----------------------------------------------------------------------------
alter table public.cambios_solicitados enable row level security;

-- La app (anon) puede crear solicitudes y leer su estado.
drop policy if exists cambios_insert_anon on public.cambios_solicitados;
create policy cambios_insert_anon on public.cambios_solicitados
    for insert to anon with check (true);

drop policy if exists cambios_select_anon on public.cambios_solicitados;
create policy cambios_select_anon on public.cambios_solicitados
    for select to anon using (true);

-- El backend (anon, en esta instalación) actualiza el estado/resultado.
drop policy if exists cambios_update_anon on public.cambios_solicitados;
create policy cambios_update_anon on public.cambios_solicitados
    for update to anon using (true) with check (true);

-- ============================================================================
--  Ejemplos de uso (desde la app o para probar manualmente):
--
--    -- Cambiar precio del producto 01234 a 12.50
--    insert into public.cambios_solicitados (tipo, codigo_producto, valor_nuevo, solicitado_por)
--    values ('precio', '01234', 12.50, 'app:serrucho-go');
--
--    -- Ajustar stock del producto 01234 en -3 (merma)
--    insert into public.cambios_solicitados (tipo, codigo_producto, delta, motivo, solicitado_por)
--    values ('stock', '01234', -3, 'DESINCORPORACION DEFECTUOSO', 'app:serrucho-go');
-- ============================================================================
