import csv
import os

CSV_PATH = r"C:\Users\OFICINA\Clawdbot\scripts\MAESTRO_ACTUAL.csv"

def find_overflow_row():
    if not os.path.exists(CSV_PATH):
        print("CSV no encontrado")
        return

    with open(CSV_PATH, 'r', encoding='utf-8-sig', errors='ignore') as f:
        reader = csv.reader(f)
        header = next(reader)
        
        # El error ocurre en el Batch 14 (filas 6501 en adelante)
        for i, row in enumerate(reader, start=2):
            if i < 6500:
                continue
            
            if len(row) < 7:
                continue
                
            # Revisar columnas numéricas (4, 5, 6) -> COSTO, PRECIO_VENTA, EXISTENCIA
            for col_idx in [4, 5, 6]:
                try:
                    val_str = row[col_idx].strip()
                    if val_str:
                        val = float(val_str)
                        # Si el valor es absurdamente grande (ej. > 1 billón)
                        if val > 1_000_000_000_000:
                            print(f"\n[!] FILA {i} SOSPECHOSA:")
                            print(f"    Código: {row[0]}")
                            print(f"    Desc:   {row[1]}")
                            print(f"    Columna {col_idx} ({header[col_idx]}): {val_str}")
                except:
                    pass

if __name__ == "__main__":
    find_overflow_row()
