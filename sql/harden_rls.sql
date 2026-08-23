-- =============================================================
-- harden_rls.sql
-- Endurece las políticas RLS: SELECT sigue siendo público (anon),
-- pero INSERT/UPDATE/DELETE quedan restringidos a service_role
-- en productos, ventas, ventas_detalle, clientes y tazas.
-- La excepción es comandos_remotos: anon conserva SELECT e INSERT
-- (las apps externas insertan comandos remotos con anon), pero
-- UPDATE/DELETE quedan restringidos a service_role (el listener
-- local actualiza el status con la service key).
--
-- ⚠️  NO EJECUTAR hasta haber puesto SUPABASE_SERVICE_KEY en el .env
-- de la PC PRINCIPAL (C:\Proyect\backend serrucho\.env) y haber
-- reiniciado el backend (start_backend.vbs). Si se ejecuta este
-- script ANTES de eso, el backend seguirá escribiendo con la anon
-- key, las políticas lo rechazarán, y la sincronización (sync.py,
-- sync_ventas.py, remote_listener.py, rates_service.py) DEJARÁ DE
-- ESCRIBIR en Supabase silenciosamente hasta que se complete la
-- migración. Ver docs/SECURITY-RLS.md para el procedimiento paso a paso.
-- =============================================================

-- Ejecutar en: Supabase → SQL Editor
-- Este script es idempotente: se puede correr varias veces sin error.

-- =============================================================
-- 1. productos
-- =============================================================
ALTER TABLE public.productos ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Lectura publica productos" ON public.productos;
CREATE POLICY "Lectura publica productos"
    ON public.productos
    FOR SELECT
    USING (true);

-- Elimina la policy anterior de escritura amplia con anon, si existe
DROP POLICY IF EXISTS "Escritura anon productos" ON public.productos;

DROP POLICY IF EXISTS "Escritura service_role productos" ON public.productos;
CREATE POLICY "Escritura service_role productos"
    ON public.productos
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- =============================================================
-- 2. ventas
-- =============================================================
ALTER TABLE public.ventas ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Lectura publica ventas" ON public.ventas;
CREATE POLICY "Lectura publica ventas"
    ON public.ventas
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS "Escritura anon ventas" ON public.ventas;

DROP POLICY IF EXISTS "Escritura service_role ventas" ON public.ventas;
CREATE POLICY "Escritura service_role ventas"
    ON public.ventas
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- =============================================================
-- 3. ventas_detalle
-- =============================================================
ALTER TABLE public.ventas_detalle ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Lectura publica ventas_detalle" ON public.ventas_detalle;
CREATE POLICY "Lectura publica ventas_detalle"
    ON public.ventas_detalle
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS "Escritura anon ventas_detalle" ON public.ventas_detalle;

DROP POLICY IF EXISTS "Escritura service_role ventas_detalle" ON public.ventas_detalle;
CREATE POLICY "Escritura service_role ventas_detalle"
    ON public.ventas_detalle
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- =============================================================
-- 4. clientes
-- =============================================================
ALTER TABLE public.clientes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Lectura publica clientes" ON public.clientes;
CREATE POLICY "Lectura publica clientes"
    ON public.clientes
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS "Escritura anon clientes" ON public.clientes;

DROP POLICY IF EXISTS "Escritura service_role clientes" ON public.clientes;
CREATE POLICY "Escritura service_role clientes"
    ON public.clientes
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- =============================================================
-- 5. tazas (tasas de cambio)
-- =============================================================
ALTER TABLE public.tazas ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Lectura publica tazas" ON public.tazas;
CREATE POLICY "Lectura publica tazas"
    ON public.tazas
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS "Escritura anon tazas" ON public.tazas;

DROP POLICY IF EXISTS "Escritura service_role tazas" ON public.tazas;
CREATE POLICY "Escritura service_role tazas"
    ON public.tazas
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- =============================================================
-- 6. comandos_remotos (caso especial)
-- anon conserva SELECT (el listener local lee comandos pendientes)
-- e INSERT (las apps externas crean comandos remotos con anon).
-- UPDATE/DELETE quedan restringidos a service_role (el listener local
-- actualiza el status del comando con la service key).
-- =============================================================
ALTER TABLE public.comandos_remotos ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Lectura publica comandos_remotos" ON public.comandos_remotos;
CREATE POLICY "Lectura publica comandos_remotos"
    ON public.comandos_remotos
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS "Insercion anon comandos_remotos" ON public.comandos_remotos;
CREATE POLICY "Insercion anon comandos_remotos"
    ON public.comandos_remotos
    FOR INSERT
    WITH CHECK (true);

-- Elimina la policy anterior de escritura amplia con anon (FOR ALL), si existe
DROP POLICY IF EXISTS "Escritura anon comandos_remotos" ON public.comandos_remotos;

DROP POLICY IF EXISTS "Actualizacion service_role comandos_remotos" ON public.comandos_remotos;
CREATE POLICY "Actualizacion service_role comandos_remotos"
    ON public.comandos_remotos
    FOR UPDATE
    TO service_role
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "Borrado service_role comandos_remotos" ON public.comandos_remotos;
CREATE POLICY "Borrado service_role comandos_remotos"
    ON public.comandos_remotos
    FOR DELETE
    TO service_role
    USING (true);

-- =============================================================
-- 7. Verificación: listar todas las policies resultantes
-- =============================================================
SELECT schemaname, tablename, policyname, cmd, roles
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('productos', 'ventas', 'ventas_detalle', 'clientes', 'tazas', 'comandos_remotos')
ORDER BY tablename, cmd;
