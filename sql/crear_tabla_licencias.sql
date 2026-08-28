-- Crear tabla de licencias para activación online
CREATE TABLE IF NOT EXISTS licencias (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    hwid TEXT UNIQUE NOT NULL,
    license_key TEXT NOT NULL,
    user_email TEXT,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE
);

-- Habilitar RLS
ALTER TABLE licencias ENABLE ROW LEVEL SECURITY;

-- Política para lectura pública (solo para validación)
-- En producción, se debería usar una función RPC para mayor seguridad
CREATE POLICY "Permitir validación por HWID" ON licencias
    FOR SELECT
    USING (true);
