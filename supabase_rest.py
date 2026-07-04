"""
supabase_rest.py — Cliente REST para Supabase sin supabase-py.
Soporta requests (preferido) y urllib (fallback stdlib, sin dependencias).
"""
import json
import os
import urllib.request
import urllib.error
import urllib.parse

# --- Configuración ---
# Se lee primero desde config.py, y luego como fallback desde variables de entorno
try:
    from config import SUPABASE_REST_URL as _REST_URL, SUPABASE_ANON_KEY as _ANON_KEY
except Exception:
    _REST_URL = ""
    _ANON_KEY = ""

# SUPABASE_SERVICE_KEY es opcional: si config.py no la expone (versión vieja del
# archivo) o falla el import, seguimos igual que siempre con la anon key.
try:
    from config import SUPABASE_SERVICE_KEY as _SERVICE_KEY
except Exception:
    _SERVICE_KEY = ""

REST_URL = os.environ.get("SUPABASE_REST_URL", _REST_URL) or ""
ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", _ANON_KEY) or ""
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", _SERVICE_KEY) or ""

# Debug sin imprimir secretos
print(f"[SUPABASE REST] REST_URL configurado: {bool(REST_URL)} | ANON_KEY configurado: {bool(ANON_KEY)} | SERVICE_KEY configurado: {bool(SERVICE_KEY)}")

# requests es opcional — urllib es el fallback stdlib
try:
    import requests as _requests
except ImportError:
    _requests = None


def _build_headers() -> dict:
    """
    Headers para escritura (upsert/delete) en este módulo.
    'apikey' siempre es la ANON key (así lo espera PostgREST). 'Authorization'
    usa la SERVICE_KEY si está configurada (escritura elevada); si no, cae a
    la ANON key, que es el comportamiento actual sin cambios.
    """
    write_key = SERVICE_KEY or ANON_KEY
    return {
        "apikey": ANON_KEY,
        "Authorization": f"Bearer {write_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal,resolution=merge-duplicates",
    }


def build_write_headers(extra_prefer: str = None) -> dict:
    """
    Helper reutilizable para que otros módulos (sync_ventas, remote_listener,
    rates_service, etc.) construyan headers de ESCRITURA con el mismo patrón:
    'apikey' = ANON_KEY, 'Authorization' = SERVICE_KEY si existe, si no ANON_KEY.

    extra_prefer: valor opcional para el header 'Prefer' (por defecto
    'return=minimal,resolution=merge-duplicates', igual que _build_headers()).
    """
    write_key = SERVICE_KEY or ANON_KEY
    headers = {
        "apikey": ANON_KEY,
        "Authorization": f"Bearer {write_key}",
        "Content-Type": "application/json",
        "Prefer": extra_prefer or "return=minimal,resolution=merge-duplicates",
    }
    return headers


def _upsert_with_requests(url: str, payload: list) -> bool:
    """Upsert usando la librería requests."""
    try:
        resp = _requests.post(
            url,
            headers=_build_headers(),
            json=payload,
            timeout=30,
        )
        if resp.status_code in (200, 201, 204):
            return True
        print(f"[REST] upsert HTTP {resp.status_code}: {resp.text[:300]}")
        return False
    except Exception as e:
        print(f"[REST] requests exception: {e}")
        return False


def _upsert_with_urllib(url: str, payload: list) -> bool:
    """Upsert usando urllib (stdlib), sin dependencias externas."""
    data = json.dumps(payload).encode("utf-8")
    headers = _build_headers()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.getcode()
            if code in (200, 201, 204):
                return True
            body = resp.read().decode(errors="ignore")
            print(f"[REST] upsert HTTP {code}: {body[:300]}")
            return False
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else ""
        print(f"[REST] HTTPError {e.code}: {body[:300]}")
        return False
    except Exception as e:
        print(f"[REST] urllib exception: {e}")
        return False


_retry_count = 0

def _exponential_backoff(attempt: int) -> float:
    return min(1.5 ** attempt, 15.0)

def upsert_batch_rest(rows: list, table: str = "productos") -> bool:
    """
    Hace upsert de una lista de dicts a la tabla indicada.
    Usa requests si está disponible, si no urllib.
    Reintenta hasta 3 veces con backoff exponencial en caso de error transitorio.
    """
    global _retry_count
    if not REST_URL or not ANON_KEY:
        print("[REST] REST_URL o ANON_KEY no configurados. Skipping.")
        return False

    url = f"{REST_URL.rstrip('/')}/rest/v1/{table}?on_conflict=codigo_interno"

    payload = [
        {
            "codigo_interno":  r.get("CODIGO_INTERNO", r.get("codigo_interno", "")),
            "descripcion":     r.get("DESCRIPCION",    r.get("descripcion", "")),
            "unidad":          r.get("UNIDAD",         r.get("unidad", "")),
            "codigo_barras":   r.get("CODIGO_BARRAS",  r.get("codigo_barras", "")),
            "referencia":      r.get("REFERENCIA",     r.get("referencia", "")),
            "costo":           r.get("COSTO",          r.get("costo", 0.0)),
            "precio_venta":    r.get("PRECIO_VENTA",   r.get("precio_venta", 0.0)),
            "existencia":      r.get("EXISTENCIA",     r.get("existencia", 0.0)),
        }
        for r in rows
    ]

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        if _requests is not None:
            ok = _upsert_with_requests(url, payload)
        else:
            ok = _upsert_with_urllib(url, payload)
        if ok:
            _retry_count = 0
            return True
        if attempt < max_retries:
            delay = _exponential_backoff(attempt)
            print(f"[REST] Reintentando upsert ({attempt}/{max_retries}) en {delay:.0f}s...")
            import time
            time.sleep(delay)
            _retry_count += 1
    _retry_count += 1
    return False


def test_conexion() -> dict:
    """
    Verifica la conexión a la REST de Supabase.
    Devuelve dict con 'ok' (bool) y 'detalle' (str).
    """
    if not REST_URL or not ANON_KEY:
        return {"ok": False, "detalle": "REST_URL o ANON_KEY no configurados"}

    url = f"{REST_URL.rstrip('/')}/rest/v1/productos?limit=1"
    headers = _build_headers()
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            code = resp.getcode()
            body = resp.read().decode(errors="ignore")
            return {"ok": code == 200, "detalle": f"HTTP {code} — {body[:120]}"}
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else ""
        return {"ok": False, "detalle": f"HTTPError {e.code}: {body[:200]}"}
    except Exception as e:
        return {"ok": False, "detalle": str(e)}
def get_row_count_rest(table: str = "productos") -> int:
    """Devuelve el conteo total de filas en la tabla indicada."""
    if not REST_URL or not ANON_KEY:
        return -1
    
    # Usamos Prefer: count=exact para obtener el total en el header 'Content-Range' o similar
    # Pero más fácil: SELECT count(*) vía RPC o query simple
    # Metodo estandar de PostgREST para obtener conteo total sin filas
    url = f"{REST_URL.rstrip('/')}/rest/v1/{table}?select=*"
    headers = _build_headers()
    headers["Range"] = "0-0" 
    headers["Prefer"] = "count=exact"
    
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_range = resp.getheader("Content-Range")
            # El header es '0-0/total'
            if content_range and "/" in content_range:
                return int(content_range.split("/")[-1])
            return -1
    except Exception as e:
        print(f"[REST] Error en get_row_count: {e}")
        return -1

_MIN_SAFE_IDS = 10

def delete_orphans_rest(valid_ids: list, table: str = "productos") -> bool:
    """Elimina filas de la tabla que NO estén en la lista de IDs válidos."""
    if not REST_URL or not ANON_KEY:
        return False
    
    # 🛡️ SALVAGUARDA: si hay menos de MIN_SAFE_IDS IDs válidos, NO eliminar.
    # Esto evita una catástrofe si la unidad H: está caída y el CSV salió vacío.
    if len(valid_ids) < _MIN_SAFE_IDS:
        print(f"[REST] SALVAGUARDA: Solo {len(valid_ids)} IDs válidos (< {_MIN_SAFE_IDS}). "
              f"NO se eliminarán huérfanos para evitar borrado masivo accidental.")
        return False
    
    try:
        # 1. Obtener TODOS los IDs de la nube (con paginacion)
        cloud_ids = set()
        page_size = 1000
        offset = 0
        while True:
            url = f"{REST_URL.rstrip('/')}/rest/v1/{table}?select=codigo_interno&limit={page_size}&offset={offset}"
            headers = _build_headers()
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=30) as resp:
                items = json.loads(resp.read().decode())
                if not items:
                    break
                for item in items:
                    cloud_ids.add(item['codigo_interno'])
                if len(items) < page_size:
                    break
                offset += page_size
        
        print(f"[REST] Cloud IDs obtenidos: {len(cloud_ids)} | CSV IDs validos: {len(valid_ids)}")
        
        # 2. Identificar huerfanos
        valid_set = set(valid_ids)
        orphans = [oid for oid in cloud_ids if oid not in valid_set]
        if orphans:
            print(f"[REST] Huerfanos encontrados: {orphans}")
        
        if not orphans:
            return True
            
        print(f"[REST] Detectados {len(orphans)} productos huerfanos. Eliminando...")
        
        # 3. Eliminar por lotes (PostgREST in filter)
        batch_size = 50 # Menor tamaño para URLs más seguras
        for i in range(0, len(orphans), batch_size):
            batch = orphans[i:i + batch_size]
            # PostgREST requiere que los valores con caracteres especiales estén entrecomillados
            # y que la URL esté codificada.
            quoted_ids = [f'"{oid}"' for oid in batch]
            ids_str = ",".join(quoted_ids)
            
            params = urllib.parse.urlencode({"codigo_interno": f"in.({ids_str})"})
            del_url = f"{REST_URL.rstrip('/')}/rest/v1/{table}?{params}"
            
            print(f"[REST] Borrando batch {i//batch_size + 1}: {len(batch)} items...")
            del_req = urllib.request.Request(del_url, headers=headers, method="DELETE")
            with urllib.request.urlopen(del_req, timeout=20) as resp:
                pass
        return True
    except Exception as e:
        print(f"[REST] Error eliminando huerfanos: {e}")
        return False
