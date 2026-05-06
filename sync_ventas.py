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
    print("[SYNC VENTAS] -> Extrayendo datos frescos de ventas (.dat)...")
    if not os.path.exists(EXPORTER_SCRIPT):
        print(f"[SYNC VENTAS] ! Error: No se encontró {EXPORTER_SCRIPT}")
        return False
    try:
        result = subprocess.run([sys.executable, EXPORTER_SCRIPT], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return True
        print(f"[SYNC VENTAS] ! Error en exportador: {result.stderr}")
        return False
    except Exception as e:
        print(f"[SYNC VENTAS] ! Fallo critico: {e}")
        return False

def upsert_batch(table: str, on_conflict: str, payload: list) -> bool:
    if not payload: return True
    if on_conflict:
        url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/{table}?on_conflict={on_conflict}"
    else:
        url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/{table}"

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.getcode() in (200, 201, 204):
                return True
            print(f"[REST] Error {resp.getcode()}: {resp.read().decode(errors='ignore')}")
            return False
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else ""
        print(f"[REST] HTTPError {e.code}: {body}")
        return False
    except Exception as e:
        print(f"[REST] Exception: {e}")
        return False

def get_hash(data_dict):
    """Genera un hash MD5 de los valores del diccionario"""
    s = "|".join(str(v) for v in data_dict.values())
    return hashlib.md5(s.encode('utf-8')).hexdigest()

def to_float(val):
    try: return float(val) if val else 0.0
    except: return 0.0

def to_int(val):
    try: return int(float(val)) if val else 0
    except: return 0

def sync_entity(entity_name, csv_path, table_name, pk_col, map_func):
    """Sincroniza una entidad genérica leyendo su CSV y comparando hashes."""
    print(f"\n[SYNC VENTAS] Procesando {entity_name}...")
    if not os.path.exists(csv_path):
        print(f"  ! Archivo {csv_path} no encontrado.")
        return {}, False

    cache = {}
    new_cache = {}
    to_upsert = []

    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        print(f"  ! Error leyendo {csv_path}: {e}")
        return {}, False

    # Transformar a formato de Supabase
    transformed_rows = []
    for row in rows:
        try:
            mapped = map_func(row)
            if mapped and mapped.get(pk_col):
                transformed_rows.append(mapped)
        except Exception as e:
            continue

    # Cargar caché específico para esta entidad si no se maneja arriba
    return transformed_rows, True


def sync_incremental(force=False):
    if not SUPABASE_REST_URL or not SUPABASE_ANON_KEY:
        print("[SYNC VENTAS] ! Faltan credenciales de Supabase.")
        return

    if not run_exporter():
        print("[SYNC VENTAS] ! Abortando sincronización.")
        return

    # Cargar Caché
    cache = {"clientes": {}, "ventas": {}, "ventas_detalle": {}}
    if not force and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                cache = json.load(f)
        except: pass

    # Funciones de mapeo
    def map_cliente(row):
        return {
            "codigo_cliente": row["CLT_CODIGO"],
            "nombre": row["CLT_DESCRIPCION"],
            "rif": row["CLT_RIF"],
            "telefono": row.get("CLT_TELEFONO", ""),
            "direccion": row.get("CLT_DIRECCION1", "")
        }

    def map_venta(row):
        return {
            "id": int(row["THT_AUTOINCREMENT"]),
            "documento": row["THT_DOCUMENTO"],
            "fecha_emision": row["THT_FECHAEMISION"] if row["THT_FECHAEMISION"] else None,
            "rif_cliente": row.get("THT_RIFCLIENTE", ""),
            "total_neto": to_float(row["THT_TOTALNETO"]),
            "total_impuesto": to_float(row.get("THT_TOTALIMPUESTO", 0)),
            "status": to_int(row["THT_STATUS"]),
            "numero_control": row["THT_NUMEROCONTROL"]
        }

    def map_detalle(row):
        try:
            return {
                "id": int(row["TBT_AUTOINCREMENT"]),
                "documento": row["TBT_DOCUMENTO"],
                "codigo_producto": row["TBT_CODIGO"],
                "cantidad": to_float(row["TBT_CANTIDAD"]),
                "precio_venta": to_float(row["TBT_PRECIODEVENTA"]),
                "costo_str": row.get("TBT_CTOCOSTOSTR", ""),
                "venta_id": int(row["TBT_OPERACION_AUTOINCREMENT"]) if row.get("TBT_OPERACION_AUTOINCREMENT") else None
            }
        except:
            return None

    entities = [
        ("clientes", "MAESTRO_CLIENTES.csv", "clientes", "codigo_cliente", map_cliente),
        ("ventas", "VENTAS_CABECERA.csv", "ventas", "id", map_venta),
        ("ventas_detalle", "VENTAS_DETALLE.csv", "ventas_detalle", "id", map_detalle)
    ]

    new_cache = {"clientes": {}, "ventas": {}, "ventas_detalle": {}}
    all_success = True

    for key_name, csv_path, table_name, pk_col, map_func in entities:
        print(f"\n[SYNC VENTAS] Evaluando {key_name}...")
        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        except Exception as e:
            print(f"  ! Error leyendo {csv_path}: {e}")
            all_success = False
            continue

        to_upsert = []
        old_cache = cache.get(key_name, {})

        for row in rows:
            mapped = map_func(row)
            if not mapped or not mapped.get(pk_col):
                continue
            pk_val = str(mapped[pk_col])
            h = get_hash(mapped)
            new_cache[key_name][pk_val] = h
            if old_cache.get(pk_val) != h:
                to_upsert.append(mapped)

        print(f"  -> Total locales: {len(rows)} | Cambios detectados: {len(to_upsert)}")

        if to_upsert:
            # Batch upsert
            success = True
            batch_size = 1000
            for i in range(0, len(to_upsert), batch_size):
                batch = to_upsert[i:i + batch_size]
                if not upsert_batch(table_name, pk_col, batch):
                    success = False
                    all_success = False
                    break
                print(f"    Subidos {min(i+batch_size, len(to_upsert))}/{len(to_upsert)}")
            if success:
                print(f"  [OK] {len(to_upsert)} registros actualizados en Supabase.")
        else:
            print(f"  [OK] Sin cambios.")

    if all_success:
        with open(CACHE_FILE, 'w') as f:
            json.dump(new_cache, f)
        
        try:
            with open(LAST_SYNC_FILE, "w") as f:
                json.dump({"last_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "timestamp": time.time()}, f)
        except: pass
        print("\n[SYNC VENTAS] Sincronización Incremental Finalizada con Éxito.")
    else:
        print("\n[SYNC VENTAS] Sincronización finalizó con errores. La caché no se actualizó completamente.")

if __name__ == "__main__":
    from lock_util import acquire_lock
    
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    try:
        with acquire_lock(timeout=120):
            if mode == "force": sync_incremental(force=True)
            else: sync_incremental()
    except TimeoutError as e:
        print(f"[SYNC VENTAS] ! Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[SYNC VENTAS] ! Fallo inesperado: {e}")
        sys.exit(1)
