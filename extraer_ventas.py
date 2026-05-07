import pydbisam
import os
import csv
from datetime import date

base = r"h:\HybridLite\HybridEmpresa\HybridDataBase"

def extract_table_to_csv(dat_filename, csv_filename, target_columns):
    filepath = os.path.join(base, dat_filename)
    if not os.path.exists(filepath):
        print(f"Error: {filepath} no existe.")
        return

    print(f"Extrayendo {dat_filename} a {csv_filename}...")
    tmp_filename = csv_filename + ".tmp"
    try:
        db = pydbisam.PyDBISAM(filepath)
        col_indices = []
        for target in target_columns:
            found = False
            for i, col in enumerate(db._columns):
                if col.name.upper() == target.upper():
                    col_indices.append(i)
                    found = True
                    break
            if not found:
                col_indices.append(-1)
                
        with open(tmp_filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(target_columns)
            for row in db.rows():
                out_row = []
                for idx in col_indices:
                    if idx != -1:
                        val = row[idx]
                        if isinstance(val, date): val = val.strftime('%Y-%m-%d')
                        elif val == 'Fail': val = ''
                        out_row.append(val)
                    else: out_row.append('')
                writer.writerow(out_row)
        
        # Reemplazo atómico: El archivo original nunca está vacío
        os.replace(tmp_filename, csv_filename)
        print(f"  -> Guardado {db._total_rows} registros en {csv_filename}")
    except Exception as e:
        if os.path.exists(tmp_filename): os.remove(tmp_filename)
        print(f"Error procesando {dat_filename}: {e}")

def should_extract(dat_filename, csv_filename):
    dat_path = os.path.join(base, dat_filename)
    if not os.path.exists(dat_path): return False
    if not os.path.exists(csv_filename): return True
    # Si el .dat es más nuevo que el .csv (con margen de 2s), extraer
    return os.path.getmtime(dat_path) > (os.path.getmtime(csv_filename) + 2)

if __name__ == '__main__':
    # Lista de tareas: (DAT, CSV, Columnas)
    tasks = [
        ("TClientes.dat", "MAESTRO_CLIENTES.csv", 
         ["CLT_CODIGO", "CLT_DESCRIPCION", "CLT_RIF", "CLT_TELEFONO", "CLT_DIRECCION1"]),
        
        ("TTransaccionvta.dat", "VENTAS_CABECERA.csv", 
         ["THT_AUTOINCREMENT", "THT_DOCUMENTO", "THT_FECHAEMISION", "THT_RIFCLIENTE", "THT_TOTALNETO", 
          "THT_STATUS", "THT_NUMEROCONTROL", "THT_TOTALIMPUESTO", "THT_TIPO", "THT_TOTALBRUTO", "THT_FACTORREFERENCIAL"]),
        
        ("TDetalleVta.dat", "VENTAS_DETALLE.csv", 
         ["TBT_AUTOINCREMENT", "TBT_DOCUMENTO", "TBT_CODIGO", "TBT_CANTIDAD", "TBT_PRECIODEVENTA", 
          "TBT_CTOCOSTOSTR", "TBT_OPERACION_AUTOINCREMENT", "TBT_TIPOOPERACION"])
    ]
    
    any_extracted = False
    for dat, csv_f, cols in tasks:
        if should_extract(dat, csv_f):
            # Para ventas, aplicamos filtros especiales dentro de la extracción si es necesario
            # Pero para mantener la función genérica, filtraremos en el loop de filas
            filepath = os.path.join(base, dat)
            tmp_filename = csv_f + ".tmp"
            try:
                db = pydbisam.PyDBISAM(filepath)
                col_indices = [next((i for i, c in enumerate(db._columns) if c.name.upper() == target.upper()), -1) for target in cols]
                
                # Indices para filtros
                idx_tipo = -1
                idx_status = -1
                if "THT_TIPO" in cols: idx_tipo = cols.index("THT_TIPO")
                elif "TBT_TIPOOPERACION" in cols: idx_tipo = cols.index("TBT_TIPOOPERACION")
                if "THT_STATUS" in cols: idx_status = cols.index("THT_STATUS")

                with open(tmp_filename, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow(cols)
                    valid_rows = 0
                    for row in db.rows():
                        # Lógica de filtrado: Solo Facturas (11) y No Anuladas (Status != 4)
                        if idx_tipo != -1:
                            tipo_val = str(row[col_indices[idx_tipo]]).strip()
                            if tipo_val != "11": continue # Solo Facturas
                        
                        if idx_status != -1:
                            status_val = str(row[col_indices[idx_status]]).strip()
                            if status_val == "4": continue # Saltar Anuladas

                        out_row = []
                        for idx in col_indices:
                            val = row[idx] if idx != -1 else ''
                            if isinstance(val, date): val = val.strftime('%Y-%m-%d')
                            elif val == 'Fail': val = ''
                            out_row.append(val)
                        writer.writerow(out_row)
                        valid_rows += 1
                
                os.replace(tmp_filename, csv_f)
                print(f"  -> {dat}: Guardado {valid_rows} registros filtrados en {csv_f}")
                any_extracted = True
            except Exception as e:
                print(f"Error procesando {dat}: {e}")
        else:
            print(f"[SKIP] {dat} no ha cambiado.")
            
    if not any_extracted:
        print("Todo está al día. No se extrajo nada.")
