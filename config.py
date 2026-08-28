"""
config.py — Configuración central del SaaS Hybrid on Cloud.
Carga variables en este orden de prioridad:
  1. Variables de entorno del sistema (mayor prioridad)
  2. Archivo .env en el mismo directorio (si existe)
  3. Valores por defecto hardcodeados (mínimos de seguridad)
"""
import os
import sys
from pathlib import Path

# Determinar si estamos ejecutando desde un .exe (PyInstaller o Nuitka)
if getattr(sys, 'frozen', False):
    # PyInstaller
    BASE_DIR = Path(sys.executable).parent
    IS_FROZEN = True
elif "__compiled__" in globals() or hasattr(sys, "nuitka_version"):
    # Nuitka (usamos sys.argv[0] que apunta al ejecutable original, no al directorio temporal)
    BASE_DIR = Path(os.path.abspath(sys.argv[0])).parent
    IS_FROZEN = True
else:
    # Entorno de desarrollo
    BASE_DIR = Path(__file__).parent
    IS_FROZEN = False

# Carpeta de datos persistentes (AppData en Windows)
if os.name == 'nt':
    DATA_DIR = Path(os.getenv('APPDATA', str(BASE_DIR))) / "HybridToCloud"
else:
    DATA_DIR = BASE_DIR

# Asegurar que la carpeta de datos existe
os.makedirs(DATA_DIR, exist_ok=True)

# Cargar .env si existe (python-dotenv es opcional)
_env_path = BASE_DIR / ".env"
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

# ─── Gestión de Secretos (Keyring) ───────────────────────────────────────────
import keyring

def get_secret(key, default=None):
    if IS_FROZEN:
        # En producción, intentar primero el Keyring de Windows
        secret = keyring.get_password(SAAS_NAME, key)
        if secret: return secret
    
    # Fallback a variables de entorno
    val = os.environ.get(key, default)
    
    # Si estamos en producción y encontramos el valor en env, guardarlo en Keyring
    if IS_FROZEN and val and val != default:
        try:
            keyring.set_password(SAAS_NAME, key, val)
        except: pass
    
    return val

# ─── Branding & SaaS ─────────────────────────────────────────────────────────
SAAS_NAME     = os.environ.get("SAAS_NAME", "Hybrid to Cloud")
BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "Mi Negocio")
BRAND_LOGO    = os.environ.get("BRAND_LOGO", "assets/logo.png")
VERSION       = "1.2.0"

# ─── Supabase (Backend Cliente) ──────────────────────────────────────────────
SUPABASE_URL = get_secret("SUPABASE_URL", "https://rgniqjfooifchyctnbzu.supabase.co")
SUPABASE_ANON_KEY = get_secret("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJnbmlxamZvb2lmY2h5Y3RuYnp1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzc4NDI2NTUsImV4cCI6MjA5MzQxODY1NX0.MwhE9n5DjbWNN42Qsj-yNmF_sSlOWZbf4mXJy2NUnKQ")
SUPABASE_REST_URL = SUPABASE_URL

# ─── Supabase (Licencias y Actualizaciones Globales) ─────────────────────────
LICENSE_SUPABASE_URL = get_secret("LICENSE_SUPABASE_URL", "https://fbqnthkgyhccridezbcf.supabase.co")
LICENSE_SUPABASE_ANON_KEY = get_secret("LICENSE_SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZicW50aGtneWhjY3JpZGV6YmNmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzc4NTczMTQsImV4cCI6MjA5MzQzMzMxNH0.VhBJje2x4WqIdxHq8lFSHjyh4HMWCRXN1Sw57K7BEj8")


# ─── Tasa de cambio USD → Bolívares ──────────────────────────────────────────
# Actualizar con la tasa actual. Se puede pasar como var de entorno TASA_BS.
TASA_BS_DEFAULT = float(os.environ.get("TASA_BS", "100.0"))

# ─── Ruta del CSV fuente (Local) ──────────────────────────────────────────────
CSV_SOURCE_PATH = os.path.join(str(BASE_DIR), "MAESTRO_ACTUAL.csv")


# ─── Rutas de base de datos HybridLite (Trigger de actualización) ──────────────
RUTA_INVENTARIO = os.environ.get("RUTA_INVENTARIO", r'H:\HybridLite\HybridEmpresa\HybridDataBase\TInventario.dat')
RUTA_PRECIOS    = os.environ.get("RUTA_PRECIOS", r'H:\HybridLite\HybridEmpresa\HybridDataBase\TCostoPrecioInv.Dat')
RUTA_EXISTENCIA = os.environ.get("RUTA_EXISTENCIA", r'H:\HybridLite\HybridEmpresa\HybridDataBase\TExistenciaInv.Dat')

# --- Nuevas Rutas para Ventas y Clientes ---
RUTA_VENTAS         = os.environ.get("RUTA_VENTAS", r'H:\HybridLite\HybridEmpresa\HybridDataBase\TTransaccionvta.dat')
RUTA_VENTAS_DETALLE = os.environ.get("RUTA_VENTAS_DETALLE", r'H:\HybridLite\HybridEmpresa\HybridDataBase\TDetalleVta.dat')
RUTA_CLIENTES       = os.environ.get("RUTA_CLIENTES", r'H:\HybridLite\HybridEmpresa\HybridDataBase\TClientes.dat')

