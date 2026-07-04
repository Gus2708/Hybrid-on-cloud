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
from sync_utils import safe_decimal, set_priority_low, _kill_proc

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORTER_SCRIPT = os.path.join(BASE_DIR, "actualizar_inventario.py")
CACHE_FILE = os.path.join(BASE_DIR, "sync_cache.json")
LAST_SYNC_FILE = os.path.join(BASE_DIR, "last_sync.json")

def run_hybrid_exporter(force=False):
    print(f"[SYNC] -> Evaluando extracción de inventario...")
    if not os.path.exists(EXPORTER_SCRIPT):
        print(f"[SYNC] ! Script no encontrado: {EXPORTER_SCRIPT}")
        return False
    args = [sys.executable, EXPORTER_SCRIPT]
    if force:
        args.append("force")
    proc = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=0x08000000
    )
    try:
        stdout, stderr = proc.communicate(timeout=120)
        if proc.returncode == 0:
            for line in stdout.decode('utf-8', errors='replace').splitlines():
                try: print(f"  {line}")
                except: pass
            return True
        else:
            print(f"[SYNC] ! Error en exportador (código {proc.returncode}):")
            for line in stderr.decode('utf-8', errors='replace').splitlines():
                try: print(f"  ! {line}")
                except: pass
            return False
    except subprocess.TimeoutExpired:
        _kill_proc(proc)
        print(f"[SYNC] ! TIMEOUT (120s): exportador colgado en H:. Abortando sync.")
        return False
    except Exception as e:
        _kill_proc(proc)
        print(f"[SYNC] ! Error ejecutando exportador: {e}")
        return False

def _load_csv(file_path: str) -> List[Dict]:
    rows = []
    if not os.path.exists(file_path):
        return rows
    try:
        with open(file_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    costo = safe_decimal(row.get('COSTO', 0))
                    precio = safe_decimal(row.get('PRECIO_VENTA', 0))
                    existencia = safe_decimal(row.get('EXISTENCIA', 0))
                    item = {
                        "codigo_interno": row.get('CODIGO_INTERNO', '').strip(),
                        "descripcion": row.get('DESCRIPCION', '').strip()[:200],
                        "unidad": row.get('UNIDAD', '').strip()[:50],
                        "codigo_barras": row.get('CODIGO_BARRAS', '').strip()[:100],
                        "referencia": row.get('REFERENCIA', '').strip()[:100],
                        "costo": round(costo, 2),
                        "precio_venta": round(precio, 2),
                        "existencia": round(existencia, 2)
                    }
                    rows.append(item)
                except:
                    continue
    except: pass
    return rows

def get_row_hash(row: Dict) -> str:
    relevant_data = f"{row.get('codigo_interno', '')}|{row.get('descripcion', '')}|{row.get('costo', 0.0):.2f}|{row.get('precio_venta', 0.0):.2f}|{row.get('existencia', 0.0):.2f}|{row.get('codigo_barras', '')}|{row.get('referencia', '')}|{row.get('unidad', '')}"
    return hashlib.md5(relevant_data.encode('utf-8')).hexdigest()

def sync_incremental(force=False):
    """Sincroniza inventario a Supabase. Devuelve True si terminó completo, False si abortó."""
    # Validar unidad H: antes de empezar
    try:
        from config import RUTA_INVENTARIO
        from network_util import check_drive
        if not check_drive(os.path.dirname(RUTA_INVENTARIO)):
            print("[SYNC] ! ERROR: Unidad de red H: no accesible. Abortando.")
            return False
    except Exception as e:
        print(f"[SYNC] ! No se pudo verificar unidad H:: {e}")
        # Continuar — run_hybrid_exporter fallará si H: está caída

    result = run_hybrid_exporter(force=force)
    if result is False:
        print("[SYNC] Extracción fallida (unidad de red probablemente caída). Abortando sync.")
        return False


    # Actualizar Tasas
    try:
        last_rates_time = 0.0
        if os.path.exists(LAST_SYNC_FILE):
            try:
                with open(LAST_SYNC_FILE, 'r') as f:
                    last_rates_time = json.load(f).get("last_rates_update", 0.0)
            except: pass
        
        now_time = time.time()
        if force or (now_time - last_rates_time >= 3600):
            print("[SYNC] Actualizando tasas de cambio...")
            service = RatesService()
            rates = service.get_all_rates()
            if service.save_to_db(rates):
                try:
                    meta = {}
                    if os.path.exists(LAST_SYNC_FILE):
                        with open(LAST_SYNC_FILE, 'r') as f: meta = json.load(f)
                    meta["last_rates_update"] = now_time
                    with open(LAST_SYNC_FILE, 'w') as f: json.dump(meta, f)
                except: pass
        else:
            print("[SYNC] Tasas de cambio actualizadas recientemente. Saltando.")
    except Exception as e:
        print(f"[SYNC] Error en tasas: {e}")

    # Cargar caché
    cache = {}
    if not force and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f: cache = json.load(f)
        except: pass

    rows = _load_csv(CSV_SOURCE_PATH)
    if not rows:
        print("[SYNC] ! CSV vacío o ilegible. Abortando.")
        return False

    to_upsert = []
    new_cache = {}
    total_count = 0
    zero_price_count = 0
    error_occurred = False

    print(f"[SYNC] Procesando Inventario ({len(rows)} productos)...")
    try:
        for item in rows:
            try:
                costo = item["costo"]
                precio = item["precio_venta"]
                existencia = item["existencia"]
                
                if precio == 0: zero_price_count += 1
                
                cid = item['codigo_interno']
                h = get_row_hash(item)
                new_cache[cid] = h
                total_count += 1
                
                if cache.get(cid) != h:
                    to_upsert.append(item)
                
                if len(to_upsert) >= 500:
                    # Salvaguarda: si mas del 50% de lo procesado tiene precio 0, abortar
                    if total_count > 100 and zero_price_count > total_count * 0.5:
                        print(f"[SYNC] ! ABORTANDO: {zero_price_count}/{total_count} productos con precio 0. Posible error de lectura.")
                        error_occurred = True
                        break
                    
                    print(f"  -> Upsert batch {len(to_upsert)}...")
                    if upsert_batch_rest(to_upsert): to_upsert = []
                    else: 
                        error_occurred = True
                        break
            except: continue
        
        if error_occurred:
            print("[SYNC] ! Error crítico durante la subida de lotes. Abortando.")
            return False

        if to_upsert:
            print(f"  -> Upsert final {len(to_upsert)}...")
            if not upsert_batch_rest(to_upsert):
                print("[SYNC] ! Error en el lote final. Abortando.")
                return False

        # Guardar Caché
        with open(CACHE_FILE, 'w') as f: json.dump(new_cache, f)
        
        # Guardar Metadata
        try:
            meta = {}
            if os.path.exists(LAST_SYNC_FILE):
                try:
                    with open(LAST_SYNC_FILE, 'r') as f: meta = json.load(f)
                except: pass
            meta.update({
                "last_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": time.time()
            })
            with open(LAST_SYNC_FILE, "w") as f:
                json.dump(meta, f)
        except: pass

        print(f"[SYNC] [OK] Sincronización finalizada. Total: {total_count}")
        verify_sync(total_count, force=force)

        # Sincronizar movimientos locales (ajustes y compras) a Supabase via pydbisam
        try:
            from sync_ajustes import sync_movimientos_locales
            sync_movimientos_locales(force=force)
            print("[SYNC] Sincronización de ajustes/compras completada.")
        except ImportError as e:
            print(f"[SYNC] sync_ajustes no disponible (¿pydbisam instalado?): {e}")
        except Exception as e:
            print(f"[SYNC] Error en sincronización de ajustes: {e}")

        return True

    except Exception as e:
        print(f"[SYNC] Error: {e}")
        return False

def verify_sync(csv_count: int, force: bool = False):
    cloud_count = get_row_count_rest()
    if cloud_count != -1 and cloud_count != csv_count:
        diff = abs(cloud_count - csv_count)
        # 🛡️ No corregir si la diferencia es >10% del total — probablemente H: caída
        max_count = max(cloud_count, csv_count)
        if max_count > 100 and diff / max_count > 0.10:
            msg = (f"Diferencia grande ({diff} filas, {diff/max_count*100:.1f}%). "
                   f"Probablemente la unidad H: estaba caída. No se corrigen huérfanos.")
            print(f"[SYNC] {msg}")
            try:
                from alert_util import send_alert
                send_alert("warning", msg)
            except Exception:
                pass
            return
        
        # Verificar cooldown de reconciliación (12 horas)
        last_reconcile = 0.0
        if os.path.exists(LAST_SYNC_FILE):
            try:
                with open(LAST_SYNC_FILE, 'r') as f:
                    last_reconcile = json.load(f).get("last_reconcile", 0.0)
            except: pass
        
        now = time.time()
        if not force and (now - last_reconcile < 12 * 3600):
            print(f"[SYNC] Discrepancia detectada ({diff} filas), pero la última reconciliación fue hace menos de 12 horas. Saltando reconciliación de huérfanos.")
            return
            
        msg = f"Discrepancia detectada ({diff} filas). Corrigiendo huérfanos..."
        print(f"[SYNC] {msg}")
        try:
            from alert_util import send_alert
            send_alert("warning", msg)
        except Exception:
            pass
        try:
            with open(CSV_SOURCE_PATH, mode='r', encoding='utf-8-sig') as f:
                ids = [r['CODIGO_INTERNO'].strip() for r in csv.DictReader(f)]
                if delete_orphans_rest(ids):
                    # Actualizar metadata con el timestamp de la última reconciliación exitosa
                    try:
                        meta = {}
                        if os.path.exists(LAST_SYNC_FILE):
                            with open(LAST_SYNC_FILE, 'r') as f: meta = json.load(f)
                        meta["last_reconcile"] = now
                        with open(LAST_SYNC_FILE, 'w') as f: json.dump(meta, f)
                    except: pass
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
