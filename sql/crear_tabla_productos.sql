-- =============================================================
-- crear_tabla_productos.sql
-- Tabla de productos para Ferretería El Serrucho
-- Ejecutar en: Supabase → SQL Editor
-- =============================================================

-- 1. Crear la tabla
CREATE TABLE IF NOT EXISTS public.productos (
    codigo_interno  TEXT        PRIMARY KEY,
    descripcion     TEXT        NOT NULL DEFAULT '',
    unidad          TEXT        NOT NULL DEFAULT '',
    codigo_barras   TEXT        NOT NULL DEFAULT '',
    costo           NUMERIC(20,4) NOT NULL DEFAULT 0,
    precio_venta    NUMERIC(20,4) NOT NULL DEFAULT 0,
    existencia      NUMERIC(20,4) NOT NULL DEFAULT 0,
    actualizado_en  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Índice para búsqueda rápida por descripción (ilike / LIKE)
CREATE INDEX IF NOT EXISTS idx_productos_descripcion
    ON public.productos (descripcion);

-- 3. Índice por código de barras (lookup en caja/scanner)
CREATE INDEX IF NOT EXISTS idx_productos_barcode
    ON public.productos (codigo_barras);

-- 4. Índice de texto completo (opcional, para búsquedas más avanzadas)
CREATE INDEX IF NOT EXISTS idx_productos_fts
    ON public.productos
    USING GIN (to_tsvector('spanish', descripcion));

-- 5. Trigger para actualizar automáticamente la columna actualizado_en
CREATE OR REPLACE FUNCTION public.set_actualizado_en()
RETURNS TRIGGER AS $$
BEGIN
    NEW.actualizado_en = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_productos_actualizado_en ON public.productos;
CREATE TRIGGER trg_productos_actualizado_en
    BEFORE UPDATE ON public.productos
    FOR EACH ROW
    EXECUTE FUNCTION public.set_actualizado_en();

-- =============================================================
-- 6. Row Level Security (RLS)
-- Habilitar RLS pero permitir lectura pública (anon key)
-- y escritura solo con service_role (para sync.py con anon key
-- en modo upsert, necesitas también la policy de INSERT/UPDATE)
-- =============================================================

ALTER TABLE public.productos ENABLE ROW LEVEL SECURITY;

-- Política: lectura pública (anon puede hacer SELECT)
DROP POLICY IF EXISTS "Lectura publica productos" ON public.productos;
CREATE POLICY "Lectura publica productos"
    ON public.productos
    FOR SELECT
    USING (true);

-- Política: inserción/actualización con anon key
-- (si prefieres restringir solo a service_role, eliminar esta policy
--  y usar SUPABASE_SERVICE_ROLE_KEY en sync.py en vez de anon key)
DROP POLICY IF EXISTS "Escritura anon productos" ON public.productos;
CREATE POLICY "Escritura anon productos"
    ON public.productos
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- =============================================================
-- 7. Verificación
-- =============================================================
SELECT
    column_name,
    data_type,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name   = 'productos'
ORDER BY ordinal_position;
