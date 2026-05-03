import os
import sys
import time
import json
import csv
import hashlib
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict

# Intentar cargar configuracion
try:
    from config import CSV_SOURCE_PATH, SUPABASE_REST_URL, SUPABASE_ANON_KEY
except ImportError:
    # Ruta local por defecto si falla el import
    base_dir = os.path.dirname(os.path.abspath(__file__))
    CSV_SOURCE_PATH = os.path.join(base_dir, "MAESTRO_ACTUAL.csv")
    SUPABASE_REST_URL = ""
    SUPABASE_ANON_KEY = ""

from supabase_rest import upsert_batch_rest, get_row_count_rest, delete_orphans_rest
from rates_service import RatesService

# Rutas críticas
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Ruta al script que genera el CSV desde HybridLite
EXPORTER_SCRIPT = os.path.join(BASE_DIR, "actualizar_inventario.py")
CACHE_FILE = os.path.join(BASE_DIR, "sync_cache.json")
LAST_SYNC_FILE = os.path.join(BASE_DIR, "last_sync.json")

def run_hybrid_exporter():
    """Ejecuta el script que extrae los datos de HybridLite y genera el CSV."""
    print(f"[SYNC] -> Extrayendo datos frescos de HybridLite (.dat)...")
    if not os.path.exists(EXPORTER_SCRIPT):
        print(f"[SYNC] ! Error: No se encontró el exportador en {EXPORTER_SCRIPT}")
        return False
    
    try:
        # Ejecutamos el exportador de HybridLite
        # Usamos sys.executable para asegurar el mismo entorno
        result = subprocess.run([sys.executable, EXPORTER_SCRIPT], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            print("[SYNC] -> Exportacion de HybridLite exitosa.")
            return True
        else:
            print(f"[SYNC] ! Error en exportador: {result.stderr}")
            return False
    except Exception as e:
        print(f"[SYNC] ! Fallo critico al ejecutar exportador: {e}")
        return False

def get_row_hash(row: Dict) -> str:
    """Genera un hash único basado en los datos críticos del producto."""
    # Usamos valores redondeados para el hash
    relevant_data = f"{row['codigo_interno']}|{row['descripcion']}|{row['costo']:.2f}|{row['precio_venta']:.2f}|{row['existencia']:.2f}|{row['codigo_barras']}|{row['unidad']}"
    return hashlib.md5(relevant_data.encode('utf-8')).hexdigest()

def _load_csv(csv_path: str) -> List[Dict]:
    if not os.path.exists(csv_path):
        print(f"[SYNC] ! No se encontro el CSV en {csv_path}")
        return []
    
    productos = []
    try:
        # El exportador usa encoding utf-8-sig y delimitador COMA (,)
        with open(csv_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f, delimiter=',')
            for row in reader:
                try:
                    # Limpieza y validación de números para evitar Numeric Overflow en Postgres (NUMERIC 20,4)
                    # El límite seguro es 10^15
                    costo = float(row.get('COSTO', 0))
                    if abs(costo) > 1e14: costo = 0.0
                    
                    precio = float(row.get('PRECIO_VENTA', 0))
                    if abs(precio) > 1e14: precio = 0.0
                    
                    existencia = float(row.get('EXISTENCIA', 0))
                    if abs(existencia) > 1e14: existencia = 0.0
                    
                    productos.append({
                        "codigo_interno": row.get('CODIGO_INTERNO', '').strip(),
                        "descripcion": row.get('DESCRIPCION', '').strip()[:200], # Capar longitud
                        "unidad": row.get('UNIDAD', '').strip()[:50],
                        "codigo_barras": row.get('CODIGO_BARRAS', '').strip()[:100],
                        "costo": round(costo, 2),
                        "precio_venta": round(precio, 2),
                        "existencia": round(existencia, 2)
                    })
                except: continue
    except Exception as e:
        print(f"[SYNC] Error procesando CSV: {e}")
    return productos

def sync_incremental(force=False):
    # PASO 1: Generar CSV fresco desde HybridLite
    if not run_hybrid_exporter():
        print("[SYNC] ! Abortando: No se pudo obtener datos de HybridLite.")
        return

    print(f"[SYNC] Iniciando sincronizacion {'COMPLETA' if force else 'INCREMENTAL'}...")
    
    # NUEVO: Actualizar Tasas de Cambio (Tazas)
    try:
        print("[SYNC] -> Actualizando tasas de cambio (BCV/Binance)...")
        service = RatesService()
        rates = service.get_all_rates()
        if service.save_to_db(rates):
            print(f"[SYNC] [OK] Tasas actualizadas: BCV USD {rates['bcv_usd']}")
        else:
            print("[SYNC] ! No se pudieron actualizar las tasas.")
    except Exception as e:
        print(f"[SYNC] ! Error actualizando tasas: {e}")

    # PASO 2: Cargar caché
    cache = {}
    if not force and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                cache = json.load(f)
        except: pass

    # PASO 3: Procesar CSV
    rows = _load_csv(CSV_SOURCE_PATH)
    if not rows:
        print("[SYNC] ! El CSV esta vacio o no se pudo leer.")
        return

    # PASO 4: Detectar cambios
    to_upsert = []
    new_cache = {}
    for row in rows:
        cid = row['codigo_interno']
        h = get_row_hash(row)
        new_cache[cid] = h
        if cache.get(cid) != h:
            to_upsert.append(row)

    print(f"[SYNC] Total: {len(rows)} | Cambios detectados: {len(to_upsert)}")

    if not to_upsert:
        print("[SYNC] [OK] Todo esta al dia en la nube.")
        _save_metadata()
        verify_sync(len(rows)) # Verificar integridad siempre
        return

    # PASO 5: Upsert a Supabase
    success = True
    batch_size = 500
    for i in range(0, len(to_upsert), batch_size):
        batch = to_upsert[i:i + batch_size]
        print(f"[SYNC] Subiendo cambios {i+1} a {min(i+batch_size, len(to_upsert))}...")
        if not upsert_batch_rest(batch):
            success = False; break
    
    if success:
        with open(CACHE_FILE, 'w') as f:
            json.dump(new_cache, f)
        _save_metadata()
        print(f"[SYNC] [OK] Exitoso! {len(to_upsert)} productos actualizados.")
        verify_sync(len(rows))
    else:
        print("[SYNC] ! Fallo al subir datos a Supabase.")

def verify_sync(csv_count: int):
    """Comprueba que el conteo en Supabase coincida con el CSV."""
    print("[SYNC] Verificando integridad de la nube...")
    cloud_count = get_row_count_rest()
    if cloud_count == -1:
        print("[SYNC] ! Advertencia: No se pudo verificar el conteo en la nube (Error de red o API).")
    elif cloud_count == csv_count:
        print(f"[SYNC] [OK] Integridad verificada: CSV({csv_count}) == Nube({cloud_count})")
    else:
        print(f"[SYNC] ! DISCREPANCIA: CSV({csv_count}) vs Nube({cloud_count}). Corrigiendo...")
        # Si hay discrepancia, intentamos corregir eliminando huerfanos
        ids = [r['codigo_interno'] for r in _load_csv(CSV_SOURCE_PATH)]
        if delete_orphans_rest(ids):
            print("[SYNC] [OK] Huerfanos eliminados. La base de datos ahora deberia ser igual al CSV.")
            # Forzamos limpieza de caché para asegurar que todo esté bien
            if os.path.exists(CACHE_FILE):
                try: os.remove(CACHE_FILE)
                except: pass
        else:
            print("[SYNC] ! No se pudieron eliminar los huerfanos.")

def _save_metadata():
    try:
        with open(LAST_SYNC_FILE, "w") as f:
            json.dump({"last_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "timestamp": time.time()}, f)
    except: pass

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    if mode == "force": sync_incremental(force=True)
    else: sync_incremental()
