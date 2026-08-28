-- Crear esquema para el módulo de gestión de clientes y licencias
CREATE SCHEMA IF NOT EXISTS hybrid_to_go;

-- Tabla de Clientes
CREATE TABLE IF NOT EXISTS hybrid_to_go.clientes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    empresa TEXT,
    telefono TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Tabla de Licencias
CREATE TABLE IF NOT EXISTS hybrid_to_go.licencias (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID REFERENCES hybrid_to_go.clientes(id),
    hwid TEXT UNIQUE NOT NULL,
    license_key TEXT NOT NULL,
    plan TEXT DEFAULT 'standard', -- standard, premium, enterprise
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE
);

-- Habilitar RLS en el nuevo esquema
ALTER TABLE hybrid_to_go.clientes ENABLE ROW LEVEL SECURITY;
ALTER TABLE hybrid_to_go.licencias ENABLE ROW LEVEL SECURITY;

-- Políticas básicas (pueden ajustarse después)
CREATE POLICY "Permitir lectura de clientes a administradores" ON hybrid_to_go.clientes
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Permitir validación de licencias" ON hybrid_to_go.licencias
    FOR SELECT USING (true);
