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
-- migración. Ver docs/base-de-datos/SECURITY-RLS.md para el procedimiento paso a paso.
-- =============================================================

-- Ejecutar en: Supabase → SQL Editor
-- Este script es idempotente: se puede correr varias veces sin error.

-- =============================================================
-- 0. Barrido de policies de escritura preexistentes
--
-- Las policies RLS son PERMISIVAS: se combinan con OR. Basta con que
-- sobreviva una sola que le dé escritura a anon para que todo el
-- endurecimiento de abajo no sirva de nada.
--
-- La primera versión de este script borraba por nombre ("Escritura anon
-- productos"), pero las policies reales del proyecto se llamaban distinto
-- ("Sync Engine - write productos", "Active employees - write productos",
-- "clientes_anon_update", "Allow anon - all tazas"...). El script corría sin
-- error y dejaba anon escribiendo igual — un falso OK peligroso.
--
-- Por eso ahora se barre por ROL y no por nombre: se elimina toda policy de
-- escritura sobre estas tablas que no sea exclusiva de service_role, salvo
-- las dos excepciones que las apps necesitan y que se recrean más abajo.
-- Los SELECT no se tocan: la lectura sigue siendo pública a propósito.
-- =============================================================
DO $$
DECLARE
    p RECORD;
    n INT := 0;
BEGIN
    FOR p IN
        SELECT tablename, policyname, cmd, roles
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename IN ('productos', 'ventas', 'ventas_detalle',
                            'clientes', 'tazas', 'comandos_remotos')
          AND cmd <> 'SELECT'
          AND roles <> '{service_role}'::name[]
          AND policyname NOT IN ('Insercion anon comandos_remotos',
                                 'App marca error_local comandos_remotos')
    LOOP
        EXECUTE format('DROP POLICY %I ON public.%I', p.policyname, p.tablename);
        RAISE NOTICE 'Eliminada: "%" (% sobre %) roles=%',
                     p.policyname, p.cmd, p.tablename, p.roles;
        n := n + 1;
    END LOOP;
    RAISE NOTICE '--- Policies de escritura eliminadas: % ---', n;
END $$;

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
-- DELETE queda restringido a service_role, y UPDATE también salvo la
-- excepción acotada del final: la app necesita poder marcar 'error_local'
-- un comando colgado, y solo eso.
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

-- Excepción necesaria: El Serrucho Go marca como 'error_local' un comando que
-- quedó colgado (src/hooks/useSyncStatus.ts). Con solo la policy de UPDATE
-- restringida a service_role, esa función de la app dejaría de operar en
-- silencio. Se permite el UPDATE desde la app pero acotado por dos lados:
--   * WITH CHECK: la fila resultante SOLO puede quedar en 'error_local', así
--     que no se puede usar para marcar un comando como 'completado'.
--   * GRANT por columna (más abajo): solo se puede tocar la columna 'status'.
DROP POLICY IF EXISTS "App marca error_local comandos_remotos" ON public.comandos_remotos;
CREATE POLICY "App marca error_local comandos_remotos"
    ON public.comandos_remotos
    FOR UPDATE
    TO anon, authenticated
    USING (true)
    WITH CHECK (status = 'error_local');

-- Limita a nivel de privilegio qué columnas puede modificar la app. Sin esto,
-- la policy de arriba dejaría cambiar cualquier columna mientras el status
-- final fuera 'error_local'.
REVOKE UPDATE ON public.comandos_remotos FROM anon, authenticated;
GRANT  UPDATE (status) ON public.comandos_remotos TO anon, authenticated;

-- =============================================================
-- 7. Verificación
--
-- No alcanza con listar las policies y mirarlas a ojo: así fue como la
-- primera versión pasó por buena dejando anon con escritura. Esta consulta
-- clasifica cada policy de escritura y marca las que son un problema.
--
-- Resultado esperado: solo filas 'OK'. Las dos únicas policies de escritura
-- que no son de service_role deben ser las excepciones de comandos_remotos
-- (INSERT público y el UPDATE acotado a 'error_local').
-- =============================================================
SELECT
    tablename,
    policyname,
    cmd,
    roles,
    CASE
        WHEN roles = '{service_role}'::name[] THEN 'OK - backend'
        WHEN policyname = 'Insercion anon comandos_remotos' THEN 'OK - la app encola comandos'
        WHEN policyname = 'App marca error_local comandos_remotos' THEN 'OK - excepcion acotada'
        ELSE '*** REVISAR: da escritura fuera de service_role ***'
    END AS veredicto
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('productos', 'ventas', 'ventas_detalle', 'clientes', 'tazas', 'comandos_remotos')
  AND cmd <> 'SELECT'
ORDER BY (roles = '{service_role}'::name[]), tablename, cmd;
