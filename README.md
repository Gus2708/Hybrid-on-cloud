# Backend — Ferretería El Serrucho

API REST en Flask para inventario de ferretería. Lee `MAESTRO_ACTUAL.csv` y sincroniza con Supabase.

## Estructura

```
backend serrucho/
├── app.py              # API Flask (búsqueda, precios en Bs, paginación)
├── sync.py             # Sincronizador CSV → Supabase
├── config.py           # Configuración central (lee .env y env vars)
├── supabase_rest.py    # Cliente REST para Supabase (sin supabase-py)
├── test_conexion.py    # Diagnóstico de conectividad (ejecutar primero)
├── run_sync.bat        # Atajo para sincronizar desde Windows
├── requirements.txt    # Dependencias (Flask, requests, python-dotenv)
├── .env.example        # Plantilla de variables de entorno
└── sql/
    └── crear_tabla_productos.sql  # SQL para crear tabla en Supabase
```

## Configuración rápida

1. Copiar `.env.example` → `.env` y completar los valores:
   ```
   TASA_BS=100.0
   SUPABASE_REST_URL=https://tu-proyecto.supabase.co
   SUPABASE_ANON_KEY=eyJ...
   ```

2. Instalar dependencias:
   ```powershell
   pip install -r requirements.txt
   ```

3. Crear la tabla en Supabase:
   - Ir a Supabase → SQL Editor
   - Ejecutar `sql/crear_tabla_productos.sql`

4. Verificar conectividad:
   ```powershell
   python test_conexion.py
   ```

5. Sincronizar CSV:
   ```powershell
   python sync.py once
   ```

6. Lanzar API:
   ```powershell
   python app.py
   ```

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Estado del servidor + info del cache |
| GET | `/api/v1/buscar?q=martillo` | Buscar productos |
| GET | `/api/v1/buscar?q=tornillo&stock=1&limit=20&offset=0` | Búsqueda paginada con stock |
| GET | `/api/v1/tasa` | Tasa USD→Bs configurada |
| GET | `/api/v1/producto/1234` | Detalle por código interno o de barras |

## Variables de entorno

| Variable | Default | Descripción |
|----------|---------|-------------|
| `SUPABASE_REST_URL` | URL del proyecto | URL base de Supabase |
| `SUPABASE_ANON_KEY` | anon JWT | Clave pública de Supabase |
| `TASA_BS` | `100.0` | Tasa de cambio USD → Bolívares |
| `CSV_SOURCE_PATH` | ruta OFICINA | Ruta al MAESTRO_ACTUAL.csv |
| `PORT` | `5000` | Puerto de la API |
| `FLASK_DEBUG` | `0` | Debug mode (1=activado) |
