import os
import sys
import csv
import json
import hashlib
import time
import subprocess
import urllib.request
import urllib.error
from datetime import datetime

try:
    from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY
except ImportError:
    SUPABASE_REST_URL = ""
    SUPABASE_ANON_KEY = ""

def set_priority_low():
    """Establece prioridad baja para no impactar el rendimiento de Windows."""
    if sys.platform == "win32":
        try:
            import win32api, win32process, win32con
            pid = win32api.GetCurrentProcessId()
            handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, True, pid)
            win32process.SetPriorityClass(handle, win32process.BELOW_NORMAL_PRIORITY_CLASS)
        except: pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORTER_SCRIPT = os.path.join(BASE_DIR, "extraer_ventas.py")
CACHE_FILE = os.path.join(BASE_DIR, "ventas_cache.json")
LAST_SYNC_FILE = os.path.join(BASE_DIR, "ventas_last_sync.json")

HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",
}

def run_exporter():
    print("[SYNC VENTAS] -> Evaluando extracción selectiva...")
    if not os.path.exists(EXPORTER_SCRIPT):
        print(f"[SYNC VENTAS] ! Script no encontrado: {EXPORTER_SCRIPT}")
        return False
    try:
        result = subprocess.run(
            [sys.executable, EXPORTER_SCRIPT],
            capture_output=True, text=True, timeout=45,
            creationflags=0x08000000
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                print(f"  {line}")
            return True
        else:
            print(f"[SYNC VENTAS] ! Error en exportador (código {result.returncode}):")
            for line in result.stderr.splitlines():
                print(f"  ! {line}")
            return False
    except subprocess.TimeoutExpired:
        print(f"[SYNC VENTAS] ! TIMEOUT (45s): exportador colgado en H:. Abortando.")
        return False
    except Exception as e:
        print(f"[SYNC VENTAS] ! Error ejecutando exportador: {e}")
        return False

def _exponential_backoff(attempt: int) -> float:
    return min(1.5 ** attempt, 15.0)

def upsert_batch(table: str, on_conflict: str, payload: list) -> bool:
    if not payload: return True
    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/{table}?on_conflict={on_conflict}"
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(1, 4):
        req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return resp.getcode() in (200, 201, 204)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="ignore")
            print(f"  [ERROR] HTTP {e.code}: {body[:200]}")
        except Exception as e:
            print(f"  [ERROR] {e}")
        if attempt < 3:
            delay = _exponential_backoff(attempt)
            print(f"  [RETRY] Upsert {table} ({attempt}/3) en {delay:.0f}s...")
            time.sleep(delay)
    return False

def get_hash(data_dict):
    s = "|".join(str(v) for v in data_dict.values())
    return hashlib.md5(s.encode('utf-8')).hexdigest()

# Tasa de cambio promedio para el periodo de Mayo (ajustado según reporte Hybrid)
FACTOR_USD = 489.55

def safe_decimal(val):
    if val is None: return 0.0
    s = str(val).replace('Bs.', '').replace(' ', '').strip()
    if not s: return 0.0
    # Manejar formato venezolano "1.500,50" -> 1500.50
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')
    try: return float(s)
    except: return 0.0

def to_float(val):
    return safe_decimal(val)

def to_int(val):
    try: return int(float(val)) if val else 0
    except: return 0

def upsert_with_response(table: str, on_conflict: str, payload: list) -> list:
    """Upsert y devuelve los registros creados/actualizados (incluyendo IDs)."""
    if not payload: return []
    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/{table}?on_conflict={on_conflict}"
    headers = HEADERS.copy()
    headers["Prefer"] = "return=representation,resolution=merge-duplicates"
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(1, 4):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  [ERROR UPSERT] {e}")
            if attempt < 3:
                delay = _exponential_backoff(attempt)
                print(f"  [RETRY] Upsert {table} con respuesta ({attempt}/3) en {delay:.0f}s...")
                time.sleep(delay)
    return []

def sync_incremental(force=False):
    if not SUPABASE_REST_URL or not SUPABASE_ANON_KEY: return
    if not run_exporter(): return

    # ─── Validar CSV antes de procesar ─────────────────────────────────────
    def validate_csv(path, min_rows=5):
        if not os.path.exists(path):
            print(f"  [SKIP] {path} no existe.")
            return False
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if len(rows) < min_rows:
                    print(f"  [SKIP] {path} tiene solo {len(rows)} filas (< {min_rows}). Posible truncado.")
                    return False
                return True
        except Exception as e:
            print(f"  [ERROR] {path} corrupto: {e}")
            return False

    # Cargar Caché
    cache = {"clientes": {}, "ventas": {}, "ventas_detalle": {}}
    if not force and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f: cache = json.load(f)
        except: pass

    # Mapeos
    def map_cliente(row):
        return {"codigo_cliente": row["CLT_CODIGO"], "nombre": row["CLT_DESCRIPCION"], "rif": row["CLT_RIF"], 
                "telefono": row.get("CLT_TELEFONO", ""), "direccion": row.get("CLT_DIRECCION1", "")}

    def map_venta(row):
        rif = row.get("THT_RIFCLIENTE", "").strip()
        
        # 🔑 Tasa de cambio de la factura (crucial para Bug #2)
        tasa_doc = safe_decimal(row.get("THT_FACTORREFERENCIAL", 0))
        if tasa_doc <= 1.0: 
            # Fallback a tasa BCV si no viene en la factura
            tasa_doc = FACTOR_USD
        
        neto_ves = safe_decimal(row["THT_TOTALNETO"])
        imp_ves = safe_decimal(row.get("THT_TOTALIMPUESTO", 0))
        bruto_ves = safe_decimal(row.get("THT_TOTALBRUTO", 0))
        if bruto_ves == 0: bruto_ves = neto_ves - imp_ves

        # Conversión a USD
        neto_usd = neto_ves / tasa_doc
        impuesto_usd = imp_ves / tasa_doc
        bruto_usd = bruto_ves / tasa_doc

        # ID Único de HybridLite (Bug #5)
        id_unico = to_int(row.get("THT_IDUNICO"))
        if id_unico == 0: id_unico = to_int(row["THT_AUTOINCREMENT"]) # Fallback

        return {
            "id_unico": id_unico,
            "documento": row["THT_DOCUMENTO"].zfill(8), 
            "fecha_emision": row["THT_FECHAEMISION"] if row["THT_FECHAEMISION"] else None,
            "rif_cliente": rif if rif else None, 
            "total_neto": round(neto_usd, 4),
            "total_impuesto": round(impuesto_usd, 4),
            "total_bruto": round(bruto_usd, 4), # Bug #3
            "status": to_int(row["THT_STATUS"]),
            "numero_control": row["THT_NUMEROCONTROL"],
            "metodo_pago": row.get("METODO_PAGO", "EFECTIVO"),
            "created_at": row.get("FECHA_HORA_COMPLETA") # Bug #5 (Time)
        }

    # 1. Clientes
    if validate_csv("MAESTRO_CLIENTES.csv"):
        print("[SYNC VENTAS] Procesando clientes...")
        to_upsert = []
        old_cache = cache.get("clientes", {})
        new_entity_cache = {}
        with open("MAESTRO_CLIENTES.csv", "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try:
                    mapped = map_cliente(row)
                    pk = mapped["codigo_cliente"]
                    h = get_hash(mapped)
                    new_entity_cache[pk] = h
                    if old_cache.get(pk) != h: to_upsert.append(mapped)
                    if len(to_upsert) >= 500:
                        upsert_batch("clientes", "codigo_cliente", to_upsert)
                        to_upsert = []
                except: continue
            if to_upsert: upsert_batch("clientes", "codigo_cliente", to_upsert)
            cache["clientes"] = new_entity_cache

    # 2. Ventas (Cabecera)
    ventas_map_ids = {}
    doc_to_tasa = {}
    
    if validate_csv("VENTAS_CABECERA.csv"):
        print("[SYNC VENTAS] Procesando ventas (Cabeceras)...")
        to_upsert = []
        old_cache = cache.get("ventas", {})
        new_entity_cache = {}
        
        with open("VENTAS_CABECERA.csv", "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try:
                    local_id = row["THT_AUTOINCREMENT"]
                    doc_num = row["THT_DOCUMENTO"].strip().zfill(8)
                    tasa = safe_decimal(row.get("THT_FACTORREFERENCIAL", FACTOR_USD))
                    if tasa <= 1.0: tasa = FACTOR_USD
                    doc_to_tasa[doc_num] = tasa
                    
                    mapped = map_venta(row)
                    pk = str(mapped["id_unico"])
                    h = get_hash(mapped)
                    new_entity_cache[pk] = h
                    
                    to_upsert.append((local_id, mapped))
                    
                    if len(to_upsert) >= 500:
                        payload = [item[1] for item in to_upsert]
                        results = upsert_with_response("ventas", "id_unico", payload)
                        for i, res in enumerate(results):
                            lid = to_upsert[i][0]
                            ventas_map_ids[lid] = res["id"]
                        to_upsert = []
                except: continue
            
            if to_upsert:
                payload = [item[1] for item in to_upsert]
                results = upsert_with_response("ventas", "id_unico", payload)
                for i, res in enumerate(results):
                    lid = to_upsert[i][0]
                    ventas_map_ids[lid] = res["id"]
            
            cache["ventas"] = new_entity_cache

    # 3. Ventas Detalle
    if validate_csv("VENTAS_DETALLE.csv"):
        print("[SYNC VENTAS] Procesando ventas (Detalles)...")
        to_upsert = []
        old_cache = cache.get("ventas_detalle", {})
        new_entity_cache = {}
        
        with open("VENTAS_DETALLE.csv", "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try:
                    doc_num = row["TBT_DOCUMENTO"].strip().zfill(8)
                    tasa = doc_to_tasa.get(doc_num, FACTOR_USD)
                    
                    local_parent_id = row.get("TBT_OPERACION_AUTOINCREMENT")
                    cloud_parent_id = ventas_map_ids.get(local_parent_id)
                    
                    precio_ves = safe_decimal(row["TBT_PRECIODEVENTA"])
                    precio_usd = precio_ves / tasa
                    
                    mapped = {
                        "id": to_int(row["TBT_AUTOINCREMENT"]),
                        "documento": doc_num,
                        "codigo_producto": row.get("TBT_CODIGO", "").strip(),
                        "cantidad": safe_decimal(row["TBT_CANTIDAD"]),
                        "precio_venta": round(precio_usd, 4),
                        "costo_str": row.get("TBT_CTOCOSTOSTR", ""),
                        "venta_id": cloud_parent_id
                    }
                    
                    pk = str(mapped["id"])
                    h = get_hash(mapped)
                    new_entity_cache[pk] = h
                    if old_cache.get(pk) != h: to_upsert.append(mapped)
                    
                    if len(to_upsert) >= 1000:
                        upsert_batch("ventas_detalle", "id", to_upsert)
                        to_upsert = []
                except: continue
            
            if to_upsert: upsert_batch("ventas_detalle", "id", to_upsert)
            cache["ventas_detalle"] = new_entity_cache

    # Guardar Caché Final
    with open(CACHE_FILE, 'w') as cf: json.dump(cache, cf)
    print("[SYNC VENTAS] [OK] Sincronización finalizada.")
    
    # Metadata final
    try:
        with open(LAST_SYNC_FILE, "w") as f:
            json.dump({"last_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "timestamp": time.time()}, f)
    except: pass
    
    # 🔍 RECONCILIACIÓN AUTOMÁTICA (Audit)
    # Solo si no hubo errores críticos y estamos en modo completo
    reconcile_ventas()

_MIN_SAFE_IDS = 10

def reconcile_ventas():
    """Busca registros en Supabase que ya no existen en los CSV locales y los elimina."""
    try:
        # 1. Reconciliar VENTAS (Cabecera) usando id_unico
        if os.path.exists("VENTAS_CABECERA.csv"):
            print("[AUDIT] Verificando integridad de Ventas...")
            with open("VENTAS_CABECERA.csv", "r", encoding="utf-8-sig") as f:
                local_ids = {int(row["THT_IDUNICO"]) for row in csv.DictReader(f) if row.get("THT_IDUNICO")}
            
            # 🛡️ No reconciliar si hay muy pocos IDs (H: caída protege datos en nube)
            if len(local_ids) < _MIN_SAFE_IDS:
                print(f"  [SKIP] Solo {len(local_ids)} IDs locales en ventas (< {_MIN_SAFE_IDS}). "
                      f"Posible unidad H: caída. No se eliminarán registros remotos.")
            elif delete_orphans_generic("ventas", "id_unico", list(local_ids)):
                print("[AUDIT] Reconciliación de Ventas completada.")

        # 2. Reconciliar DETALLES usando id (HybridLite autoincrement)
        if os.path.exists("VENTAS_DETALLE.csv"):
            print("[AUDIT] Verificando integridad de Detalles...")
            with open("VENTAS_DETALLE.csv", "r", encoding="utf-8-sig") as f:
                local_ids = {int(row["TBT_AUTOINCREMENT"]) for row in csv.DictReader(f)}
            
            if len(local_ids) < _MIN_SAFE_IDS:
                print(f"  [SKIP] Solo {len(local_ids)} IDs locales en detalle (< {_MIN_SAFE_IDS}). "
                      f"Posible unidad H: caída. No se eliminarán registros remotos.")
            elif delete_orphans_generic("ventas_detalle", "id", list(local_ids)):
                print("[AUDIT] Reconciliación de Detalles completada.")
    except Exception as e:
        print(f"[AUDIT] Error: {e}")

def _retry_http(url: str, method: str = "GET", data: bytes = None, timeout: int = 30, headers: dict = None) -> object:
    """Ejecuta HTTP request con 3 reintentos y backoff. Devuelve response o None."""
    if headers is None: headers = HEADERS
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            return urllib.request.urlopen(req, timeout=timeout)
        except Exception as e:
            print(f"  [RETRY {method} {url.split('/')[-1]}] ({attempt}/3): {str(e)[:80]}")
            if attempt < 3:
                time.sleep(_exponential_backoff(attempt))
    return None

def delete_orphans_generic(table: str, pk_col: str, valid_ids: list) -> bool:
    """Elimina registros huérfanos de cualquier tabla con reintentos."""
    try:
        cloud_ids = set()
        page_size = 1000
        offset = 0
        while True:
            url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/{table}?select={pk_col}&limit={page_size}&offset={offset}"
            resp = _retry_http(url, timeout=30)
            if resp is None:
                print(f"  [ERROR] No se pudieron obtener IDs de {table} tras reintentos.")
                return False
            items = json.loads(resp.read().decode())
            if not items: break
            for item in items:
                val = item.get(pk_col)
                if val is not None:
                    cloud_ids.add(int(val))
            if len(items) < page_size: break
            offset += page_size

        valid_set = {int(vid) for vid in valid_ids}
        orphans = [oid for oid in cloud_ids if oid not in valid_set]

        if not orphans:
            print(f"  [OK] No se detectaron huérfanos en {table}.")
            return True

        print(f"  [!] Detectados {len(orphans)} registros huérfanos en {table}. Eliminando...")
        batch_size = 100
        for i in range(0, len(orphans), batch_size):
            batch = orphans[i:i + batch_size]
            ids_str = ",".join(map(str, batch))
            del_url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/{table}?{pk_col}=in.({ids_str})"
            _retry_http(del_url, method="DELETE", timeout=20)
        return True
    except Exception as e:
        print(f"  [ERROR AUDIT] {table}: {e}")
        return False

if __name__ == "__main__":
    from lock_util import acquire_lock
    try:
        set_priority_low()
        with acquire_lock(timeout=120):
            mode = sys.argv[1] if len(sys.argv) > 1 else "once"
            sync_incremental(force=(mode == "force"))
    except Exception as e:
        print(f"[SYNC VENTAS] ! Error: {e}")
