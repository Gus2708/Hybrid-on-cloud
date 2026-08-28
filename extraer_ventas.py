import pydbisam
import os
import csv
from datetime import date
try:
    import config
    RUTA_CLIENTES = config.RUTA_CLIENTES
    RUTA_VENTAS = config.RUTA_VENTAS
    RUTA_VENTAS_DETALLE = config.RUTA_VENTAS_DETALLE
except ImportError:
    RUTA_CLIENTES = r"h:\HybridLite\HybridEmpresa\HybridDataBase\TClientes.dat"
    RUTA_VENTAS = r"h:\HybridLite\HybridEmpresa\HybridDataBase\TTransaccionvta.dat"
    RUTA_VENTAS_DETALLE = r"h:\HybridLite\HybridEmpresa\HybridDataBase\TDetalleVta.dat"

def extract_table_to_csv(filepath, csv_filename, target_columns):
    if not os.path.exists(filepath):
        print(f"Error: {filepath} no existe.")
        return

    print(f"Extrayendo {os.path.basename(filepath)} a {csv_filename}...")
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
        print(f"Error procesando {filepath}: {e}")

if __name__ == '__main__':
    # Clientes
    extract_table_to_csv(
        RUTA_CLIENTES, 
        "MAESTRO_CLIENTES.csv", 
        ["CLT_CODIGO", "CLT_DESCRIPCION", "CLT_RIF", "CLT_TELEFONO", "CLT_DIRECCION1"]
    )
    
    # Cabecera de Ventas
    extract_table_to_csv(
        RUTA_VENTAS, 
        "VENTAS_CABECERA.csv", 
        ["THT_AUTOINCREMENT", "THT_DOCUMENTO", "THT_FECHAEMISION", "THT_RIFCLIENTE", "THT_TOTALNETO", "THT_STATUS", "THT_NUMEROCONTROL", "THT_TOTALIMPUESTO"]
    )
    
    # Detalle de Ventas
    extract_table_to_csv(
        RUTA_VENTAS_DETALLE, 
        "VENTAS_DETALLE.csv", 
        ["TBT_AUTOINCREMENT", "TBT_DOCUMENTO", "TBT_CODIGO", "TBT_CANTIDAD", "TBT_PRECIODEVENTA", "TBT_CTOCOSTOSTR", "TBT_OPERACION_AUTOINCREMENT"]
    )
    print("Extracción completada.")
