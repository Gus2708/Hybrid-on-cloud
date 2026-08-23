import os
import re
import json
import struct
import urllib.request
import urllib.error
import urllib.parse
from datetime import date, datetime

try:
    from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY
except ImportError:
    SUPABASE_REST_URL = ""
    SUPABASE_ANON_KEY = ""

# Encabezados para comunicación REST con Supabase. Usa SUPABASE_SERVICE_KEY si
# está configurada (mismo patrón que sync_ventas.py y remote_listener.py), para
# que las escrituras sigan funcionando si se endurecen las políticas RLS.
# try/except: debe seguir funcionando aunque falte el helper.
try:
    from supabase_rest import build_write_headers
    HEADERS = build_write_headers(extra_prefer="return=minimal")
except Exception:
    HEADERS = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }

def decode_dbisam_time(ms_value):
    """Decodifica milisegundos desde medianoche a formato HH:MM:SS"""
    if not isinstance(ms_value, int):
        return "00:00:00"
    h = ms_value // (1000 * 3600)
    m = (ms_value % (1000 * 3600)) // (1000 * 60)
    s = (ms_value % (1000 * 60)) // 1000
    return f"{h:02d}:{m:02d}:{s:02d}"

def get_product_descriptions(csv_path):
    """Lee el CSV maestro actual para mapear código a descripción localmente."""
    mapping = {}
    if not os.path.exists(csv_path):
        return mapping
    try:
        import csv
        with open(csv_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get('CODIGO_INTERNO', '').strip()
                desc = row.get('DESCRIPCION', '').strip()
                if code:
                    mapping[code] = desc
    except Exception as e:
        print(f"[SYNC AJUSTES] Error cargando descripciones locales: {e}")
    return mapping

def get_synced_transaction_ids() -> set:
    """Busca en Supabase las cabeceras de órdenes de cambio que tienen el tag de sincronización local."""
    synced = set()
    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/ordenes_cambio?select=nota"
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            rows = json.loads(resp.read().decode())
            for r in rows:
                nota = r.get("nota") or ""
                # Buscar patrón: [Local Inv ID: 123] o [Local Com ID: 123]
                match = re.search(r"\[Local (Inv|Com) ID:\s*(\d+)\]", nota)
                if match:
                    synced.add((match.group(1), int(match.group(2))))
    except Exception as e:
        print(f"[SYNC AJUSTES] Error consultando ordenes sincronizadas: {e}")
    return synced

def insert_parent_order(payload) -> int:
    """Inserta la cabecera en Supabase y retorna el ID asignado por la base de datos."""
    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/ordenes_cambio"
    headers = HEADERS.copy()
    headers["Prefer"] = "return=representation"
    data = json.dumps([payload]).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read().decode())
            if res and isinstance(res, list) and len(res) > 0:
                return res[0].get("id")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else ""
        print(f"[SYNC AJUSTES] Error insertando cabecera: HTTP {e.code} - {body}")
    except Exception as e:
        print(f"[SYNC AJUSTES] Error insertando cabecera: {e}")
    return None

def insert_child_items(items) -> bool:
    """Realiza la inserción masiva de los detalles del movimiento en Supabase."""
    if not items:
        return True
    # Estos items son ESPEJOS HISTÓRICOS de movimientos ya aplicados en HybridLite.
    # `ordenes_cambio_items.backend_status` es también la cola del write-back
    # (hybrid_writeback/listener_writeback.py): si nacieran 'pendiente' (el default
    # de la columna), el listener los RE-aplicaría en HybridLite y se armaría un
    # bucle de retroalimentación (re-aplicar -> se vuelve a espejar -> re-aplicar).
    # Se insertan directamente 'completado' como segunda capa de defensa (la
    # primera: el listener filtra por creado_por NOT NULL en la cabecera).
    for item in items:
        item.setdefault("backend_status", "completado")
        item.setdefault("backend_resultado",
                        "Espejo histórico sincronizado desde HybridLite por "
                        "sync_ajustes; ya aplicado localmente, no procesar.")
    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/ordenes_cambio_items"
    data = json.dumps(items).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.getcode() in (200, 201, 204)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else ""
        print(f"[SYNC AJUSTES] Error insertando items: HTTP {e.code} - {body}")
        return False
    except Exception as e:
        print(f"[SYNC AJUSTES] Error insertando items: {e}")
        return False

def sync_manual_adjustments(base_db_dir, synced_ids, desc_mapping):
    """Extrae ajustes manuales locales de DBISAM y los sincroniza a Supabase."""
    import pydbisam
    path_header = os.path.join(base_db_dir, "TTransaccioninv.dat")
    path_detail = os.path.join(base_db_dir, "TDetalleInv.Dat")
    if not os.path.exists(path_header) or not os.path.exists(path_detail):
        print("[SYNC AJUSTES] Tablas de ajustes locales (inv) no encontradas. Saltando.")
        return 0

    # 1. Cargar detalles agrupados por Parent ID
    print("[SYNC AJUSTES] Cargando detalles de ajustes locales...")
    db_det = pydbisam.PyDBISAM(path_detail)
    col_names_det = [c.name for c in db_det._columns]
    idx_det_code = col_names_det.index('TBT_CODIGO')
    idx_det_qty = col_names_det.index('TBT_CANTIDAD')
    idx_det_prev = col_names_det.index('TBT_EXISTANTERIOR')
    idx_det_act = col_names_det.index('TBT_EXISTACTUAL')
    idx_det_parent = col_names_det.index('TBT_OPERACION_AUTOINCREMENT')
    idx_det_memo = col_names_det.index('TBT_MEMODETALLE') if 'TBT_MEMODETALLE' in col_names_det else -1

    items_by_parent = {}
    for r in db_det.rows():
        if r is None: continue
        parent_id = int(r[idx_det_parent])
        qty = float(r[idx_det_qty])
        if qty == 0.0: continue # Omitir ajustes neutros
        
        item = {
            "codigo": str(r[idx_det_code]).strip(),
            "cantidad": qty,
            "anterior": float(r[idx_det_prev]),
            "actual": float(r[idx_det_act]),
            "memo": str(r[idx_det_memo]).strip() if idx_det_memo != -1 and r[idx_det_memo] else None
        }
        if parent_id not in items_by_parent:
            items_by_parent[parent_id] = []
        items_by_parent[parent_id].append(item)
    del db_det

    # 2. Procesar cabeceras y sincronizar
    print("[SYNC AJUSTES] Cargando transacciones de ajustes...")
    db_hdr = pydbisam.PyDBISAM(path_header)
    col_names_hdr = [c.name for c in db_hdr._columns]
    idx_hdr_id = col_names_hdr.index('THT_AUTOINCREMENT')
    idx_hdr_doc = col_names_hdr.index('THT_DOCUMENTO')
    idx_hdr_status = col_names_hdr.index('THT_STATUS')
    idx_hdr_fecha = col_names_hdr.index('THT_FECHAEMISION')
    idx_hdr_classify = col_names_hdr.index('THT_DESCRIPCLASIFY')
    idx_hdr_hora = col_names_hdr.index('THT_HORA')

    count_synced = 0
    total_rows = db_hdr._total_rows + db_hdr._deleted_rows
    for i in range(total_rows):
        row = db_hdr.row(i)
        if row is None: continue

        status_val = str(row[idx_hdr_status]).strip()
        if status_val == "4": continue # Omitir anulados
        
        local_id = int(row[idx_hdr_id])
        if ("Inv", local_id) in synced_ids:
            continue # Ya sincronizado

        details = items_by_parent.get(local_id)
        if not details:
            continue # Sin items a ajustar

        # Extraer hora precisa desde milisegundos binarios de DBISAM
        col_obj = db_hdr._columns[idx_hdr_hora]
        row_offset = db_hdr._data_offset + (i * db_hdr._row_size)
        field_data = db_hdr._data[row_offset + col_obj.row_offset : row_offset + col_obj.row_offset + 4]
        ms_val = struct.unpack("<I", field_data)[0]

        fecha_val = row[idx_hdr_fecha]
        fecha_str = fecha_val.strftime("%Y-%m-%d") if isinstance(fecha_val, (date, datetime)) else str(fecha_val).split(" ")[0].strip()
        hora_str = decode_dbisam_time(ms_val)
        timestamp_iso = f"{fecha_str}T{hora_str}-04:00"

        classify_val = str(row[idx_hdr_classify]).strip()
        doc_num = str(row[idx_hdr_doc]).strip().zfill(8)

        nota = f"[Local Inv ID: {local_id}] - Ajuste #{doc_num}: {classify_val}"

        parent_payload = {
            "nota": nota,
            "status": "emitido",
            "creado_en": timestamp_iso
        }

        print(f"  -> Sincronizando ajuste local ID {local_id} ({nota})...")
        cloud_parent_id = insert_parent_order(parent_payload)
        if cloud_parent_id:
            child_payloads = []
            for d in details:
                desc = desc_mapping.get(d["codigo"], "Producto local")
                child_payloads.append({
                    "orden_id": cloud_parent_id,
                    "codigo_producto": d["codigo"],
                    "descripcion": desc,
                    "existencia_actual": d["anterior"],
                    "nueva_existencia": d["actual"],
                    "nota": d["memo"]
                })
            if insert_child_items(child_payloads):
                count_synced += 1
                synced_ids.add(("Inv", local_id))
            else:
                print(f"  [ERROR] No se pudieron insertar detalles para ajuste ID {local_id}")
        else:
            print(f"  [ERROR] No se pudo insertar cabecera para ajuste ID {local_id}")
    del db_hdr
    return count_synced

def sync_purchases(base_db_dir, synced_ids, desc_mapping):
    """Extrae compras/ingresos locales de DBISAM y los sincroniza a Supabase."""
    import pydbisam
    path_header = os.path.join(base_db_dir, "TTransaccioncom.dat")
    path_detail = os.path.join(base_db_dir, "TDetalleCom.Dat")
    if not os.path.exists(path_header) or not os.path.exists(path_detail):
        print("[SYNC AJUSTES] Tablas de compras locales (com) no encontradas. Saltando.")
        return 0

    # 1. Cargar detalles agrupados por Parent ID
    print("[SYNC AJUSTES] Cargando detalles de compras locales...")
    db_det = pydbisam.PyDBISAM(path_detail)
    col_names_det = [c.name for c in db_det._columns]
    idx_det_code = col_names_det.index('TBT_CODIGO')
    idx_det_qty = col_names_det.index('TBT_CANTIDAD')
    idx_det_prev = col_names_det.index('TBT_EXISTANTERIOR')
    idx_det_act = col_names_det.index('TBT_EXISTACTUAL')
    idx_det_parent = col_names_det.index('TBT_OPERACION_AUTOINCREMENT')
    idx_det_memo = col_names_det.index('TBT_MEMODETALLE') if 'TBT_MEMODETALLE' in col_names_det else -1

    items_by_parent = {}
    for r in db_det.rows():
        if r is None: continue
        parent_id = int(r[idx_det_parent])
        qty = float(r[idx_det_qty])
        if qty == 0.0: continue
        
        item = {
            "codigo": str(r[idx_det_code]).strip(),
            "cantidad": qty, # Las compras incrementan stock (siempre positivas)
            "anterior": float(r[idx_det_prev]),
            "actual": float(r[idx_det_act]),
            "memo": str(r[idx_det_memo]).strip() if idx_det_memo != -1 and r[idx_det_memo] else None
        }
        if parent_id not in items_by_parent:
            items_by_parent[parent_id] = []
        items_by_parent[parent_id].append(item)
    del db_det

    # 2. Procesar cabeceras y sincronizar
    print("[SYNC AJUSTES] Cargando transacciones de compras...")
    db_hdr = pydbisam.PyDBISAM(path_header)
    col_names_hdr = [c.name for c in db_hdr._columns]
    idx_hdr_id = col_names_hdr.index('THT_AUTOINCREMENT')
    idx_hdr_doc = col_names_hdr.index('THT_DOCUMENTO')
    idx_hdr_status = col_names_hdr.index('THT_STATUS')
    idx_hdr_fecha = col_names_hdr.index('THT_FECHAEMISION')
    idx_hdr_rif = col_names_hdr.index('THT_RIFCLIENTE')
    idx_hdr_prov_name = col_names_hdr.index('THT_PERSONACONTACTO')
    idx_hdr_hora = col_names_hdr.index('THT_HORA')

    count_synced = 0
    total_rows = db_hdr._total_rows + db_hdr._deleted_rows
    for i in range(total_rows):
        row = db_hdr.row(i)
        if row is None: continue

        status_val = str(row[idx_hdr_status]).strip()
        if status_val == "4": continue # Omitir anuladas
        
        local_id = int(row[idx_hdr_id])
        if ("Com", local_id) in synced_ids:
            continue # Ya sincronizada

        details = items_by_parent.get(local_id)
        if not details:
            continue

        # Extraer hora precisa de DBISAM
        col_obj = db_hdr._columns[idx_hdr_hora]
        row_offset = db_hdr._data_offset + (i * db_hdr._row_size)
        field_data = db_hdr._data[row_offset + col_obj.row_offset : row_offset + col_obj.row_offset + 4]
        ms_val = struct.unpack("<I", field_data)[0]

        fecha_val = row[idx_hdr_fecha]
        fecha_str = fecha_val.strftime("%Y-%m-%d") if isinstance(fecha_val, (date, datetime)) else str(fecha_val).split(" ")[0].strip()
        hora_str = decode_dbisam_time(ms_val)
        timestamp_iso = f"{fecha_str}T{hora_str}-04:00"

        doc_num = str(row[idx_hdr_doc]).strip().zfill(8)
        prov_rif = str(row[idx_hdr_rif]).strip()
        prov_name = str(row[idx_hdr_prov_name]).strip()

        nota = f"[Local Com ID: {local_id}] - Compra #{doc_num}: {prov_name}"
        if prov_rif:
            nota += f" (RIF: {prov_rif})"

        parent_payload = {
            "nota": nota,
            "status": "emitido",
            "creado_en": timestamp_iso
        }

        print(f"  -> Sincronizando compra local ID {local_id} ({nota})...")
        cloud_parent_id = insert_parent_order(parent_payload)
        if cloud_parent_id:
            child_payloads = []
            for d in details:
                desc = desc_mapping.get(d["codigo"], "Producto local")
                child_payloads.append({
                    "orden_id": cloud_parent_id,
                    "codigo_producto": d["codigo"],
                    "descripcion": desc,
                    "existencia_actual": d["anterior"],
                    "nueva_existencia": d["actual"],
                    "nota": d["memo"]
                })
            if insert_child_items(child_payloads):
                count_synced += 1
                synced_ids.add(("Com", local_id))
            else:
                print(f"  [ERROR] No se pudieron insertar detalles para compra ID {local_id}")
        else:
            print(f"  [ERROR] No se pudo insertar cabecera para compra ID {local_id}")
    del db_hdr
    return count_synced

def sync_movimientos_locales(force: bool = False):
    """Bucle principal de sincronización de movimientos locales con optimización por mtime."""
    print("=== Iniciando Sincronización de Movimientos Locales (Ajustes y Compras) ===")
    if not SUPABASE_REST_URL or not SUPABASE_ANON_KEY:
        print("[SYNC AJUSTES] Error: URL o clave de Supabase no configuradas.")
        return

    try:
        from config import CSV_SOURCE_PATH, RUTA_INVENTARIO
        base_db_dir = os.path.dirname(RUTA_INVENTARIO)
        
        path_inv = os.path.join(base_db_dir, "TTransaccioninv.dat")
        path_com = os.path.join(base_db_dir, "TTransaccioncom.dat")
        
        # Obtener mtimes locales
        mtime_inv = os.path.getmtime(path_inv) if os.path.exists(path_inv) else 0.0
        mtime_com = os.path.getmtime(path_com) if os.path.exists(path_com) else 0.0
        
        # Cargar mtimes guardados previamente
        mtimes_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_ajustes_mtimes.json")
        saved_mtimes = {}
        if os.path.exists(mtimes_file):
            try:
                with open(mtimes_file, 'r') as f:
                    saved_mtimes = json.load(f)
            except: pass
            
        saved_inv = saved_mtimes.get("TTransaccioninv.dat", 0.0)
        saved_com = saved_mtimes.get("TTransaccioncom.dat", 0.0)
        
        # Si no han cambiado y no es forzado, saltar
        if not force and mtime_inv == saved_inv and mtime_com == saved_com:
            print("[SYNC AJUSTES] Los archivos locales de transacciones no han cambiado. Saltando sincronización.")
            print("=== Sincronización de Movimientos Locales Finalizada ===")
            return
            
        # 1. Cargar descripciones para resolución local ultra rápida
        print("[SYNC AJUSTES] Cargando catálogo local...")
        desc_mapping = get_product_descriptions(CSV_SOURCE_PATH)
        
        # 2. Consultar registros previos en la nube
        print("[SYNC AJUSTES] Consultando transacciones previas en Supabase...")
        synced_ids = get_synced_transaction_ids()
        print(f"[SYNC AJUSTES] Encontradas {len(synced_ids)} transacciones ya registradas en la nube.")
        
        # 3. Sincronizar ajustes manuales
        adj_count = sync_manual_adjustments(base_db_dir, synced_ids, desc_mapping)
        print(f"[SYNC AJUSTES] Finalizado. Sincronizados {adj_count} ajustes locales.")
        
        # 4. Sincronizar compras (ingresos)
        com_count = sync_purchases(base_db_dir, synced_ids, desc_mapping)
        print(f"[SYNC AJUSTES] Finalizado. Sincronizadas {com_count} compras locales.")
        
        # Guardar nuevos mtimes
        try:
            with open(mtimes_file, 'w') as f:
                json.dump({
                    "TTransaccioninv.dat": mtime_inv,
                    "TTransaccioncom.dat": mtime_com
                }, f)
        except: pass
        
        print("=== Sincronización de Movimientos Locales Finalizada con Éxito ===")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[SYNC AJUSTES] Error general en la sincronización de movimientos: {e}")

if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    sync_movimientos_locales(force=(mode == "force"))
