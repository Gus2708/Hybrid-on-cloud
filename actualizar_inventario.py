import os
import csv
import sys
import pydbisam
from datetime import date

# ==========================================
#         CONFIGURACIÓN
# ==========================================
try:
    from config import RUTA_INVENTARIO, RUTA_PRECIOS, RUTA_EXISTENCIA
except ImportError:
    RUTA_INVENTARIO = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TInventario.dat'
    RUTA_PRECIOS    = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TCostoPrecioInv.Dat'
    RUTA_EXISTENCIA = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TExistenciaInv.Dat'

CARPETA_SALIDA = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_SALIDA = os.path.join(CARPETA_SALIDA, "MAESTRO_ACTUAL.csv")
# ==========================================

def clean_val(val):
    if isinstance(val, str):
        # Eliminar caracteres nulos y limpiar espacios
        val = val.replace('\x00', '').strip()
        return val.replace('"', '').replace('\r', '').replace('\n', ' ')
    if isinstance(val, date):
        return val.strftime('%Y-%m-%d')
    if val == 'Fail':
        return ''
    return val

def process_inventory():
    print(f"--- Iniciando extracción profesional de inventario ---")
    
    # 1. Leer Catálogo Maestro
    productos = {}
    print(f"  -> Procesando catálogo: {os.path.basename(RUTA_INVENTARIO)}...")
    try:
        db_inv = pydbisam.PyDBISAM(RUTA_INVENTARIO)
        # Columnas: PRD_CODIGO (0), PRD_DESCRIPCION (1), PRD_UNIDAD (8), PRD_REFERENCIA (10)
        for row in db_inv.rows():
            code = str(row[0]).strip()
            if not code or code == 'Fail': continue
            
            productos[code] = {
                'codigo': code,
                'desc': clean_val(row[1]),
                'und': clean_val(row[8]) if row[8] != 'Fail' else 'UND',
                'bar': clean_val(row[10]) if row[10] != 'Fail' and row[10] else 'SIN_CODIGO',
                'costo': 0.0,
                'precio': 0.0,
                'existencia': 0.0
            }
    except Exception as e:
        print(f"  ! Error crítico en catálogo: {e}")
        return

    # 2. Leer Precios y Costos
    print(f"  -> Procesando precios: {os.path.basename(RUTA_PRECIOS)}...")
    try:
        db_precios = pydbisam.PyDBISAM(RUTA_PRECIOS)
        # TPC_CODIGOPRODUCTO (1), TPC_COSTOACTUAL (4), TPC_PVPSINIMPUESTO1 (7)
        for row in db_precios.rows():
            code = str(row[1]).strip()
            if code in productos:
                try:
                    costo = float(row[4]) if row[4] != 'Fail' else 0.0
                    precio = float(row[7]) if row[7] != 'Fail' else 0.0
                    productos[code]['costo'] = costo
                    productos[code]['precio'] = precio
                except: pass
    except Exception as e:
        print(f"  ! Advertencia en precios: {e}")

    # 3. Leer Existencias (Suma por código)
    print(f"  -> Procesando existencias: {os.path.basename(RUTA_EXISTENCIA)}...")
    try:
        db_stock = pydbisam.PyDBISAM(RUTA_EXISTENCIA)
        # EIN_CODIGOPRODUCTO (1), EIN_EXISTENCIA (8)
        for row in db_stock.rows():
            code = str(row[1]).strip()
            if code in productos:
                try:
                    stock = float(row[8]) if row[8] != 'Fail' else 0.0
                    productos[code]['existencia'] += stock
                except: pass
    except Exception as e:
        print(f"  ! Advertencia en existencias: {e}")

    # 4. Generar CSV
    print(f"  -> Generando {ARCHIVO_SALIDA}...")
    try:
        with open(ARCHIVO_SALIDA, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['CODIGO_INTERNO', 'DESCRIPCION', 'UNIDAD', 'CODIGO_BARRAS', 'COSTO', 'PRECIO_VENTA', 'EXISTENCIA'])
            
            count = 0
            for code in sorted(productos.keys()):
                p = productos[code]
                # Filtro básico de seguridad: no exportar basura
                if len(p['codigo']) < 2 or p['desc'] == 'SIN DESCRIPCION':
                    continue
                
                writer.writerow([
                    p['codigo'],
                    p['desc'],
                    p['und'],
                    p['bar'],
                    p['costo'],
                    p['precio'],
                    p['existencia']
                ])
                count += 1
        print(f"--- ÉXITO: {count} productos exportados correctamente ---")
    except Exception as e:
        print(f"  ! Error guardando CSV: {e}")

if __name__ == "__main__":
    process_inventory()