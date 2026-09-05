import json
import math
import pandas as pd

# Cargar el maestro actual
df = pd.read_csv('MAESTRO_ACTUAL.csv', encoding='utf-8-sig', on_bad_lines='skip')
maestro = {}
for _, r in df.iterrows():
    cod = str(r['CODIGO_INTERNO']).strip()
    maestro[cod] = {
        "codigo": cod,
        "descripcion": str(r['DESCRIPCION']).strip(),
        "costo_actual": float(r['COSTO']) if pd.notna(r['COSTO']) else 0.0,
        "precio_actual": float(r['PRECIO_VENTA']) if pd.notna(r['PRECIO_VENTA']) else 0.0
    }

# Función smart_round idéntica a widget.pyw
def smart_round(val):
    integer_part = int(val)
    dec = val - integer_part
    if dec <= 0.15:
        return float(integer_part)
    elif dec <= 0.65:
        return integer_part + 0.5
    else:
        return float(integer_part + 1)

# Lista completa de los 66 renglones de las 3 páginas
items_facturas = [
    # PAGINA 1 - Nota M000003215
    {"pagina": 1, "codigo": "F-404-01", "desc_factura": "HOGAR MELOCOTON GAL", "cant": 4.0, "precio_unit": 7.40, "total_fac": 29.60, "clase": "Clase C (Hogar)", "tipo": "Galón", "color": "MELOCOTON"},
    {"pagina": 1, "codigo": "F-401-01", "desc_factura": "HOGAR BLANCO NIEVE GAL", "cant": 16.0, "precio_unit": 7.40, "total_fac": 118.40, "clase": "Clase C (Hogar)", "tipo": "Galón", "color": "BLANCO NIEVE"},
    {"pagina": 1, "codigo": "F-402-01", "desc_factura": "HOGAR BEIGE GAL", "cant": 4.0, "precio_unit": 7.40, "total_fac": 29.60, "clase": "Clase C (Hogar)", "tipo": "Galón", "color": "BEIGE"},
    {"pagina": 1, "codigo": "F-405-01", "desc_factura": "HOGAR AZUL MAR GAL", "cant": 8.0, "precio_unit": 7.40, "total_fac": 59.20, "clase": "Clase C (Hogar)", "tipo": "Galón", "color": "AZUL MAR"},
    {"pagina": 1, "codigo": "F-408-01", "desc_factura": "HOGAR CANARIO GAL", "cant": 4.0, "precio_unit": 7.40, "total_fac": 29.60, "clase": "Clase C (Hogar)", "tipo": "Galón", "color": "CANARIO"},
    {"pagina": 1, "codigo": "F-406-01", "desc_factura": "HOGAR AGUAMARINA GAL", "cant": 4.0, "precio_unit": 7.40, "total_fac": 29.60, "clase": "Clase C (Hogar)", "tipo": "Galón", "color": "AGUAMARINA"},
    {"pagina": 1, "codigo": "F-407-01", "desc_factura": "HOGAR ROCIO GAL", "cant": 4.0, "precio_unit": 7.40, "total_fac": 29.60, "clase": "Clase C (Hogar)", "tipo": "Galón", "color": "ROCIO"},
    {"pagina": 1, "codigo": "F-403-01", "desc_factura": "HOGAR CELESTE GAL", "cant": 4.0, "precio_unit": 7.40, "total_fac": 29.60, "clase": "Clase C (Hogar)", "tipo": "Galón", "color": "CELESTE"},
    {"pagina": 1, "codigo": "F-409-01", "desc_factura": "HOGAR DURAZNO GAL", "cant": 4.0, "precio_unit": 7.40, "total_fac": 29.60, "clase": "Clase C (Hogar)", "tipo": "Galón", "color": "DURAZNO"},
    {"pagina": 1, "codigo": "F-401-04", "desc_factura": "HOGAR BLANCO NIEVE CNT", "cant": 4.0, "precio_unit": 24.60, "total_fac": 98.40, "clase": "Clase C (Hogar)", "tipo": "Cuñete", "color": "BLANCO NIEVE"},
    {"pagina": 1, "codigo": "F-402-05", "desc_factura": "HOGAR BEIGE CNT", "cant": 4.0, "precio_unit": 24.60, "total_fac": 98.40, "clase": "Clase C (Hogar)", "tipo": "Cuñete", "color": "BEIGE"},
    {"pagina": 1, "codigo": "F-411-04", "desc_factura": "HOGAR GRIS HUMO CNT", "cant": 2.0, "precio_unit": 24.60, "total_fac": 49.20, "clase": "Clase C (Hogar)", "tipo": "Cuñete", "color": "GRIS HUMO"},
    {"pagina": 1, "codigo": "F-405-04", "desc_factura": "HOGAR AZUL MAR CNT", "cant": 2.0, "precio_unit": 24.60, "total_fac": 49.20, "clase": "Clase C (Hogar)", "tipo": "Cuñete", "color": "AZUL MAR"},
    {"pagina": 1, "codigo": "F-404-05", "desc_factura": "HOGAR MELOCOTON CNT", "cant": 2.0, "precio_unit": 24.60, "total_fac": 49.20, "clase": "Clase C (Hogar)", "tipo": "Cuñete", "color": "MELOCOTON"},
    {"pagina": 1, "codigo": "F-410-05", "desc_factura": "HOGAR LIMONADA CNT", "cant": 1.0, "precio_unit": 24.60, "total_fac": 24.60, "clase": "Clase C (Hogar)", "tipo": "Cuñete", "color": "LIMONADA"},
    {"pagina": 1, "codigo": "F-406-04", "desc_factura": "HOGAR AGUAMARINA CNT", "cant": 1.0, "precio_unit": 24.60, "total_fac": 24.60, "clase": "Clase C (Hogar)", "tipo": "Cuñete", "color": "AGUAMARINA"},

    # PAGINA 2 - Nota M000003214 (Parte 1)
    {"pagina": 2, "codigo": "F-316-01", "desc_factura": "SATINADO OCRE GAL", "cant": 4.0, "precio_unit": 20.35, "total_fac": 81.40, "clase": "Satinado", "tipo": "Galón", "color": "OCRE"},
    {"pagina": 2, "codigo": "F-301-01", "desc_factura": "SATINADO BLANCO GAL", "cant": 8.0, "precio_unit": 20.35, "total_fac": 162.80, "clase": "Satinado", "tipo": "Galón", "color": "BLANCO"},
    {"pagina": 2, "codigo": "F-302-01", "desc_factura": "SATINADO MARFIL GAL", "cant": 8.0, "precio_unit": 20.35, "total_fac": 162.80, "clase": "Satinado", "tipo": "Galón", "color": "MARFIL"},
    {"pagina": 2, "codigo": "F-304-01", "desc_factura": "SATINADO BLANCO OSTRA GAL", "cant": 8.0, "precio_unit": 20.35, "total_fac": 162.80, "clase": "Satinado", "tipo": "Galón", "color": "BLANCO OSTRA"},
    {"pagina": 2, "codigo": "F-303-01", "desc_factura": "SATINADO SALMON GAL", "cant": 4.0, "precio_unit": 20.35, "total_fac": 81.40, "clase": "Satinado", "tipo": "Galón", "color": "SALMON"},
    {"pagina": 2, "codigo": "F-310-01", "desc_factura": "SATINADO MANZANA GAL", "cant": 4.0, "precio_unit": 20.35, "total_fac": 81.40, "clase": "Satinado", "tipo": "Galón", "color": "MANZANA"},
    {"pagina": 2, "codigo": "F-307-01", "desc_factura": "SATINADO ROSA PASTEL GAL", "cant": 4.0, "precio_unit": 20.35, "total_fac": 81.40, "clase": "Satinado", "tipo": "Galón", "color": "ROSA PASTEL"},
    {"pagina": 2, "codigo": "F-301-04", "desc_factura": "SATINADO BLANCO CNT", "cant": 2.0, "precio_unit": 79.20, "total_fac": 158.40, "clase": "Satinado", "tipo": "Cuñete", "color": "BLANCO"},
    {"pagina": 2, "codigo": "F-302-04", "desc_factura": "SATINADO MARFIL CNT", "cant": 2.0, "precio_unit": 79.20, "total_fac": 158.40, "clase": "Satinado", "tipo": "Cuñete", "color": "MARFIL"},
    {"pagina": 2, "codigo": "F-354-01", "desc_factura": "PREMIUM VERDE MORICHAL GAL", "cant": 4.0, "precio_unit": 15.73, "total_fac": 62.92, "clase": "Clase A (Premium)", "tipo": "Galón", "color": "VERDE MORICHAL"},
    {"pagina": 2, "codigo": "F-362-01", "desc_factura": "PREMIUM VIOLETA GAL", "cant": 4.0, "precio_unit": 15.73, "total_fac": 62.92, "clase": "Clase A (Premium)", "tipo": "Galón", "color": "VIOLETA"},
    {"pagina": 2, "codigo": "F-352-01", "desc_factura": "PREMIUM MARFIL GAL", "cant": 4.0, "precio_unit": 15.73, "total_fac": 62.92, "clase": "Clase A (Premium)", "tipo": "Galón", "color": "MARFIL"},
    {"pagina": 2, "codigo": "F-352-04", "desc_factura": "PREMIUM MARFIL CNT", "cant": 2.0, "precio_unit": 57.20, "total_fac": 114.40, "clase": "Clase A (Premium)", "tipo": "Cuñete", "color": "MARFIL"},
    {"pagina": 2, "codigo": "F-351-04", "desc_factura": "PREMIUM BLANCO CNT", "cant": 2.0, "precio_unit": 57.20, "total_fac": 114.40, "clase": "Clase A (Premium)", "tipo": "Cuñete", "color": "BLANCO"},
    {"pagina": 2, "codigo": "F-136-01", "desc_factura": "CAUCHO FLORAL GAL", "cant": 4.0, "precio_unit": 9.20, "total_fac": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón", "color": "FLORAL"},
    {"pagina": 2, "codigo": "F-103-01", "desc_factura": "CAUCHO MELON GAL", "cant": 4.0, "precio_unit": 9.20, "total_fac": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón", "color": "MELON"},
    {"pagina": 2, "codigo": "F-105-01", "desc_factura": "CAUCHO GRIS CLARO GAL", "cant": 4.0, "precio_unit": 9.20, "total_fac": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón", "color": "GRIS CLARO"},
    {"pagina": 2, "codigo": "F-115-01", "desc_factura": "CAUCHO ORQUIDEA GAL", "cant": 4.0, "precio_unit": 9.20, "total_fac": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón", "color": "ORQUIDEA"},
    {"pagina": 2, "codigo": "F-101-01", "desc_factura": "CAUCHO BLANCO GAL", "cant": 8.0, "precio_unit": 9.20, "total_fac": 73.60, "clase": "Clase B (Caucho)", "tipo": "Galón", "color": "BLANCO"},
    {"pagina": 2, "codigo": "F-129-01", "desc_factura": "CAUCHO GIRASOL GAL", "cant": 4.0, "precio_unit": 9.20, "total_fac": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón", "color": "GIRASOL"},
    {"pagina": 2, "codigo": "F-118-01", "desc_factura": "CAUCHO AZUL BAHIA GAL", "cant": 8.0, "precio_unit": 9.20, "total_fac": 73.60, "clase": "Clase B (Caucho)", "tipo": "Galón", "color": "AZUL BAHIA"},
    {"pagina": 2, "codigo": "F-118-04", "desc_factura": "CAUCHO AZUL BAHIA CNT", "cant": 2.0, "precio_unit": 34.50, "total_fac": 69.00, "clase": "Clase B (Caucho)", "tipo": "Cuñete", "color": "AZUL BAHIA"},
    {"pagina": 2, "codigo": "F-130-01", "desc_factura": "CAUCHO FUCSIA GAL", "cant": 4.0, "precio_unit": 9.20, "total_fac": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón", "color": "FUCSIA"},
    {"pagina": 2, "codigo": "F-112-01", "desc_factura": "CAUCHO CREPUSCULO GAL", "cant": 4.0, "precio_unit": 9.20, "total_fac": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón", "color": "CREPUSCULO"},
    {"pagina": 2, "codigo": "F-112-04", "desc_factura": "CAUCHO CREPUSCULO CNT", "cant": 1.0, "precio_unit": 34.50, "total_fac": 34.50, "clase": "Clase B (Caucho)", "tipo": "Cuñete", "color": "CREPUSCULO"},
    {"pagina": 2, "codigo": "F-121-01", "desc_factura": "CAUCHO AZUL CIELO GAL", "cant": 4.0, "precio_unit": 9.20, "total_fac": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón", "color": "AZUL CIELO"},
    {"pagina": 2, "codigo": "F-102-01", "desc_factura": "CAUCHO MARFIL CLASICO GAL", "cant": 4.0, "precio_unit": 9.20, "total_fac": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón", "color": "MARFIL CLASICO"},
    {"pagina": 2, "codigo": "F-128-01", "desc_factura": "CAUCHO MARFIL GAL", "cant": 8.0, "precio_unit": 9.20, "total_fac": 73.60, "clase": "Clase B (Caucho)", "tipo": "Galón", "color": "MARFIL"},
    {"pagina": 2, "codigo": "F-104-01", "desc_factura": "CAUCHO GREIGE GAL", "cant": 4.0, "precio_unit": 9.20, "total_fac": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón", "color": "GREIGE"},
    {"pagina": 2, "codigo": "F-116-01", "desc_factura": "CAUCHO AZUL OSCURO GAL", "cant": 4.0, "precio_unit": 9.20, "total_fac": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón", "color": "AZUL OSCURO"},
    {"pagina": 2, "codigo": "F-123-01", "desc_factura": "CAUCHO VERDE ALEGRIA GAL", "cant": 4.0, "precio_unit": 9.20, "total_fac": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón", "color": "VERDE ALEGRIA"},

    # PAGINA 3 - Nota M000003214 (Parte 2)
    {"pagina": 3, "codigo": "F-123-04", "desc_factura": "CAUCHO VERDE ALEGRIA CNT", "cant": 1.0, "precio_unit": 34.50, "total_fac": 34.50, "clase": "Clase B (Caucho)", "tipo": "Cuñete", "color": "VERDE ALEGRIA"},
    {"pagina": 3, "codigo": "F-133-04", "desc_factura": "CAUCHO BLANCO OSTRA CNT", "cant": 2.0, "precio_unit": 34.50, "total_fac": 69.00, "clase": "Clase B (Caucho)", "tipo": "Cuñete", "color": "BLANCO OSTRA"},
    {"pagina": 3, "codigo": "F-134-04", "desc_factura": "CAUCHO ESMERALDA CNT", "cant": 1.0, "precio_unit": 34.50, "total_fac": 34.50, "clase": "Clase B (Caucho)", "tipo": "Cuñete", "color": "ESMERALDA"},
    {"pagina": 3, "codigo": "F-119-04", "desc_factura": "CAUCHO TURQUESA CNT", "cant": 1.0, "precio_unit": 34.50, "total_fac": 34.50, "clase": "Clase B (Caucho)", "tipo": "Cuñete", "color": "TURQUESA"},
    {"pagina": 3, "codigo": "F-418-05", "desc_factura": "SAT HOGAR LILA GAL", "cant": 4.0, "precio_unit": 15.95, "total_fac": 63.80, "clase": "Satinado Hogar", "tipo": "Galón", "color": "LILA"},
    {"pagina": 3, "codigo": "F-414-05", "desc_factura": "SAT HOGAR FLAMINGO GAL", "cant": 4.0, "precio_unit": 15.95, "total_fac": 63.80, "clase": "Satinado Hogar", "tipo": "Galón", "color": "FLAMINGO"},
    {"pagina": 3, "codigo": "F-416-05", "desc_factura": "SAT. HOGAR ZAFIRO GAL", "cant": 4.0, "precio_unit": 15.95, "total_fac": 63.80, "clase": "Satinado Hogar", "tipo": "Galón", "color": "ZAFIRO"},
    {"pagina": 3, "codigo": "F-830-01", "desc_factura": "2 EN 1 GRIS GALON", "cant": 8.0, "precio_unit": 21.23, "total_fac": 169.84, "clase": "Esmalte 2 en 1", "tipo": "Galón", "color": "GRIS"},
    {"pagina": 3, "codigo": "F-830-04", "desc_factura": "2 EN 1 GRIS 1/4", "cant": 12.0, "precio_unit": 6.60, "total_fac": 79.20, "clase": "Esmalte 2 en 1", "tipo": "1/4 Galón", "color": "GRIS"},
    {"pagina": 3, "codigo": "F-721-04", "desc_factura": "BARNIZ CAOBA CLARO 1/4", "cant": 12.0, "precio_unit": 7.37, "total_fac": 88.44, "clase": "Barniz", "tipo": "1/4 Galón", "color": "CAOBA CLARO"},
    {"pagina": 3, "codigo": "F-722-04", "desc_factura": "BARNIZ CAOBA OSCURO 1/4", "cant": 12.0, "precio_unit": 7.37, "total_fac": 88.44, "clase": "Barniz", "tipo": "1/4 Galón", "color": "CAOBA OSCURO"},
    {"pagina": 3, "codigo": "F-722-01", "desc_factura": "BARNIZ CAOBA OSCURO GAL", "cant": 4.0, "precio_unit": 24.75, "total_fac": 99.00, "clase": "Barniz", "tipo": "Galón", "color": "CAOBA OSCURO"},
    {"pagina": 3, "codigo": "F-721-01", "desc_factura": "BARNIZ CAOBA CLARO GAL", "cant": 4.0, "precio_unit": 24.75, "total_fac": 99.00, "clase": "Barniz", "tipo": "Galón", "color": "CAOBA CLARO"},
    {"pagina": 3, "codigo": "THINNER-01", "desc_factura": "SOLVENTE MULTIUSO FLORIPAINT", "cant": 24.0, "precio_unit": 3.50, "total_fac": 84.00, "clase": "Solvente", "tipo": "Litro / Botella", "color": "MULTIUSO"},
    {"pagina": 3, "codigo": "F-790-04", "desc_factura": "PASTA PROFESIONAL CNT", "cant": 6.0, "precio_unit": 27.39, "total_fac": 164.34, "clase": "Pasta Profesional", "tipo": "Cuñete", "color": "BLANCO"},
    {"pagina": 3, "codigo": "F-790-01", "desc_factura": "PASTA PROFESIONAL GAL", "cant": 8.0, "precio_unit": 7.59, "total_fac": 60.72, "clase": "Pasta Profesional", "tipo": "Galón", "color": "BLANCO"},
    {"pagina": 3, "codigo": "F-790-05", "desc_factura": "PASTA PROFESIONAL 1/4", "cant": 12.0, "precio_unit": 2.75, "total_fac": 33.00, "clase": "Pasta Profesional", "tipo": "1/4 Galón", "color": "BLANCO"},
    {"pagina": 3, "codigo": "F-789-01", "desc_factura": "ANTIALCALINO GAL", "cant": 4.0, "precio_unit": 12.43, "total_fac": 49.72, "clase": "Antialcalino", "tipo": "Galón", "color": "BLANCO"},
    {"pagina": 3, "codigo": "F-789-02", "desc_factura": "ANTIALCALINO 1/4", "cant": 6.0, "precio_unit": 3.85, "total_fac": 23.10, "clase": "Antialcalino", "tipo": "1/4 Galón", "color": "BLANCO"},
]

def generar_nombre_estandar(item):
    clase = item['clase']
    tipo = item['tipo']
    color = item['color']
    
    tipo_str = "GAL" if tipo == "Galón" else ("CUNETE" if tipo == "Cuñete" else "1/4")
    
    if clase == "Clase C (Hogar)":
        return f"PINTURA CAUCHO {color} C {tipo_str} FLORIPAINT"
    elif clase == "Clase B (Caucho)":
        return f"PINTURA CAUCHO {color} B {tipo_str} FLORIPAINT"
    elif clase == "Satinado":
        return f"PINTURA SATINADA {color} {tipo_str} FLORIPAINT"
    elif clase == "Clase A (Premium)":
        if tipo == "Cuñete":
            return f"PINTURA {color} PREMIUN FLORIPAINT CUNETE"
        else:
            return f"PINTURA PREMIUM {color} GAL FLORIPAINT"
    elif clase == "Satinado Hogar":
        return f"PINTURA SATINADA HOGAR {color} GAL FLORIPAINT"
    elif clase == "Esmalte 2 en 1":
        return f"PINTURA ESMALTE 2 EN 1 {color} {tipo_str} FLORIPAINT"
    elif clase == "Barniz":
        return f"BARNIZ {color} {tipo_str} FLORIPAINT"
    elif clase == "Pasta Profesional":
        return f"PASTA PROFESIONAL {tipo_str} FLORIPAINT"
    elif clase == "Antialcalino":
        return f"PINTURA ANTIALCALINO {tipo_str} FLORIPAINT"
    elif clase == "Solvente":
        return "SOLVENTE MULTIUSO FLORIPAINT"
    return item['desc_factura']

lista_final = []

for it in items_facturas:
    cod = it['codigo']
    esta = cod in maestro
    p_fac = it['precio_unit']
    desc = 0.35 if 'Clase C' in it['clase'] else 0.25
    raw_cost = (p_fac * 1.16) * (1 - desc)
    costo = 5.57 if (p_fac == 7.40 and desc == 0.35) else round(raw_cost, 2)
    p25 = float(math.ceil(costo * 1.25))
    p30 = float(math.ceil(costo * 1.30))
    
    if esta:
        nombre_sistema = maestro[cod]['descripcion']
        estado = "EN SISTEMA"
    else:
        nombre_sistema = generar_nombre_estandar(it)
        estado = "NUEVO (NO ESTA)"
        
    lista_final.append({
        "codigo": cod,
        "descripcion_factura": it['desc_factura'],
        "descripcion_sistema": nombre_sistema,
        "estado": estado,
        "clase": it['clase'],
        "tipo": it['tipo'],
        "cantidad": it['cant'],
        "precio_factura": it['precio_unit'],
        "descuento_proveedor": desc,
        "costo_neto_menos_35": costo,
        "costo": costo,
        "precio_venta_sugerido_25": p25,
        "precio_venta_30": p30,
        "pagina": it['pagina']
    })

# Guardar en archivo JSON
with open('c:/Proyect/backend serrucho/scratch/floripaint_procesado.json', 'w', encoding='utf-8') as f:
    json.dump(lista_final, f, indent=2, ensure_ascii=False)

print("JSON generado exitosamente con", len(lista_final), "elementos.")

groups = {}
for item in lista_final:
    k = (item['clase'], item['tipo'])
    if k not in groups:
        groups[k] = {
            'precio_factura': item['precio_factura'],
            'costo': item['costo_neto_menos_35'],
            'precio_25': item['precio_venta_sugerido_25'],
            'precio_30': item['precio_venta_30'],
            'total_items': 0,
            'en_sistema': 0,
            'nuevos': 0,
        }
    groups[k]['total_items'] += 1
    if item['estado'] == 'EN SISTEMA':
        groups[k]['en_sistema'] += 1
    else:
        groups[k]['nuevos'] += 1

print("\n=== TABLA RESUMEN POR CLASE Y TIPO ===")
header = f"{'CLASE':<22} | {'TIPO':<10} | {'FAC ($)':<8} | {'COSTO (-35%)':<12} | {'PRECIO (25%)':<12} | {'PRECIO (30%)':<12} | {'TOTAL':<5} | {'EN SIST':<7} | {'NUEVOS':<6}"
print(header)
print("-" * len(header))
for (clase, tipo), v in groups.items():
    print(f"{clase:<22} | {tipo:<10} | {v['precio_factura']:<8.2f} | {v['costo']:<12.2f} | {v['precio_25']:<12.2f} | {v['precio_30']:<12.2f} | {v['total_items']:<5} | {v['en_sistema']:<7} | {v['nuevos']:<6}")

print("\n=== ITEMS NUEVOS (NO ESTÁN EN EL SISTEMA) ===")
nuevos = [x for x in lista_final if x['estado'] != 'EN SISTEMA']
for x in nuevos:
    print(f"{x['codigo']:<10} | {x['clase']:<18} | {x['tipo']:<10} | {x['descripcion_factura']:<26} -> {x['descripcion_sistema']}")

print("\n=== ITEMS YA EXISTENTES EN EL SISTEMA ===")
existentes = [x for x in lista_final if x['estado'] == 'EN SISTEMA']
for x in existentes:
    print(f"{x['codigo']:<10} | {x['clase']:<18} | {x['tipo']:<10} | Factura: {x['descripcion_factura']:<26} -> Sistema: {x['descripcion_sistema']}")


