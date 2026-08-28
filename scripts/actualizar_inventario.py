import struct
import re
import csv
import os
import math
import sys
from datetime import datetime

# ==========================================
#         CONFIGURACIÓN
# ==========================================
from config import RUTA_INVENTARIO, RUTA_PRECIOS, RUTA_EXISTENCIA

# Ruta de destino (CARPETA LOCAL DEL PROYECTO)
CARPETA_SALIDA = os.path.dirname(os.path.abspath(__file__))
# ==========================================

def esperar_salida():
    print("\n" + "="*40)
    input("Presione ENTER para cerrar esta ventana...")
    sys.exit()

def obtener_nombres_archivos():
    ahora = datetime.now()
    fecha_str = ahora.strftime("%Y-%m-%d_%H-%M")
    
    if not os.path.exists(CARPETA_SALIDA):
        try:
            os.makedirs(CARPETA_SALIDA)
        except:
            print(f"❌ Error: No puedo crear la carpeta {CARPETA_SALIDA}")
            esperar_salida()

    ruta_con_fecha = os.path.join(CARPETA_SALIDA, f"MAESTRO_SERRUCHO_{fecha_str}.csv")
    ruta_fija = os.path.join(CARPETA_SALIDA, "MAESTRO_ACTUAL.csv")
    
    return ruta_con_fecha, ruta_fija

def limpiar_texto(texto):
    # Usamos raw string (r'') para evitar el SyntaxWarning de la barrita \
    return re.sub(r'[^a-zA-Z0-9\s\.\-\/\+\*\(\)\,]', '', str(texto)).strip()

def leer_inventario_maestro(ruta):
    print(f"--- Leyendo CATALOGO desde: {ruta}...")
    if not os.path.exists(ruta): return {}
    productos = {}
    try:
        with open(ruta, 'rb') as f:
            contenido = f.read()
            # Usamos patrones binarios para evitar advertencias de escape
            tokens = [x.decode('latin-1', errors='ignore').strip() for x in re.findall(b'[\x20-\x7E\xA0-\xFF]{2,}', contenido)]
        i = 0
        unidades_validas = ['UND', 'PZA', 'MTS', 'KGS', 'JGO', 'LTS', 'GAL', 'PAR', 'SET', 'KIT', 'ROLLO', 'CAJA', 'LAT', 'BTO', 'M3', 'SAC']
        while i < len(tokens) - 2:
            token = tokens[i]
            if re.match(r'^[A-Z0-9\-\.]{1,15}$', token) and token not in unidades_validas:
                codigo = token
                if codigo in productos: 
                    i += 1
                    continue
                desc = "SIN DESCRIPCION"; unidad = "UND"; barra = "SIN_CODIGO"
                if i + 1 < len(tokens):
                    posible_desc = tokens[i+1]
                    if len(posible_desc) > 1 and posible_desc not in unidades_validas:
                        desc = posible_desc
                        for offset in range(2, 6):
                            if i + offset < len(tokens):
                                if tokens[i+offset] in unidades_validas:
                                    unidad = tokens[i+offset]
                                    if i + offset + 1 < len(tokens):
                                        raw_bar = tokens[i+offset+1]
                                        if len(raw_bar) >= 3 and raw_bar != '-1': barra = raw_bar
                                    break
                        if len(desc) >= 3:
                            desc = limpiar_texto(desc)
                            productos[codigo] = {'desc': desc, 'und': unidad, 'bar': barra}
                            i += 1
            i += 1
        return productos
    except Exception as e: print(f"--- Error: {e}"); return {}

def leer_precios_maestros(ruta, codigos_validos):
    print(f"--- Buscando PRECIOS...")
    if not os.path.exists(ruta): return {}
    precios_finales = {}
    try:
        with open(ruta, 'rb') as f:
            contenido = f.read()
            # Arreglado el patrón con b'' para evitar SyntaxWarning
            for match in re.finditer(b'[A-Z0-9\\-\\.\\s]{1,15}', contenido):
                try:
                    codigo = match.group().decode('ascii', errors='ignore').strip()
                    if codigo not in codigos_validos: continue
                    if codigo in precios_finales: continue
                    offset = match.start()
                    if offset + 459 > len(contenido): continue
                    c = struct.unpack('<d', contenido[offset+370 : offset+378])[0]
                    p = struct.unpack('<d', contenido[offset+451 : offset+459])[0]
                    
                    # Capping de seguridad
                    if math.isnan(c) or abs(c) > 1e14: c = 0.0
                    if math.isnan(p) or abs(p) > 1e14: p = 0.0
                    
                    precios_finales[codigo] = (round(c, 2), round(p, 2))
                except: pass
    except: return {}
    return precios_finales

def leer_existencias_maestras(ruta, codigos_validos):
    print(f"--- Buscando STOCK...")
    if not os.path.exists(ruta): return {}
    stock_final = {}
    try:
        with open(ruta, 'rb') as f:
            contenido = f.read()
            for match in re.finditer(b'[A-Z0-9\\-\\.\\s]{1,15}', contenido):
                try:
                    codigo = match.group().decode('ascii', errors='ignore').strip()
                    if codigo not in codigos_validos: continue
                    if codigo in stock_final: continue
                    offset = match.start()
                    if offset + 192 <= len(contenido):
                        val = struct.unpack('<d', contenido[offset+184 : offset+192])[0]
                        if not math.isnan(val) and abs(val) < 100000:
                            if abs(val) < 0.001: val = 0.0
                            stock_final[codigo] = val
                except: pass
    except: return {}
    return stock_final

def fusionar():
    ruta_fecha, ruta_fija = obtener_nombres_archivos()
    print(f"\n--- GENERANDO ARCHIVOS EN:\n    {CARPETA_SALIDA}")
    
    db_prods = leer_inventario_maestro(RUTA_INVENTARIO)
    if not db_prods: return False
    
    lista_codigos = set(db_prods.keys())
    db_prices = leer_precios_maestros(RUTA_PRECIOS, lista_codigos)
    db_stock  = leer_existencias_maestras(RUTA_EXISTENCIA, lista_codigos)
    
    filas_out = []
    for codigo, datos in db_prods.items():
        costo, precio = (0.0, 0.0)
        existencia = 0.0
        if codigo in db_prices: costo, precio = db_prices[codigo]
        if codigo in db_stock:  existencia = db_stock[codigo]
            
        filas_out.append({
            'CODIGO_INTERNO': codigo,
            'DESCRIPCION': datos['desc'],
            'UNIDAD': datos['und'],
            'CODIGO_BARRAS': datos['bar'],
            'COSTO': costo,
            'PRECIO_VENTA': precio,
            'EXISTENCIA': round(existencia, 2)
        })
    
    try:
        fieldnames = ['CODIGO_INTERNO', 'DESCRIPCION', 'UNIDAD', 'CODIGO_BARRAS', 'COSTO', 'PRECIO_VENTA', 'EXISTENCIA']
        for ruta in [ruta_fecha, ruta_fija]:
            with open(ruta, 'w', newline='', encoding='utf-8-sig') as f:
                # Delimitador coma (,) y comillas para las descripciones
                escritor = csv.DictWriter(f, fieldnames=fieldnames, delimiter=',', quoting=csv.QUOTE_MINIMAL)
                escritor.writeheader()
                escritor.writerows(filas_out)
            
        print("\n" + "="*40)
        print(f"--- EXITO! Sistema Actualizado.")
        print(f"--- Bot ahora leera CEMENTO con comas y comillas.")
        print("="*40)
        return True
        
    except PermissionError:
        print("❌ ERROR: Cierra el archivo Excel antes de ejecutar.")
        return False
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

def export_to_csv():
    """Alias para sync.py"""
    return fusionar()

if __name__ == "__main__":
    fusionar()
    # esperar_salida()