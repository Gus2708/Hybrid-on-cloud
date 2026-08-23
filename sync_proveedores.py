"""
sync_proveedores.py — Sincronización de proveedores HybridLite -> Supabase.

Extrae el catálogo de proveedores desde el archivo DBISAM `TProveedores.Dat`
(solo lectura, vive en H:\\HybridLite\\...) y hace upsert completo a la tabla
`proveedores` en Supabase vía REST.

Son ~34 filas (catálogo pequeño y estable), por lo que NO se usa cache de
hashes como en `sync.py`: cada corrida sube el listado completo con
`Prefer: resolution=merge-duplicates` (upsert por PK `codigo`).

Uso:
    python sync_proveedores.py
"""
import os
import sys
import time
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone

try:
    from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY, RUTA_PROVEEDORES
except ImportError:
    SUPABASE_REST_URL = ""
    SUPABASE_ANON_KEY = ""
    RUTA_PROVEEDORES = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TProveedores.Dat'

# ==========================================
#         CONFIGURACIÓN
# ==========================================
# (RUTA_PROVEEDORES ahora se importa de config)

_MAX_RETRIES = 3
_RETRY_DELAY = 2  # segundos

# Encabezados para comunicación REST con Supabase (mismo patrón que sync_ajustes.py):
# la service key si está configurada, si no la anon key.
try:
    from supabase_rest import build_write_headers
    HEADERS = build_write_headers(extra_prefer="resolution=merge-duplicates")
except Exception:
    HEADERS = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sync_proveedores")


def _clean_text(val):
    """Normaliza un valor de texto proveniente de DBISAM.

    Los .DAT de HybridLite traen 'Fail' como placeholder de campos vacíos
    (patrón conocido del proyecto). Cualquier valor 'Fail' (exacto) o vacío
    tras strip() se convierte en None.
    """
    if val is None:
        return None
    text = str(val).strip()
    if text == "" or text == "Fail":
        return None
    return text


def _esperar_unidad_h(ruta: str, retries: int = _MAX_RETRIES, delay: int = _RETRY_DELAY) -> bool:
    """Verifica que el archivo .Dat sea accesible, reintentando si la unidad H: no está montada."""
    for attempt in range(1, retries + 1):
        if os.path.exists(ruta):
            return True
        log.warning(
            "[RETRY %d/%d] Unidad H: no disponible o archivo no encontrado: %s",
            attempt, retries, ruta,
        )
        if attempt < retries:
            time.sleep(delay)
    return False


def extraer_proveedores() -> list[dict]:
    """Lee TProveedores.Dat (DBISAM, solo lectura) y devuelve la lista de proveedores saneados."""
    import pydbisam

    if not _esperar_unidad_h(RUTA_PROVEEDORES):
        log.error("Unidad H: no disponible. Abortando extracción de proveedores.")
        return []

    log.info("Leyendo %s...", RUTA_PROVEEDORES)
    db = pydbisam.PyDBISAM(RUTA_PROVEEDORES)
    field_names = db.fields()
    idx_codigo = field_names.index("PRV_CODIGO")
    idx_nombre = field_names.index("PRV_DESCRIPCION")
    idx_rif = field_names.index("PRV_RIF")
    idx_telefono = field_names.index("PRV_TELEFONO")
    idx_contacto = field_names.index("PRV_CONTACTO")
    idx_email = field_names.index("PRV_EMAIL")
    idx_status = field_names.index("PRV_STATUS")

    ahora_iso = datetime.now(timezone.utc).isoformat()

    proveedores = []
    for row in db.rows():
        codigo = _clean_text(row[idx_codigo])
        nombre = _clean_text(row[idx_nombre])

        if not codigo or not nombre:
            log.warning("Fila sin PRV_CODIGO o PRV_DESCRIPCION, se salta: %r", row)
            continue

        proveedores.append({
            "codigo": codigo,
            "nombre": nombre,
            "rif": _clean_text(row[idx_rif]),
            "telefono": _clean_text(row[idx_telefono]),
            "contacto": _clean_text(row[idx_contacto]),
            "email": _clean_text(row[idx_email]),
            "status": bool(row[idx_status]),
            "actualizado_en": ahora_iso,
        })

    del db
    log.info("Extraídos %d proveedores de HybridLite.", len(proveedores))
    return proveedores


def subir_proveedores(rows: list[dict]) -> bool:
    """Hace upsert completo de la lista de proveedores a Supabase vía REST."""
    if not rows:
        log.warning("Lista de proveedores vacía, no se sube nada.")
        return False

    if not SUPABASE_REST_URL or not SUPABASE_ANON_KEY:
        log.error("SUPABASE_REST_URL y/o SUPABASE_ANON_KEY no configurados. Abortando subida.")
        return False

    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/proveedores"
    data = json.dumps(rows).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            ok = resp.getcode() in (200, 201, 204)
            if ok:
                log.info("Upsert de %d proveedores exitoso (HTTP %d).", len(rows), resp.getcode())
            else:
                log.error("Upsert respondió HTTP %d inesperado.", resp.getcode())
            return ok
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else ""
        log.error("Error subiendo proveedores: HTTP %d - %s", e.code, body)
        return False
    except Exception as e:
        log.error("Error subiendo proveedores: %s", e)
        return False


def main() -> int:
    log.info("=== Iniciando sincronización de proveedores (HybridLite -> Supabase) ===")

    proveedores = extraer_proveedores()
    log.info("Total de proveedores extraídos: %d", len(proveedores))

    if not proveedores:
        log.error("No se extrajo ningún proveedor. Sincronización abortada.")
        return 1

    exito = subir_proveedores(proveedores)
    if exito:
        log.info("=== Sincronización de proveedores finalizada con éxito (%d filas) ===", len(proveedores))
        return 0

    log.error("=== Sincronización de proveedores finalizada con errores ===")
    return 1


if __name__ == "__main__":
    sys.exit(main())
