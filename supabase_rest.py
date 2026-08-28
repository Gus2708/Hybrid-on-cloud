import json
import os
import requests
from typing import List, Dict, Optional

# --- Configuración ---
try:
    from config import SUPABASE_REST_URL as _REST_URL, SUPABASE_ANON_KEY as _ANON_KEY
except ImportError:
    _REST_URL = ""
    _ANON_KEY = ""

REST_URL = os.environ.get("SUPABASE_REST_URL", _REST_URL) or ""
ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", _ANON_KEY) or ""

# Debug sin imprimir secretos
print(f"[SUPABASE REST] REST_URL configurado: {bool(REST_URL)} | ANON_KEY configurado: {bool(ANON_KEY)}")

def _build_headers() -> dict:
    return {
        "apikey": ANON_KEY,
        "Authorization": f"Bearer {ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

def upsert_batch_rest(rows: list, table: str = "productos") -> bool:
    """Hace upsert de una lista de dicts a la tabla indicada."""
    if not REST_URL or not ANON_KEY:
        print("[REST] REST_URL o ANON_KEY no configurados. Skipping.")
        return False

    url = f"{REST_URL.rstrip('/')}/rest/v1/{table}?on_conflict=codigo_interno"

    # Normalizar payload
    payload = [
        {
            "codigo_interno":  r.get("CODIGO_INTERNO", r.get("codigo_interno", "")),
            "descripcion":     r.get("DESCRIPCION",    r.get("descripcion", "")),
            "unidad":          r.get("UNIDAD",         r.get("unidad", "")),
            "codigo_barras":   r.get("CODIGO_BARRAS",  r.get("codigo_barras", "")),
            "costo":           float(r.get("COSTO",    r.get("costo", 0.0))),
            "precio_venta":    float(r.get("PRECIO_VENTA", r.get("precio_venta", 0.0))),
            "existencia":      float(r.get("EXISTENCIA", r.get("existencia", 0.0))),
        }
        for r in rows
    ]

    try:
        resp = requests.post(url, headers=_build_headers(), json=payload, timeout=30)
        if resp.status_code in (200, 201, 204):
            return True
        print(f"[REST] upsert HTTP {resp.status_code}: {resp.text[:300]}")
        return False
    except Exception as e:
        print(f"[REST] Exception in upsert: {e}")
        return False

def test_conexion() -> dict:
    """Verifica la conexión a la REST de Supabase."""
    if not REST_URL or not ANON_KEY:
        return {"ok": False, "detalle": "REST_URL o ANON_KEY no configurados"}

    url = f"{REST_URL.rstrip('/')}/rest/v1/productos?limit=1"
    try:
        resp = requests.get(url, headers=_build_headers(), timeout=10)
        return {"ok": resp.status_code == 200, "detalle": f"HTTP {resp.status_code} — {resp.text[:120]}"}
    except Exception as e:
        return {"ok": False, "detalle": str(e)}

def get_row_count_rest(table: str = "productos") -> int:
    """Devuelve el conteo total de filas en la tabla indicada."""
    if not REST_URL or not ANON_KEY: return -1
    
    url = f"{REST_URL.rstrip('/')}/rest/v1/{table}?select=*"
    headers = _build_headers()
    headers["Range"] = "0-0" 
    headers["Prefer"] = "count=exact"
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        content_range = resp.headers.get("Content-Range")
        if content_range and "/" in content_range:
            return int(content_range.split("/")[-1])
        return -1
    except Exception as e:
        print(f"[REST] Error en get_row_count: {e}")
        return -1

def delete_orphans_rest(valid_ids: list, table: str = "productos") -> bool:
    """Elimina filas de la tabla que NO estén en la lista de IDs válidos."""
    if not REST_URL or not ANON_KEY: return False
    
    try:
        # 1. Obtener TODOS los IDs de la nube
        cloud_ids = set()
        page_size = 1000
        offset = 0
        while True:
            url = f"{REST_URL.rstrip('/')}/rest/v1/{table}?select=codigo_interno&limit={page_size}&offset={offset}"
            resp = requests.get(url, headers=_build_headers(), timeout=30)
            items = resp.json()
            if not items: break
            for item in items:
                cloud_ids.add(item['codigo_interno'])
            if len(items) < page_size: break
            offset += page_size
        
        # 2. Identificar huerfanos
        valid_set = set(valid_ids)
        orphans = [oid for oid in cloud_ids if oid not in valid_set]
        
        if not orphans: return True
            
        print(f"[REST] Detectados {len(orphans)} productos huerfanos. Eliminando...")
        
        # 3. Eliminar por lotes
        batch_size = 50 
        for i in range(0, len(orphans), batch_size):
            batch = orphans[i:i + batch_size]
            # Formato PostgREST: in.("id1","id2")
            ids_str = ",".join([f'"{oid}"' for oid in batch])
            del_url = f"{REST_URL.rstrip('/')}/rest/v1/{table}"
            params = {"codigo_interno": f"in.({ids_str})"}
            
            requests.delete(del_url, headers=_build_headers(), params=params, timeout=20)
            
        return True
    except Exception as e:
        print(f"[REST] Error eliminando huerfanos: {e}")
        return False
