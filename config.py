"""
config.py — Configuración central del backend El Serrucho.
Carga variables en este orden de prioridad:
  1. Variables de entorno del sistema (mayor prioridad)
  2. Archivo .env en el mismo directorio (si existe)
  3. Valores por defecto hardcodeados (mínimos de seguridad)
"""
import os
from pathlib import Path

# Cargar .env si existe (python-dotenv es opcional)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path, override=False)  # override=False: env vars del sistema tienen prioridad
        print(f"[CONFIG] .env cargado desde {_env_path}")
    except ImportError:
        # python-dotenv no instalado, leer manualmente (formato KEY=VALUE simple)
        try:
            with open(_env_path, "r", encoding="utf-8") as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line and not _line.startswith("#") and "=" in _line:
                        _k, _v = _line.split("=", 1)
                        _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
                        if _k and _k not in os.environ:
                            os.environ[_k] = _v
            print(f"[CONFIG] .env cargado manualmente desde {_env_path}")
        except Exception:
            pass

# ─── Supabase (cliente Python supabase-py) ───────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://YOUR-PROJECT-REF.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_91qCibM40mWzij-bW5bQyA_xkGA3fsj")

# ─── Supabase REST API (fallback sin supabase-py) ────────────────────────────
# SUPABASE_REST_URL: URL base del proyecto (misma que SUPABASE_URL)
# SUPABASE_ANON_KEY: anon/public JWT — se obtiene en Supabase > Settings > API
SUPABASE_REST_URL = os.environ.get("SUPABASE_REST_URL", "https://YOUR-PROJECT-REF.supabase.co")
SUPABASE_ANON_KEY = os.environ.get(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "REDACTED-JWT-PAYLOAD."
    "REDACTED-JWT-SIGNATURE"
)

# ─── Tasa de cambio USD → Bolívares ──────────────────────────────────────────
# Actualizar con la tasa actual. Se puede pasar como var de entorno TASA_BS.
TASA_BS_DEFAULT = float(os.environ.get("TASA_BS", "100.0"))

# ─── Ruta del CSV fuente (Local) ──────────────────────────────────────────────
CSV_SOURCE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MAESTRO_ACTUAL.csv")


# ─── Rutas de base de datos HybridLite (Trigger de actualización) ──────────────
RUTA_INVENTARIO = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TInventario.dat'
RUTA_PRECIOS    = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TCostoPrecioInv.Dat'
RUTA_EXISTENCIA = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TExistenciaInv.Dat'

# ─── Rutas de base de datos de Ventas (Trigger de actualización) ──────────────
RUTA_VENTAS_CABECERA = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TTransaccionvta.dat'
RUTA_VENTAS_DETALLE  = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TDetalleVta.dat'
RUTA_CLIENTES        = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TClientes.dat'

