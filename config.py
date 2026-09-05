"""
config.py — Configuración central del backend El Serrucho.
Carga variables en este orden de prioridad:
  1. Variables de entorno del sistema (mayor prioridad)
  2. Archivo .env en el mismo directorio (si existe)
  3. Valores por defecto hardcodeados (mínimos de seguridad)
"""
import os
import sys
from pathlib import Path

# ─── Deteccion de ejecutable congelado ───────────────────────────────────────
# Portado desde la rama serrucho. Compilado con Nuitka, __file__ apunta a un
# directorio temporal: hay que resolver la ruta real del .exe para encontrar
# el .env y los assets junto al binario que el usuario ejecuta.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent          # PyInstaller
    IS_FROZEN = True
elif "__compiled__" in globals() or hasattr(sys, "nuitka_version"):
    BASE_DIR = Path(os.path.abspath(sys.argv[0])).parent   # Nuitka
    IS_FROZEN = True
else:
    BASE_DIR = Path(__file__).parent                # desarrollo
    IS_FROZEN = False

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

# ─── Supabase (cliente Python supabase-py) ───────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# ─── Supabase REST API (fallback sin supabase-py) ────────────────────────────
# SUPABASE_REST_URL: URL base del proyecto (misma que SUPABASE_URL)
# SUPABASE_ANON_KEY: anon/public JWT — se obtiene en Supabase > Settings > API
# Configurar en .env (ver .env.example)
SUPABASE_REST_URL = os.environ.get("SUPABASE_REST_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

# SUPABASE_SERVICE_KEY: clave service_role (opcional). Si está presente, las
# operaciones de ESCRITURA (INSERT/UPDATE/DELETE) la usan en vez de la anon key,
# lo que permite endurecer las políticas RLS (ver sql/harden_rls.sql) sin dejar
# de leer con anon. Es opcional: si falta, todo sigue funcionando igual que hoy
# con la anon key para lectura y escritura, por eso NO se advierte si está vacía.
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_REST_URL or not SUPABASE_ANON_KEY:
    print("[CONFIG] ADVERTENCIA: SUPABASE_REST_URL y/o SUPABASE_ANON_KEY no configurados.")
    print("[CONFIG] Crear/verificar el archivo .env con las credenciales del proyecto Supabase.")

# ─── Alertas (opcional) ───────────────────────────────────────────────────────
# URL de webhook para alertas de sync. Vacío = alertas deshabilitadas.
ALERT_WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL", "")

# ─── Auth para endpoints de sync ─────────────────────────────────────────────
# Header X-API-Key requerido en /api/v1/sync/*. Vacío = sin restricción (solo desarrollo).
SYNC_API_KEY = os.environ.get("SYNC_API_KEY", "")

# ─── CORS ─────────────────────────────────────────────────────────────────────
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5000,http://127.0.0.1:5000").split(",") if o.strip()]

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
RUTA_PROVEEDORES     = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TProveedores.Dat'

# ─── Listener de Zelle (zelle_listener.py — correo Outlook via Microsoft Graph) ──
# El puerto IMAP (993) esta bloqueado por el ISP de la tienda (confirmado con pruebas
# de red); el listener usa Graph API por HTTPS/443 en su lugar (ver docs/guias/ZELLE-LISTENER.md).
# ZELLE_EMAIL: cuenta personal de Outlook/Hotmail que recibe los avisos de Zelle
#   (solo informativa/para logs — Graph identifica la cuenta via el login "/me").
# ZELLE_CLIENT_ID: Application (client) ID del App Registration de Azure
#   (cliente público con device-code flow; ver docs/guias/ZELLE-LISTENER.md).
# ZELLE_TRUSTED_SENDERS: direcciones EXACTAS que cuentan como banco real
#   (anti-spoofing). Los avisos de pago recibido vienen de customerservice@... y
#   los de "en revisión" de onlinebanking@... (subdominio ealerts.bankofamerica.com).
#   Un correo cuyo remitente no esté en esta lista se descarta aunque parezca Zelle.
# ZELLE_REQUIRE_DMARC: exigir que el correo haya pasado DMARC (cabecera que agrega
#   Outlook al recibir y el estafador no puede falsificar). Dejar en "1" salvo depuración.
# ZELLE_POLL_INTERVAL_S: segundos entre cada consulta a Graph (polling, no push).
ZELLE_EMAIL = os.environ.get("ZELLE_EMAIL", "")
ZELLE_CLIENT_ID = os.environ.get("ZELLE_CLIENT_ID", "")
ZELLE_TRUSTED_SENDERS = {s.strip().lower() for s in os.environ.get(
    "ZELLE_TRUSTED_SENDERS",
    "customerservice@ealerts.bankofamerica.com,onlinebanking@ealerts.bankofamerica.com",
).split(",") if s.strip()}
ZELLE_REQUIRE_DMARC = os.environ.get("ZELLE_REQUIRE_DMARC", "1") == "1"
ZELLE_POLL_INTERVAL_S = float(os.environ.get("ZELLE_POLL_INTERVAL_S", "5"))

# ─── Marca blanca y licenciamiento ───────────────────────────────────────────
# Portado desde la rama serrucho (empaquetado Nuitka). Las credenciales van por
# entorno, nunca embebidas: ver commit 533d126 "eliminar credenciales embebidas".
#
# DATA_DIR: carpeta de datos persistentes del usuario. En Windows vive en APPDATA
#   para que el ejecutable no escriba junto al .exe (Program Files es de solo
#   lectura para el usuario). security.py guarda ahi el estado de licencia.
# BUSINESS_NAME / BRAND_LOGO: personalizacion visible del producto por cliente.
# LICENSE_SUPABASE_*: proyecto Supabase SEPARADO del de inventario, dedicado a
#   validar licencias por HWID. Sin estas variables, verify_license() no valida.
if os.name == "nt":
    DATA_DIR = Path(os.getenv("APPDATA", str(BASE_DIR))) / "HybridToCloud"
else:
    DATA_DIR = BASE_DIR
os.makedirs(DATA_DIR, exist_ok=True)

BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "Mi Negocio")
BRAND_LOGO = os.environ.get("BRAND_LOGO", "assets/logo.png")

LICENSE_SUPABASE_URL = os.environ.get("LICENSE_SUPABASE_URL", "")
LICENSE_SUPABASE_ANON_KEY = os.environ.get("LICENSE_SUPABASE_ANON_KEY", "")
