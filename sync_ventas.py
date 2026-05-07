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
    if not os.path.exists(EXPORTER_SCRIPT): return False
    try:
        result = subprocess.run([sys.executable, EXPORTER_SCRIPT], capture_output=True, text=True, check=False)
        return result.returncode == 0
    except: return False

def upsert_batch(table: str, on_conflict: str, payload: list) -> bool:
    if not payload: return True
    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/{table}?on_conflict={on_conflict}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.getcode() in (200, 201, 204)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")
        print(f"  [ERROR] HTTP {e.code}: {body[:500]}")
        return False
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False

def get_hash(data_dict):
    s = "|".join(str(v) for v in data_dict.values())
    return hashlib.md5(s.encode('utf-8')).hexdigest()

def to_float(val):
    try: return float(val) if val else 0.0
    except: return 0.0

def to_int(val):
    try: return int(float(val)) if val else 0
    except: return 0

def sync_incremental(force=False):
    if not SUPABASE_REST_URL or not SUPABASE_ANON_KEY: return
    if not run_exporter(): return

    # Cargar Caché
    cache = {"clientes": {}, "ventas": {}, "ventas_detalle": {}}
    if not force and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f: cache = json.load(f)
        except: pass

    # Cargar Caché de Productos (desde sync_cache.json)
    productos_cache = {}
    PROD_CACHE_FILE = os.path.join(BASE_DIR, "sync_cache.json")
    if os.path.exists(PROD_CACHE_FILE):
        try:
            with open(PROD_CACHE_FILE, 'r') as f: productos_cache = json.load(f)
        except: pass

    # Mapeos
    def map_cliente(row):
        return {"codigo_cliente": row["CLT_CODIGO"], "nombre": row["CLT_DESCRIPCION"], "rif": row["CLT_RIF"], 
                "telefono": row.get("CLT_TELEFONO", ""), "direccion": row.get("CLT_DIRECCION1", "")}

    def map_venta(row):
        rif = row.get("THT_RIFCLIENTE", "").strip()
        # Validar FK contra el catálogo de clientes (cache contiene los códigos de cliente)
        # Si no existe, usamos None para evitar error 409
        if rif and rif not in cache.get("clientes", {}):
            rif = None
            
        return {"id": int(row["THT_AUTOINCREMENT"]), "documento": row["THT_DOCUMENTO"], 
                "fecha_emision": row["THT_FECHAEMISION"] if row["THT_FECHAEMISION"] else None,
                "rif_cliente": rif if rif else None, 
                "total_neto": to_float(row["THT_TOTALNETO"]),
                "total_impuesto": to_float(row.get("THT_TOTALIMPUESTO", 0)), "status": to_int(row["THT_STATUS"]),
                "numero_control": row["THT_NUMEROCONTROL"]}

    def map_detalle(row):
        try:
            prod = row.get("TBT_CODIGO", "").strip()
            # Validar FK contra el catálogo de productos
            if prod and prod not in productos_cache:
                prod = None
                
            return {"id": int(row["TBT_AUTOINCREMENT"]), "documento": row["TBT_DOCUMENTO"], 
                    "codigo_producto": prod if prod else None,
                    "cantidad": to_float(row["TBT_CANTIDAD"]), "precio_venta": to_float(row["TBT_PRECIODEVENTA"]),
                    "costo_str": row.get("TBT_CTOCOSTOSTR", ""), 
                    "venta_id": int(row["TBT_OPERACION_AUTOINCREMENT"]) if row.get("TBT_OPERACION_AUTOINCREMENT") else None}
        except: return None

    entities = [
        ("clientes", "MAESTRO_CLIENTES.csv", "clientes", "codigo_cliente", map_cliente),
        ("ventas", "VENTAS_CABECERA.csv", "ventas", "id", map_venta),
        ("ventas_detalle", "VENTAS_DETALLE.csv", "ventas_detalle", "id", map_detalle)
    ]

    for key_name, csv_path, table_name, pk_col, map_func in entities:
        if not os.path.exists(csv_path): continue
        print(f"[SYNC VENTAS] Procesando {key_name} (Stream)...")
        
        to_upsert = []
        old_cache = cache.get(key_name, {})
        new_entity_cache = {}
        
        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                count = 0
                error_occurred = False
                for row in reader:
                    mapped = map_func(row)
                    if not mapped or not mapped.get(pk_col): continue
                    pk_val = str(mapped[pk_col])
                    h = get_hash(mapped)
                    new_entity_cache[pk_val] = h
                    if old_cache.get(pk_val) != h:
                        to_upsert.append(mapped)
                    
                    if len(to_upsert) >= 1000:
                        print(f"  -> Subiendo lote de {len(to_upsert)}...")
                        if upsert_batch(table_name, pk_col, to_upsert): 
                            to_upsert = []
                        else: 
                            print(f"  ! Error crítico en lote de {key_name}"); 
                            error_occurred = True
                            break
                    count += 1
                
                if error_occurred:
                    print(f"  [STOP] Deteniendo sincronización de {key_name} por error.")
                    continue

                # Resto final
                if to_upsert:
                    print(f"  -> Subiendo resto de {len(to_upsert)}...")
                    if not upsert_batch(table_name, pk_col, to_upsert):
                        print(f"  ! Error en lote final de {key_name}")
                        continue
                
                # GUARDADO DE CACHÉ SÓLO SI NO HUBO ERRORES
                cache[key_name] = new_entity_cache
                with open(CACHE_FILE, 'w') as cf: json.dump(cache, cf)
                print(f"  [OK] {key_name} al día. ({count} registros procesados)")

        except Exception as e:
            print(f"  ! Error en {key_name}: {e}")

    # Metadata final
    try:
        with open(LAST_SYNC_FILE, "w") as f:
            json.dump({"last_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "timestamp": time.time()}, f)
    except: pass

if __name__ == "__main__":
    from lock_util import acquire_lock
    try:
        set_priority_low()
        with acquire_lock(timeout=120):
            mode = sys.argv[1] if len(sys.argv) > 1 else "once"
            sync_incremental(force=(mode == "force"))
    except Exception as e:
        print(f"[SYNC VENTAS] ! Error: {e}")
