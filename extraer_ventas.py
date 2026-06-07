import pydbisam
import os
import csv
import struct
import sys
import time
from datetime import date, datetime, timedelta
from lock_util import safe_replace

base = r"h:\HybridLite\HybridEmpresa\HybridDataBase"

# ─── Reintento para operaciones de red/archivo ───────────────────────────────
_MAX_RETRIES = 3
_RETRY_DELAY = 2

def _safe_read_db(filepath: str, retries: int = _MAX_RETRIES):
    """Lee un archivo DBISAM con reintentos si la red/unidad falla."""
    for attempt in range(1, retries + 1):
        try:
            db = pydbisam.PyDBISAM(filepath)
            _ = db._row_size
            return db
        except Exception as e:
            if attempt < retries:
                print(f"  [RETRY {attempt}/{retries}] Error leyendo {os.path.basename(filepath)}: {str(e)[:80]}")
                time.sleep(_RETRY_DELAY)
            else:
                raise

def get_payments_map():
    path = os.path.join(base, "TDetalleFormasPagoVta.Dat")
    if not os.path.exists(path):
        return {}
    
    payments = {}
    try:
        db = pydbisam.PyDBISAM(path)
        # Identificar columnas necesarias
        idx_id_src = -1
        idx_desc = -1
        for i, col in enumerate(db._columns):
            if col.name.upper() == "DFP_IDUNICOSOURCE": idx_id_src = i
            elif col.name.upper() == "DFP_DESCRIPCION": idx_desc = i
        
        if idx_id_src == -1 or idx_desc == -1:
            return {}

        for row in db.rows():
            id_src = row[idx_id_src]
            desc = row[idx_desc]
            if id_src:
                payments[id_src] = desc
    except Exception as e:
        print(f"Error cargando mapa de pagos: {e}")
    return payments

def decode_dbisam_time(ms_value):
    """Decodifica milisegundos desde medianoche a formato HH:MM:SS"""
    if not isinstance(ms_value, int):
        return "00:00:00"
    h = ms_value // (1000 * 3600)
    m = (ms_value % (1000 * 3600)) // (1000 * 60)
    s = (ms_value % (1000 * 60)) // 1000
    return f"{h:02d}:{m:02d}:{s:02d}"

def should_extract(dat_filename, csv_filename):
    dat_path = os.path.join(base, dat_filename)
    if not os.path.exists(dat_path): return False
    if not os.path.exists(csv_filename): return True
    return os.path.getmtime(dat_path) > os.path.getmtime(csv_filename)

def load_existing_csv_simple(csv_path, key_idx=0):
    rows_dict = {}
    if not os.path.exists(csv_path):
        return rows_dict
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader, None) # Saltar cabecera
            if not header:
                return rows_dict
            for r in reader:
                if len(r) > key_idx:
                    key = r[key_idx].strip()
                    if key:
                        rows_dict[key] = r
    except Exception as e:
        print(f"Error cargando CSV existente {csv_path}: {e}")
    return rows_dict

def run_extraction(force=False):
    # ─── Verificar unidad de red antes de operar ───────────────────────────
    test_path = os.path.join(base, "TInventario.dat")
    if not os.path.exists(test_path):
        print("  [DRIVE] Unidad H: no disponible. Abortando extracción de ventas.")
        return False

    # Lista de tareas: (DAT, CSV, Columnas)
    tasks = [
        ("TClientes.dat", "MAESTRO_CLIENTES.csv", 
         ["CLT_CODIGO", "CLT_DESCRIPCION", "CLT_RIF", "CLT_TELEFONO", "CLT_DIRECCION1"]),
        
        ("TTransaccionvta.dat", "VENTAS_CABECERA.csv", 
         ["THT_AUTOINCREMENT", "THT_DOCUMENTO", "THT_FECHAEMISION", "THT_RIFCLIENTE", "THT_TOTALNETO", 
          "THT_STATUS", "THT_NUMEROCONTROL", "THT_TOTALIMPUESTO", "THT_TIPO", "THT_TOTALBRUTO", 
          "THT_FACTORREFERENCIAL", "THT_HORA", "THT_IDUNICO"]),
        
        ("TDetalleVta.dat", "VENTAS_DETALLE.csv", 
         ["TBT_AUTOINCREMENT", "TBT_DOCUMENTO", "TBT_CODIGO", "TBT_CANTIDAD", "TBT_PRECIODEVENTA", 
          "TBT_CTOCOSTOSTR", "TBT_OPERACION_AUTOINCREMENT", "TBT_TIPOOPERACION"])
    ]
    
    any_extracted = False
    payments_map = None
    
    # ─── Determinar si las ventas cambiaron (cabecera o detalle) ───
    ventas_changed = should_extract("TTransaccionvta.dat", "VENTAS_CABECERA.csv") or should_extract("TDetalleVta.dat", "VENTAS_DETALLE.csv")
    
    for dat, csv_f, cols in tasks:
        is_venta = dat in ["TTransaccionvta.dat", "TDetalleVta.dat"]
        need_extract = (ventas_changed if is_venta else should_extract(dat, csv_f)) or force
        
        if need_extract:
            filepath = os.path.join(base, dat)
            tmp_filename = csv_f + ".tmp"
            
            # Cargar mapa de pagos solo si vamos a procesar ventas
            if dat == "TTransaccionvta.dat" and payments_map is None:
                print("Cargando catálogo de métodos de pago...")
                payments_map = get_payments_map()

            db = None
            try:
                db = _safe_read_db(filepath)
                col_indices = [next((i for i, c in enumerate(db._columns) if c.name.upper() == target.upper()), -1) for target in cols]
                
                # Columnas para lógica especial
                idx_tipo = next((i for i, c in enumerate(cols) if c == "THT_TIPO" or c == "TBT_TIPOOPERACION"), -1)
                idx_status = next((i for i, c in enumerate(cols) if c == "THT_STATUS"), -1)
                idx_fecha = next((i for i, c in enumerate(cols) if c == "THT_FECHAEMISION"), -1)
                idx_hora = next((i for i, c in enumerate(cols) if c == "THT_HORA"), -1)
                idx_id_unico = next((i for i, c in enumerate(cols) if c == "THT_IDUNICO"), -1)

                # Columnas de salida
                out_cols = cols.copy()
                if dat == "TTransaccionvta.dat":
                    out_cols.append("METODO_PAGO")
                    out_cols.append("FECHA_HORA_COMPLETA")

                # Cargar datos existentes si es incremental
                existing_data = {}
                is_incremental = False
                total_rows = db._total_rows + db._deleted_rows

                if not force and os.path.exists(csv_f):
                    existing_data = load_existing_csv_simple(csv_f, key_idx=0)
                    if existing_data and len(existing_data) > 100:
                        is_incremental = True

                start_idx = 0
                if is_incremental:
                    limit_n = 2000 if dat == "TDetalleVta.dat" else 1000
                    if total_rows > limit_n:
                        start_idx = total_rows - limit_n
                        print(f"  [INCREMENTAL] {dat}: Extrayendo últimos {limit_n} registros (de {total_rows})...")

                if total_rows > 2_000_000:
                    print(f"  ! {dat}: {total_rows} filas reportadas (>2M). Posible corrupción. Abortando.")
                    raise Exception("Demasiadas filas — archivo corrupto o infinito")

                # Recolectar o actualizar registros
                new_rows = []
                for i in range(start_idx, total_rows):
                    row = db.row(i)
                    if row is None: continue # Fila eliminada

                    # Lógica de filtrado: Solo Facturas (11) y No Anuladas (Status != 4)
                    if idx_tipo != -1:
                        tipo_val = str(row[col_indices[idx_tipo]]).strip()
                        if tipo_val != "11": continue
                    
                    if idx_status != -1:
                        status_val = str(row[col_indices[idx_status]]).strip()
                        if status_val == "4": continue

                    out_row = []
                    for col_idx in col_indices:
                        val = row[col_idx] if col_idx != -1 else ''
                        if isinstance(val, date): val = val.strftime('%Y-%m-%d')
                        elif val == 'Fail': val = ''
                        out_row.append(val)
                    
                    # Lógica especial para VENTAS_CABECERA
                    if dat == "TTransaccionvta.dat":
                        id_unico = row[col_indices[idx_id_unico]] if idx_id_unico != -1 else None
                        metodo = payments_map.get(id_unico, "EFECTIVO") if id_unico else "EFECTIVO"
                        out_row.append(metodo)
                        
                        fecha_str = out_row[idx_fecha] if idx_fecha != -1 else ""
                        hora_str = "00:00:00"
                        if idx_hora != -1:
                            col_obj = db._columns[col_indices[idx_hora]]
                            row_offset = db._data_offset + (i * db._row_size)
                            field_data = db._data[row_offset + col_obj.row_offset : row_offset + col_obj.row_offset + 4]
                            ms_val = struct.unpack("<I", field_data)[0]
                            hora_str = decode_dbisam_time(ms_val)
                        
                        full_ts = f"{fecha_str} {hora_str}-04:00"
                        out_row.append(full_ts)

                    # Si es incremental, actualizamos el diccionario en memoria
                    if is_incremental:
                        key = str(out_row[0]).strip()
                        if key:
                            existing_data[key] = out_row
                    else:
                        new_rows.append(out_row)

                # Guardar el CSV resultante
                with open(tmp_filename, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow(out_cols)
                    
                    if is_incremental:
                        # Escribir todos los registros fusionados en memoria
                        for key in existing_data:
                            writer.writerow(existing_data[key])
                        valid_rows = len(existing_data)
                    else:
                        for r in new_rows:
                            writer.writerow(r)
                        valid_rows = len(new_rows)
                
                # Reemplazo seguro con reintentos
                if safe_replace(tmp_filename, csv_f):
                    mode_str = "Incremental" if is_incremental else "Completo"
                    print(f"  -> {dat}: ({mode_str}) Guardado {valid_rows} registros filtrados en {csv_f}")
                else:
                    raise IOError(f"No se pudo reemplazar {csv_f} debido a bloqueos de archivos en Windows.")
                
                any_extracted = True
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"Error procesando {dat}: {e}")
                if os.path.exists(tmp_filename):
                    try: os.remove(tmp_filename)
                    except: pass
            finally:
                if db is not None:
                    del db
        else:
            print(f"[SKIP] {dat} no ha cambiado.")
            
    if not any_extracted:
        print("Todo está al día. No se extrajo nada.")
    return any_extracted

if __name__ == '__main__':
    force = len(sys.argv) > 1 and sys.argv[1] == "force"
    run_extraction(force=force)

