import os
import sys
import time
import json
import csv
import hashlib
import subprocess
from datetime import datetime
from typing import List, Dict

try:
    from config import CSV_SOURCE_PATH, SUPABASE_REST_URL, SUPABASE_ANON_KEY
except ImportError:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    CSV_SOURCE_PATH = os.path.join(base_dir, "MAESTRO_ACTUAL.csv")
    SUPABASE_REST_URL = ""
    SUPABASE_ANON_KEY = ""

from supabase_rest import upsert_batch_rest, get_row_count_rest, delete_orphans_rest
from rates_service import RatesService

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
EXPORTER_SCRIPT = os.path.join(BASE_DIR, "actualizar_inventario.py")
CACHE_FILE = os.path.join(BASE_DIR, "sync_cache.json")
LAST_SYNC_FILE = os.path.join(BASE_DIR, "last_sync.json")

def run_hybrid_exporter():
    print(f"[SYNC] -> Evaluando extracción de inventario...")
    if not os.path.exists(EXPORTER_SCRIPT): return False
    try:
        result = subprocess.run([sys.executable, EXPORTER_SCRIPT], capture_output=True, text=True, check=False)
        return result.returncode == 0
    except: return False

def get_row_hash(row: Dict) -> str:
    relevant_data = f"{row['codigo_interno']}|{row['descripcion']}|{row['costo']:.2f}|{row['precio_venta']:.2f}|{row['existencia']:.2f}|{row['codigo_barras']}|{row['unidad']}"
    return hashlib.md5(relevant_data.encode('utf-8')).hexdigest()

def sync_incremental(force=False):
    if not run_hybrid_exporter(): return

    # Actualizar Tasas
    try:
        service = RatesService()
        rates = service.get_all_rates()
        service.save_to_db(rates)
    except: pass

    # Cargar caché
    cache = {}
    if not force and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f: cache = json.load(f)
        except: pass

    if not os.path.exists(CSV_SOURCE_PATH): return

    # Procesamiento por STREAM
    to_upsert = []
    new_cache = {}
    total_count = 0
    
    print(f"[SYNC] Procesando Inventario (Stream)...")
    try:
        with open(CSV_SOURCE_PATH, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            error_occurred = False
            for row in reader:
                try:
                    costo = float(row.get('COSTO', 0))
                    precio = float(row.get('PRECIO_VENTA', 0))
                    existencia = float(row.get('EXISTENCIA', 0))
                    
                    item = {
                        "codigo_interno": row.get('CODIGO_INTERNO', '').strip(),
                        "descripcion": row.get('DESCRIPCION', '').strip()[:200],
                        "unidad": row.get('UNIDAD', '').strip()[:50],
                        "codigo_barras": row.get('CODIGO_BARRAS', '').strip()[:100],
                        "costo": round(costo, 2), "precio_venta": round(precio, 2), "existencia": round(existencia, 2)
                    }
                    
                    cid = item['codigo_interno']
                    h = get_row_hash(item)
                    new_cache[cid] = h
                    total_count += 1
                    
                    if cache.get(cid) != h:
                        to_upsert.append(item)
                    
                    if len(to_upsert) >= 500:
                        print(f"  -> Upsert batch {len(to_upsert)}...")
                        if upsert_batch_rest(to_upsert): to_upsert = []
                        else: 
                            error_occurred = True
                            break
                except: continue
        
        if error_occurred:
            print("[SYNC] ! Error crítico durante la subida de lotes. Abortando.")
            return

        if to_upsert:
            print(f"  -> Upsert final {len(to_upsert)}...")
            if not upsert_batch_rest(to_upsert):
                print("[SYNC] ! Error en el lote final. Abortando.")
                return

        # Guardar Caché
        with open(CACHE_FILE, 'w') as f: json.dump(new_cache, f)
        
        # Guardar Metadata
        try:
            with open(LAST_SYNC_FILE, "w") as f:
                json.dump({"last_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "timestamp": time.time()}, f)
        except: pass

        print(f"[SYNC] [OK] Sincronización finalizada. Total: {total_count}")
        verify_sync(total_count)

    except Exception as e:
        print(f"[SYNC] Error: {e}")

def verify_sync(csv_count: int):
    cloud_count = get_row_count_rest()
    if cloud_count != -1 and cloud_count != csv_count:
        print(f"[SYNC] ! Discrepancia detectada. Corrigiendo huerfanos...")
        # Nota: Aquí sí cargamos IDs en memoria para el delete_orphans
        try:
            with open(CSV_SOURCE_PATH, mode='r', encoding='utf-8-sig') as f:
                ids = [r['CODIGO_INTERNO'].strip() for r in csv.DictReader(f)]
                if delete_orphans_rest(ids):
                    if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
        except: pass

if __name__ == "__main__":
    from lock_util import acquire_lock
    try:
        set_priority_low()
        with acquire_lock(timeout=120):
            mode = sys.argv[1] if len(sys.argv) > 1 else "once"
            if mode == "force": sync_incremental(force=True)
            else: sync_incremental()
    except Exception as e:
        print(f"[SYNC] ! Error: {e}")
