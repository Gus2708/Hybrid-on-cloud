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

from sync_utils import safe_decimal, set_priority_low, _kill_proc, exponential_backoff

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORTER_SCRIPT = os.path.join(BASE_DIR, "extraer_ventas.py")
CACHE_FILE = os.path.join(BASE_DIR, "ventas_cache.json")
LAST_SYNC_FILE = os.path.join(BASE_DIR, "ventas_last_sync.json")

# HEADERS de escritura: usa SUPABASE_SERVICE_KEY si está configurada (vía
# build_write_headers en supabase_rest.py), si no cae al comportamiento
# actual con la anon key. Con try/except porque este script debe seguir
# funcionando aunque falle el import (p.ej. supabase_rest.py roto o ausente).
try:
    from supabase_rest import build_write_headers
    HEADERS = build_write_headers()
except Exception:
    HEADERS = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal,resolution=merge-duplicates",
    }

def run_exporter(force=False):
    print("[SYNC VENTAS] -> Evaluando extracción selectiva...")
    if not os.path.exists(EXPORTER_SCRIPT):
        print(f"[SYNC VENTAS] ! Script no encontrado: {EXPORTER_SCRIPT}")
        return False
    args = [sys.executable, EXPORTER_SCRIPT]
    if force:
        args.append("force")
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=0x08000000
    )
    try:
        stdout, stderr = proc.communicate(timeout=120)
        if proc.returncode == 0:
            # Intentar imprimir salida pero no morir si falla el encoding de la consola
            try:
                for line in stdout.decode('utf-8', errors='replace').splitlines():
                    print(f"  {line}")
            except: pass
            return True
        else:
            print(f"[SYNC VENTAS] ! Error en exportador (código {proc.returncode}):")
            try:
                for line in stderr.decode('utf-8', errors='replace').splitlines():
                    print(f"  ! {line}")
            except: pass
            return False
    except subprocess.TimeoutExpired:
        _kill_proc(proc)
        print(f"[SYNC VENTAS] ! TIMEOUT (120s): exportador colgado en H:. Abortando.")
        return False
    except Exception as e:
        _kill_proc(proc)
        print(f"[SYNC VENTAS] ! Error ejecutando exportador: {e}")
        return False

def _send_batch_request(table: str, on_conflict: str, payload: list) -> bool:
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
            # Si es un error de clave foránea o de cliente, no reintentar para fallar rápido
            if e.code in (400, 409):
                return False
        except Exception as e:
            print(f"  [ERROR] {e}")
        if attempt < 3:
            delay = exponential_backoff(attempt)
            print(f"  [RETRY] Upsert {table} ({attempt}/3) en {delay:.0f}s...")
            time.sleep(delay)
    return False

def upsert_batch(table: str, on_conflict: str, payload: list) -> bool:
    if not payload: return True
    success = _send_batch_request(table, on_conflict, payload)
    if success:
        return True
    
    # Si falla y el lote tiene más de un elemento, lo dividimos recursivamente
    if len(payload) > 1:
        print(f"  [WARN] Lote de {len(payload)} registros en '{table}' falló. Dividiendo lote para aislar el error...")
        mid = len(payload) // 2
        left_ok = upsert_batch(table, on_conflict, payload[:mid])
        right_ok = upsert_batch(table, on_conflict, payload[mid:])
        return left_ok and right_ok
    else:
        # Si es un único elemento que falla, lo identificamos y lo omitimos
        item = payload[0]
        if table == "ventas_detalle":
            print(f"  [SKIPPED] Detalle omitido: ID {item.get('id')} (Doc: {item.get('documento')}, Producto: {item.get('codigo_producto')} - No existe en 'productos' o viola FK)")
        else:
            print(f"  [SKIPPED] Registro omitido en '{table}': {item}")
        return False

def get_hash(data_dict):
    s = "|".join(str(v) for v in data_dict.values())
    return hashlib.md5(s.encode('utf-8')).hexdigest()

# Tasa de cambio por defecto si falla el servicio
FACTOR_USD_DEFAULT = 489.55

def get_current_rate():
    try:
        from rates_service import RatesService
        service = RatesService()
        rates = service.get_all_rates()
        # Intentar obtener BCV USD primero, luego Binance P2P como fallback
        return rates.get("bcv_usd", rates.get("binance_p2p", FACTOR_USD_DEFAULT))
    except:
        return FACTOR_USD_DEFAULT

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
                delay = exponential_backoff(attempt)
                print(f"  [RETRY] Upsert {table} con respuesta ({attempt}/3) en {delay:.0f}s...")
                time.sleep(delay)
    return []

def sync_incremental(force=False):
    """Sincroniza ventas/clientes a Supabase. Devuelve True si terminó completo, False si abortó o hubo lotes fallidos."""
    if not SUPABASE_REST_URL or not SUPABASE_ANON_KEY: return False

    # Validar unidad H: antes de empezar (check_drive tiene timeout duro;
    # os.path.exists directo puede colgarse minutos con la unidad SMB caída)
    try:
        from config import RUTA_VENTAS_CABECERA
        base_h = os.path.dirname(RUTA_VENTAS_CABECERA)
    except ImportError:
        base_h = r"H:\HybridLite\HybridEmpresa\HybridDataBase"
    try:
        from network_util import check_drive
        drive_ok = check_drive(base_h)
    except ImportError:
        drive_ok = os.path.exists(base_h)
    if not drive_ok:
        print("[SYNC VENTAS] ! ERROR: Unidad de red H: no accesible. Abortando.")
        return False

    if not run_exporter(force=force): return False

    # Si algún lote falla (p.ej. corte de internet a mitad de subida), NO se debe
    # cachear su hash: quedaría marcado como subido y no se reintentaría jamás.
    had_errors = False


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

    def map_venta(row, fallback_rate):
        rif = row.get("THT_RIFCLIENTE", "").strip()
        
        # 🔑 Tasa de cambio de la factura
        tasa_doc = safe_decimal(row.get("THT_FACTORREFERENCIAL", 0))
        if tasa_doc <= 1.0: 
            tasa_doc = fallback_rate
        
        neto_ves = safe_decimal(row["THT_TOTALNETO"])
        imp_ves = safe_decimal(row.get("THT_TOTALIMPUESTO", 0))
        bruto_ves = safe_decimal(row.get("THT_TOTALBRUTO", 0))
        if bruto_ves == 0: bruto_ves = neto_ves - imp_ves

        # Conversión a USD
        neto_usd = neto_ves / tasa_doc
        impuesto_usd = imp_ves / tasa_doc
        bruto_usd = bruto_ves / tasa_doc

        # ID Único de HybridLite
        id_unico = to_int(row.get("THT_IDUNICO"))
        if id_unico == 0: id_unico = to_int(row["THT_AUTOINCREMENT"]) # Fallback


        return {
            "id_unico": id_unico,
            "documento": row["THT_DOCUMENTO"].zfill(8), 
            "fecha_emision": row["THT_FECHAEMISION"] if row["THT_FECHAEMISION"] else None,
            "rif_cliente": rif if rif else None, 
            "total_neto": round(neto_usd, 4),
            "total_impuesto": round(impuesto_usd, 4),
            "total_bruto": round(bruto_usd, 4),
            "status": to_int(row["THT_STATUS"]),
            "numero_control": row["THT_NUMEROCONTROL"],
            "metodo_pago": row.get("METODO_PAGO", "EFECTIVO"),
            "created_at": row.get("FECHA_HORA_COMPLETA")
        }

    # 1. Clientes
    if validate_csv("MAESTRO_CLIENTES.csv"):
        print("[SYNC VENTAS] Procesando clientes...")
        to_upsert = []  # lista de (pk, hash, mapped): el hash se cachea solo si el lote sube OK
        old_cache = cache.get("clientes", {})
        new_entity_cache = {}

        def flush_clientes(batch):
            nonlocal had_errors
            if not batch: return
            if upsert_batch("clientes", "codigo_cliente", [m for _, _, m in batch]):
                for pk, h, _ in batch:
                    new_entity_cache[pk] = h
            else:
                had_errors = True

        with open("MAESTRO_CLIENTES.csv", "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try:
                    mapped = map_cliente(row)
                    pk = mapped["codigo_cliente"]
                    h = get_hash(mapped)
                    if old_cache.get(pk) != h:
                        to_upsert.append((pk, h, mapped))
                    else:
                        new_entity_cache[pk] = h
                    if len(to_upsert) >= 500:
                        flush_clientes(to_upsert)
                        to_upsert = []
                except: continue
            flush_clientes(to_upsert)
            cache["clientes"] = new_entity_cache

    # 2. Ventas (Cabecera)
    ventas_map_ids = {}
    doc_to_tasa = {}
    current_bcv_rate = get_current_rate()
    
    if validate_csv("VENTAS_CABECERA.csv"):
        print(f"[SYNC VENTAS] Procesando ventas (Tasa actual: {current_bcv_rate})...")
        to_upsert = []
        # El caché ahora es {id_unico: [hash, cloud_id]}
        old_cache = cache.get("ventas", {})
        new_entity_cache = {}
        total_ventas_count = 0
        zero_total_count = 0

        with open("VENTAS_CABECERA.csv", "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try:
                    local_id = row["THT_AUTOINCREMENT"]
                    doc_num = row["THT_DOCUMENTO"].strip().zfill(8)
                    tasa = safe_decimal(row.get("THT_FACTORREFERENCIAL", current_bcv_rate))
                    if tasa <= 1.0: tasa = current_bcv_rate
                    doc_to_tasa[doc_num] = tasa

                    mapped = map_venta(row, current_bcv_rate)
                    total_ventas_count += 1
                    if mapped.get("total_neto", 0) == 0.0:
                        zero_total_count += 1
                    pk = str(mapped["id_unico"])
                    h = get_hash(mapped)
                    
                    # 💡 Si está en caché, recuperamos el cloud_id para los detalles
                    cached_data = old_cache.get(pk)
                    if cached_data and isinstance(cached_data, list) and cached_data[0] == h:
                        cloud_id = cached_data[1]
                        ventas_map_ids[local_id] = cloud_id
                        new_entity_cache[pk] = [h, cloud_id]
                    else:
                        to_upsert.append((local_id, mapped))
                    
                    if len(to_upsert) >= 500:
                        # Salvaguarda: si >50% de ventas tienen total_neto=0, posible error de lectura
                        if total_ventas_count > 50 and zero_total_count > total_ventas_count * 0.5:
                            print(f"[SYNC VENTAS] ! ABORTANDO: {zero_total_count}/{total_ventas_count} "
                                  f"ventas con total_neto=0. Posible CSV corrupto o tasa cero.")
                            return False
                        print(f"  [SYNC VENTAS] Upserting batch of {len(to_upsert)} sales...")
                        payload = [item[1] for item in to_upsert]
                        results = upsert_with_response("ventas", "id_unico", payload)
                        res_map = {r["id_unico"]: r["id"] for r in results if "id_unico" in r and "id" in r}
                        for lid, mapped_item in to_upsert:
                            uid = mapped_item["id_unico"]
                            cid = res_map.get(uid)
                            if cid is not None:
                                ventas_map_ids[lid] = cid
                                new_entity_cache[str(uid)] = [get_hash(mapped_item), cid]
                            else:
                                print(f"  [WARN] No se obtuvo cloud_id para id_unico {uid}")
                                had_errors = True
                        to_upsert = []
                except Exception as e: 
                    print(f"  [ERROR VENTA] doc {row.get('THT_DOCUMENTO')}: {e}")
                    continue
            
            if to_upsert:
                print(f"  [SYNC VENTAS] Upserting final batch of {len(to_upsert)} sales...")
                payload = [item[1] for item in to_upsert]
                results = upsert_with_response("ventas", "id_unico", payload)
                res_map = {r["id_unico"]: r["id"] for r in results if "id_unico" in r and "id" in r}
                for lid, mapped_item in to_upsert:
                    uid = mapped_item["id_unico"]
                    cid = res_map.get(uid)
                    if cid is not None:
                        ventas_map_ids[lid] = cid
                        new_entity_cache[str(uid)] = [get_hash(mapped_item), cid]
                    else:
                        print(f"  [WARN] No se obtuvo cloud_id para id_unico {uid}")
                        had_errors = True

            print(f"  [SYNC VENTAS] Total sales in mapping: {len(ventas_map_ids)}")
            cache["ventas"] = new_entity_cache

    # 3. Ventas Detalle
    if validate_csv("VENTAS_DETALLE.csv"):
        print("[SYNC VENTAS] Procesando ventas (Detalles)...")
        to_upsert = []  # lista de (pk, hash, mapped): el hash se cachea solo si el lote sube OK
        old_cache = cache.get("ventas_detalle", {})
        new_entity_cache = {}

        def flush_detalles(batch):
            nonlocal had_errors
            if not batch: return
            if upsert_batch("ventas_detalle", "id", [m for _, _, m in batch]):
                for pk, h, _ in batch:
                    new_entity_cache[pk] = h
            else:
                had_errors = True

        with open("VENTAS_DETALLE.csv", "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try:
                    doc_num = row["TBT_DOCUMENTO"].strip().zfill(8)
                    tasa = doc_to_tasa.get(doc_num, current_bcv_rate)
                    
                    local_parent_id = row.get("TBT_OPERACION_AUTOINCREMENT")
                    cloud_parent_id = ventas_map_ids.get(local_parent_id)
                    
                    # Si no tenemos el parent_id, el detalle no se puede linkear correctamente
                    if cloud_parent_id is None:
                        # Solo loguear una vez por documento para no inundar
                        # print(f"  [WARN] No parent ID for detail doc {doc_num} (local_parent_id: {local_parent_id})")
                        continue 

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
                    if old_cache.get(pk) != h:
                        to_upsert.append((pk, h, mapped))
                    else:
                        new_entity_cache[pk] = h

                    if len(to_upsert) >= 1000:
                        print(f"  [SYNC VENTAS] Upserting batch of {len(to_upsert)} details...")
                        flush_detalles(to_upsert)
                        to_upsert = []
                except Exception as e:
                    print(f"  [ERROR DETAIL] doc {row.get('TBT_DOCUMENTO')}: {e}")
                    continue

            flush_detalles(to_upsert)
            cache["ventas_detalle"] = new_entity_cache

    # Guardar Caché Final
    with open(CACHE_FILE, 'w') as cf: 
        json.dump(cache, cf)
        print(f"[SYNC VENTAS] Caché guardada en {CACHE_FILE}")
    
    # Limpieza de memoria explícita
    ventas_map_ids.clear()
    doc_to_tasa.clear()

    if had_errors:
        print("[SYNC VENTAS] [WARN] Sincronización finalizada CON ERRORES: "
              "algunos lotes no subieron y se reintentarán en el próximo sync.")
        # No reconciliar con datos parciales: podría borrar registros válidos en la nube
        return False

    print("[SYNC VENTAS] [OK] Sincronización finalizada.")

    # Metadata final
    try:
        with open(LAST_SYNC_FILE, "w") as f:
            json.dump({"last_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "timestamp": time.time()}, f)
    except: pass


    # 🔍 RECONCILIACIÓN AUTOMÁTICA (Audit)
    # Solo si no hubo errores críticos y estamos en modo completo
    reconcile_ventas(force=force)
    return True

_MIN_SAFE_IDS = 10

def reconcile_ventas(force: bool = False):
    """Busca registros en Supabase que ya no existen en los CSV locales y los elimina (con cooldown de 12h)."""
    # Verificar cooldown de 12 horas
    last_reconcile_time = 0.0
    last_reconcile_file = os.path.join(BASE_DIR, "ventas_last_reconcile.json")
    if os.path.exists(last_reconcile_file):
        try:
            with open(last_reconcile_file, 'r') as f:
                last_reconcile_time = json.load(f).get("last_reconcile", 0.0)
        except: pass
    
    now = time.time()
    if not force and (now - last_reconcile_time < 12 * 3600):
        print(f"[AUDIT] La última reconciliación de ventas fue hace menos de 12 horas. Saltando reconciliación.")
        return

    try:
        reconciled_any = False
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
                reconciled_any = True

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
                reconciled_any = True
                
        if reconciled_any or not os.path.exists(last_reconcile_file):
            try:
                with open(last_reconcile_file, 'w') as f:
                    json.dump({"last_reconcile": now}, f)
            except: pass
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
                time.sleep(exponential_backoff(attempt))
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

        # 🛡️ Salvaguarda inteligente contra eliminación masiva accidental
        total_cloud = len(cloud_ids)
        if total_cloud > 100 and len(orphans) > 200 and (len(orphans) / total_cloud) > 0.05:
            print(f"  [ABORT] Salvaguarda de Seguridad: Detectados demasiados huérfanos para eliminar "
                  f"({len(orphans)} de {total_cloud}, {len(orphans)/total_cloud*100:.1f}%). "
                  f"Posible error local o corrupción del CSV. Operación cancelada para proteger la nube.")
            return False

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
