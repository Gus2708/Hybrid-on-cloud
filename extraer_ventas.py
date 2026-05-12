import pydbisam
import os
import csv
import struct
import sys
import time
from datetime import date, datetime, timedelta

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
    return os.path.getmtime(dat_path) > os.path.getmtime(csv_filename) + 2

def run_extraction():
    # ─── Verificar unidad de red antes de operar ───────────────────────────
    test_path = os.path.join(base, "TInventario.dat")
    if not os.path.exists(test_path):
        print("  [DRIVE] Unidad H: no disponible. Abortando extracción de ventas.")
        return False

    # Solo extraer ventas de los últimos 90 días para evitar procesar
    # años de datos históricos y consumir memoria innecesariamente
    CORTE_FECHA = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')

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
    
    for dat, csv_f, cols in tasks:
        if should_extract(dat, csv_f):
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

                # Columnas de salida (agregamos metodo_pago y fecha_hora_completa al CSV)
                out_cols = cols.copy()
                if dat == "TTransaccionvta.dat":
                    out_cols.append("METODO_PAGO")
                    out_cols.append("FECHA_HORA_COMPLETA")

                with open(tmp_filename, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow(out_cols)
                    valid_rows = 0
                    
                    total_rows = db._total_rows + db._deleted_rows
                    if total_rows > 2_000_000:
                        print(f"  ! {dat}: {total_rows} filas reportadas (>2M). Posible corrupción. Abortando.")
                        raise Exception("Demasiadas filas — archivo corrupto o infinito")
                    for i in range(total_rows):
                        row = db.row(i)
                        if row is None: continue # Fila eliminada

                        # Lógica de filtrado: Solo Facturas (11) y No Anuladas (Status != 4)
                        if idx_tipo != -1:
                            tipo_val = str(row[col_indices[idx_tipo]]).strip()
                            if tipo_val != "11": continue
                        
                        if idx_status != -1:
                            status_val = str(row[col_indices[idx_status]]).strip()
                            if status_val == "4": continue

                        # Filtrar por fecha de corte (solo ventas recientes)
                        if idx_fecha != -1 and dat == "TTransaccionvta.dat":
                            fecha_val = str(row[col_indices[idx_fecha]]).strip()
                            if fecha_val and fecha_val < CORTE_FECHA:
                                continue

                        out_row = []
                        for col_idx in col_indices:
                            val = row[col_idx] if col_idx != -1 else ''
                            if isinstance(val, date): val = val.strftime('%Y-%m-%d')
                            elif val == 'Fail': val = ''
                            out_row.append(val)
                        
                        # Lógica especial para VENTAS_CABECERA
                        if dat == "TTransaccionvta.dat":
                            # 1. Método de Pago
                            id_unico = row[col_indices[idx_id_unico]] if idx_id_unico != -1 else None
                            metodo = payments_map.get(id_unico, "EFECTIVO") if id_unico else "EFECTIVO"
                            out_row.append(metodo)
                            
                            # 2. Fecha y Hora Completa
                            fecha_str = out_row[idx_fecha] if idx_fecha != -1 else ""
                            # Decodificar hora manualmente desde el buffer crudo si pydbisam falla
                            hora_str = "00:00:00"
                            if idx_hora != -1:
                                col_obj = db._columns[col_indices[idx_hora]]
                                row_offset = db._data_offset + (i * db._row_size)
                                field_data = db._data[row_offset + col_obj.row_offset : row_offset + col_obj.row_offset + 4]
                                ms_val = struct.unpack("<I", field_data)[0]
                                hora_str = decode_dbisam_time(ms_val)
                            
                            # Combinar en ISO 8601 con offset VZLA
                            full_ts = f"{fecha_str} {hora_str}-04:00"
                            out_row.append(full_ts)

                        writer.writerow(out_row)
                        valid_rows += 1
                
                os.replace(tmp_filename, csv_f)
                print(f"  -> {dat}: Guardado {valid_rows} registros filtrados en {csv_f}")
                any_extracted = True
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"Error procesando {dat}: {e}")
            finally:
                if db is not None:
                    del db
        else:
            print(f"[SKIP] {dat} no ha cambiado.")
            
    if not any_extracted:
        print("Todo está al día. No se extrajo nada.")
    return any_extracted

if __name__ == '__main__':
    run_extraction()
