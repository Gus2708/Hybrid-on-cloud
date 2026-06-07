import os
import csv
import sys
import time
import pydbisam
from datetime import date
from lock_util import safe_replace

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

# ─── Reintento para operaciones de red/archivo ───────────────────────────────
_MAX_RETRIES = 3
_RETRY_DELAY = 2

def _safe_read_db(filepath: str, retries: int = _MAX_RETRIES):
    """Lee un archivo DBISAM con reintentos si la red/unidad falla."""
    for attempt in range(1, retries + 1):
        try:
            db = pydbisam.PyDBISAM(filepath)
            # Forzar lectura de metadatos para verificar que el archivo es accesible
            _ = db._row_size
            return db
        except Exception as e:
            err_str = str(e)
            if attempt < retries:
                print(f"  [RETRY {attempt}/{retries}] Error leyendo {os.path.basename(filepath)}: {err_str[:80]}")
                time.sleep(_RETRY_DELAY)
            else:
                raise

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

def process_inventory(force=False):
    print(f"--- Iniciando extracción profesional de inventario ---")
    
    # ─── Verificar unidad de red antes de operar ───────────────────────────
    for ruta in [RUTA_INVENTARIO, RUTA_PRECIOS, RUTA_EXISTENCIA]:
        if not os.path.exists(ruta):
            print(f"  [DRIVE] Archivo no accesible: {ruta}")
            print("  [DRIVE] Unidad H: no disponible. Abortando extracción.")
            return False
    
    if not force:
        rutas_criticas = [RUTA_INVENTARIO, RUTA_PRECIOS, RUTA_EXISTENCIA]
        if os.path.exists(ARCHIVO_SALIDA):
            csv_mtime = os.path.getmtime(ARCHIVO_SALIDA)
            has_changes = False
            for r in rutas_criticas:
                if os.path.exists(r) and os.path.getmtime(r) > csv_mtime:
                    has_changes = True
                    break
            if not has_changes:
                print("  [SKIP] Los archivos de inventario no han cambiado. Saltando extracción.")
                return True
    
    # 1. Leer Catálogo Maestro (con reintento)
    productos = {}
    print(f"  -> Procesando catálogo: {os.path.basename(RUTA_INVENTARIO)}...")
    try:
        db_inv = _safe_read_db(RUTA_INVENTARIO)
        for row in db_inv.rows():
            code = str(row[0]).strip()
            if not code or code == 'Fail': continue
            
            productos[code] = {
                'codigo': code,
                'desc': clean_val(row[1]),
                'und': clean_val(row[8]) if row[8] != 'Fail' else 'UND',
                'bar': clean_val(row[10]) if row[10] != 'Fail' and row[10] else 'SIN_CODIGO',
                'referencia': clean_val(row[10]) if row[10] != 'Fail' and row[10] else '',
                'costo': 0.0,
                'precio': 0.0,
                'existencia': 0.0
            }
        del db_inv
    except Exception as e:
        print(f"  ! Error crítico en catálogo: {e}")
        return False
    
    if not productos:
        print("  ! Catálogo vacío — abortando para no destruir datos en la nube.")
        return False
    
    # 2. Leer Precios y Costos (con reintento)
    print(f"  -> Procesando precios: {os.path.basename(RUTA_PRECIOS)}...")
    try:
        db_precios = _safe_read_db(RUTA_PRECIOS)
        for row in db_precios.rows():
            code = str(row[1]).strip()
            if code in productos:
                try:
                    raw_costo = str(row[4]).replace(',', '.') if row[4] != 'Fail' else '0.0'
                    raw_precio = str(row[13]).replace(',', '.') if row[13] != 'Fail' else '0.0'
                    productos[code]['costo'] = float(raw_costo)
                    productos[code]['precio'] = float(raw_precio)
                except Exception as e:
                    print(f"    ! Error parseando precios para {code}: {e} (Cost: {row[4]}, Price: {row[13]})")
        del db_precios
    except Exception as e:
        print(f"  ! Error en precios (se continúa con datos parciales): {e}")

    # 3. Leer Existencias (con reintento)
    print(f"  -> Procesando existencias: {os.path.basename(RUTA_EXISTENCIA)}...")
    try:
        db_stock = _safe_read_db(RUTA_EXISTENCIA)
        for row in db_stock.rows():
            code = str(row[1]).strip()
            if code in productos:
                try:
                    raw_stock = str(row[8]).replace(',', '.') if row[8] != 'Fail' else '0.0'
                    productos[code]['existencia'] += float(raw_stock)
                except Exception as e:
                    print(f"    ! Error parseando existencia para {code}: {e} (Stock: {row[8]})")
        del db_stock
    except Exception as e:
        print(f"  ! Error en existencias (se continúa con datos parciales): {e}")

    # 4. Generar CSV
    print(f"  -> Generando {ARCHIVO_SALIDA}...")
    tmp_salida = ARCHIVO_SALIDA + ".tmp"
    try:
        with open(tmp_salida, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['CODIGO_INTERNO', 'DESCRIPCION', 'UNIDAD', 'CODIGO_BARRAS', 'REFERENCIA', 'COSTO', 'PRECIO_VENTA', 'EXISTENCIA'])
            
            count = 0
            for code in sorted(productos.keys()):
                p = productos[code]
                if len(p['codigo']) < 2 or p['desc'] == 'SIN DESCRIPCION': continue
                
                writer.writerow([p['codigo'], p['desc'], p['und'], p['bar'], p['referencia'], p['costo'], p['precio'], p['existencia']])
                count += 1
        
        if safe_replace(tmp_salida, ARCHIVO_SALIDA):
            print(f"--- ÉXITO: {count} productos exportados correctamente ---")
            return True
        else:
            raise IOError("No se pudo reemplazar el archivo debido a bloqueos de Windows.")
    except Exception as e:
        if os.path.exists(tmp_salida): os.remove(tmp_salida)
        print(f"  ! Error guardando CSV: {e}")
        return False

if __name__ == "__main__":
    import sys
    force = len(sys.argv) > 1 and sys.argv[1] == "force"
    process_inventory(force=force)