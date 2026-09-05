import pandas as pd
import json

# Cargar maestro actual
df = pd.read_csv('MAESTRO_ACTUAL.csv', encoding='utf-8-sig', on_bad_lines='skip')
maestro_dict = {}
for _, row in df.iterrows():
    c = str(row['CODIGO_INTERNO']).strip()
    maestro_dict[c] = {
        'codigo': c,
        'descripcion': str(row['DESCRIPCION']).strip(),
        'costo': float(row['COSTO']) if pd.notna(row['COSTO']) else 0.0,
        'precio_venta': float(row['PRECIO_VENTA']) if pd.notna(row['PRECIO_VENTA']) else 0.0
    }

# Definir todos los items de la nota de entrega
items_factura = [
    # --- PAGINA 1 (Nota M000003215) ---
    {"pagina": 1, "codigo": "F-404-01", "desc_factura": "HOGAR MELOCOTON GAL", "cant": 4.0, "precio_unit": 7.40, "total": 29.60, "clase": "Clase C (Hogar)", "tipo": "Galón"},
    {"pagina": 1, "codigo": "F-401-01", "desc_factura": "HOGAR BLANCO NIEVE GAL", "cant": 16.0, "precio_unit": 7.40, "total": 118.40, "clase": "Clase C (Hogar)", "tipo": "Galón"},
    {"pagina": 1, "codigo": "F-402-01", "desc_factura": "HOGAR BEIGE GAL", "cant": 4.0, "precio_unit": 7.40, "total": 29.60, "clase": "Clase C (Hogar)", "tipo": "Galón"},
    {"pagina": 1, "codigo": "F-405-01", "desc_factura": "HOGAR AZUL MAR GAL", "cant": 8.0, "precio_unit": 7.40, "total": 59.20, "clase": "Clase C (Hogar)", "tipo": "Galón"},
    {"pagina": 1, "codigo": "F-408-01", "desc_factura": "HOGAR CANARIO GAL", "cant": 4.0, "precio_unit": 7.40, "total": 29.60, "clase": "Clase C (Hogar)", "tipo": "Galón"},
    {"pagina": 1, "codigo": "F-406-01", "desc_factura": "HOGAR AGUAMARINA GAL", "cant": 4.0, "precio_unit": 7.40, "total": 29.60, "clase": "Clase C (Hogar)", "tipo": "Galón"},
    {"pagina": 1, "codigo": "F-407-01", "desc_factura": "HOGAR ROCIO GAL", "cant": 4.0, "precio_unit": 7.40, "total": 29.60, "clase": "Clase C (Hogar)", "tipo": "Galón"},
    {"pagina": 1, "codigo": "F-403-01", "desc_factura": "HOGAR CELESTE GAL", "cant": 4.0, "precio_unit": 7.40, "total": 29.60, "clase": "Clase C (Hogar)", "tipo": "Galón"},
    {"pagina": 1, "codigo": "F-409-01", "desc_factura": "HOGAR DURAZNO GAL", "cant": 4.0, "precio_unit": 7.40, "total": 29.60, "clase": "Clase C (Hogar)", "tipo": "Galón"},
    {"pagina": 1, "codigo": "F-401-04", "desc_factura": "HOGAR BLANCO NIEVE CNT", "cant": 4.0, "precio_unit": 24.60, "total": 98.40, "clase": "Clase C (Hogar)", "tipo": "Cuñete"},
    {"pagina": 1, "codigo": "F-402-05", "desc_factura": "HOGAR BEIGE CNT", "cant": 4.0, "precio_unit": 24.60, "total": 98.40, "clase": "Clase C (Hogar)", "tipo": "Cuñete"},
    {"pagina": 1, "codigo": "F-411-04", "desc_factura": "HOGAR GRIS HUMO CNT", "cant": 2.0, "precio_unit": 24.60, "total": 49.20, "clase": "Clase C (Hogar)", "tipo": "Cuñete"},
    {"pagina": 1, "codigo": "F-405-04", "desc_factura": "HOGAR AZUL MAR CNT", "cant": 2.0, "precio_unit": 24.60, "total": 49.20, "clase": "Clase C (Hogar)", "tipo": "Cuñete"},
    {"pagina": 1, "codigo": "F-404-05", "desc_factura": "HOGAR MELOCOTON CNT", "cant": 2.0, "precio_unit": 24.60, "total": 49.20, "clase": "Clase C (Hogar)", "tipo": "Cuñete"},
    {"pagina": 1, "codigo": "F-410-05", "desc_factura": "HOGAR LIMONADA CNT", "cant": 1.0, "precio_unit": 24.60, "total": 24.60, "clase": "Clase C (Hogar)", "tipo": "Cuñete"},
    {"pagina": 1, "codigo": "F-406-04", "desc_factura": "HOGAR AGUAMARINA CNT", "cant": 1.0, "precio_unit": 24.60, "total": 24.60, "clase": "Clase C (Hogar)", "tipo": "Cuñete"},

    # --- PAGINA 2 (Nota M000003214 - Parte 1) ---
    {"pagina": 2, "codigo": "F-316-01", "desc_factura": "SATINADO OCRE GAL", "cant": 4.0, "precio_unit": 20.35, "total": 81.40, "clase": "Satinado", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-301-01", "desc_factura": "SATINADO BLANCO GAL", "cant": 8.0, "precio_unit": 20.35, "total": 162.80, "clase": "Satinado", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-302-01", "desc_factura": "SATINADO MARFIL GAL", "cant": 8.0, "precio_unit": 20.35, "total": 162.80, "clase": "Satinado", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-304-01", "desc_factura": "SATINADO BLANCO OSTRA GAL", "cant": 8.0, "precio_unit": 20.35, "total": 162.80, "clase": "Satinado", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-303-01", "desc_factura": "SATINADO SALMON GAL", "cant": 4.0, "precio_unit": 20.35, "total": 81.40, "clase": "Satinado", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-310-01", "desc_factura": "SATINADO MANZANA GAL", "cant": 4.0, "precio_unit": 20.35, "total": 81.40, "clase": "Satinado", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-307-01", "desc_factura": "SATINADO ROSA PASTEL GAL", "cant": 4.0, "precio_unit": 20.35, "total": 81.40, "clase": "Satinado", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-301-04", "desc_factura": "SATINADO BLANCO CNT", "cant": 2.0, "precio_unit": 79.20, "total": 158.40, "clase": "Satinado", "tipo": "Cuñete"},
    {"pagina": 2, "codigo": "F-302-04", "desc_factura": "SATINADO MARFIL CNT", "cant": 2.0, "precio_unit": 79.20, "total": 158.40, "clase": "Satinado", "tipo": "Cuñete"},
    {"pagina": 2, "codigo": "F-354-01", "desc_factura": "PREMIUM VERDE MORICHAL GAL", "cant": 4.0, "precio_unit": 15.73, "total": 62.92, "clase": "Clase A (Premium)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-362-01", "desc_factura": "PREMIUM VIOLETA GAL", "cant": 4.0, "precio_unit": 15.73, "total": 62.92, "clase": "Clase A (Premium)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-352-01", "desc_factura": "PREMIUM MARFIL GAL", "cant": 4.0, "precio_unit": 15.73, "total": 62.92, "clase": "Clase A (Premium)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-352-04", "desc_factura": "PREMIUM MARFIL CNT", "cant": 2.0, "precio_unit": 57.20, "total": 114.40, "clase": "Clase A (Premium)", "tipo": "Cuñete"},
    {"pagina": 2, "codigo": "F-351-04", "desc_factura": "PREMIUM BLANCO CNT", "cant": 2.0, "precio_unit": 57.20, "total": 114.40, "clase": "Clase A (Premium)", "tipo": "Cuñete"},
    {"pagina": 2, "codigo": "F-136-01", "desc_factura": "CAUCHO FLORAL GAL", "cant": 4.0, "precio_unit": 9.20, "total": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-103-01", "desc_factura": "CAUCHO MELON GAL", "cant": 4.0, "precio_unit": 9.20, "total": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-105-01", "desc_factura": "CAUCHO GRIS CLARO GAL", "cant": 4.0, "precio_unit": 9.20, "total": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-115-01", "desc_factura": "CAUCHO ORQUIDEA GAL", "cant": 4.0, "precio_unit": 9.20, "total": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-101-01", "desc_factura": "CAUCHO BLANCO GAL", "cant": 8.0, "precio_unit": 9.20, "total": 73.60, "clase": "Clase B (Caucho)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-129-01", "desc_factura": "CAUCHO GIRASOL GAL", "cant": 4.0, "precio_unit": 9.20, "total": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-118-01", "desc_factura": "CAUCHO AZUL BAHIA GAL", "cant": 8.0, "precio_unit": 9.20, "total": 73.60, "clase": "Clase B (Caucho)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-118-04", "desc_factura": "CAUCHO AZUL BAHIA CNT", "cant": 2.0, "precio_unit": 34.50, "total": 69.00, "clase": "Clase B (Caucho)", "tipo": "Cuñete"},
    {"pagina": 2, "codigo": "F-130-01", "desc_factura": "CAUCHO FUCSIA GAL", "cant": 4.0, "precio_unit": 9.20, "total": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-112-01", "desc_factura": "CAUCHO CREPUSCULO GAL", "cant": 4.0, "precio_unit": 9.20, "total": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-112-04", "desc_factura": "CAUCHO CREPUSCULO CNT", "cant": 1.0, "precio_unit": 34.50, "total": 34.50, "clase": "Clase B (Caucho)", "tipo": "Cuñete"},
    {"pagina": 2, "codigo": "F-121-01", "desc_factura": "CAUCHO AZUL CIELO GAL", "cant": 4.0, "precio_unit": 9.20, "total": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-102-01", "desc_factura": "CAUCHO MARFIL CLASICO GAL", "cant": 4.0, "precio_unit": 9.20, "total": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-128-01", "desc_factura": "CAUCHO MARFIL GAL", "cant": 8.0, "precio_unit": 9.20, "total": 73.60, "clase": "Clase B (Caucho)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-104-01", "desc_factura": "CAUCHO GREIGE GAL", "cant": 4.0, "precio_unit": 9.20, "total": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-116-01", "desc_factura": "CAUCHO AZUL OSCURO GAL", "cant": 4.0, "precio_unit": 9.20, "total": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón"},
    {"pagina": 2, "codigo": "F-123-01", "desc_factura": "CAUCHO VERDE ALEGRIA GAL", "cant": 4.0, "precio_unit": 9.20, "total": 36.80, "clase": "Clase B (Caucho)", "tipo": "Galón"},

    # --- PAGINA 3 (Nota M000003214 - Parte 2) ---
    {"pagina": 3, "codigo": "F-123-04", "desc_factura": "CAUCHO VERDE ALEGRIA CNT", "cant": 1.0, "precio_unit": 34.50, "total": 34.50, "clase": "Clase B (Caucho)", "tipo": "Cuñete"},
    {"pagina": 3, "codigo": "F-133-04", "desc_factura": "CAUCHO BLANCO OSTRA CNT", "cant": 2.0, "precio_unit": 34.50, "total": 69.00, "clase": "Clase B (Caucho)", "tipo": "Cuñete"},
    {"pagina": 3, "codigo": "F-134-04", "desc_factura": "CAUCHO ESMERALDA CNT", "cant": 1.0, "precio_unit": 34.50, "total": 34.50, "clase": "Clase B (Caucho)", "tipo": "Cuñete"},
    {"pagina": 3, "codigo": "F-119-04", "desc_factura": "CAUCHO TURQUESA CNT", "cant": 1.0, "precio_unit": 34.50, "total": 34.50, "clase": "Clase B (Caucho)", "tipo": "Cuñete"},
    {"pagina": 3, "codigo": "F-418-05", "desc_factura": "SAT HOGAR LILA GAL", "cant": 4.0, "precio_unit": 15.95, "total": 63.80, "clase": "Satinado Hogar", "tipo": "Galón"},
    {"pagina": 3, "codigo": "F-414-05", "desc_factura": "SAT HOGAR FLAMINGO GAL", "cant": 4.0, "precio_unit": 15.95, "total": 63.80, "clase": "Satinado Hogar", "tipo": "Galón"},
    {"pagina": 3, "codigo": "F-416-05", "desc_factura": "SAT. HOGAR ZAFIRO GAL", "cant": 4.0, "precio_unit": 15.95, "total": 63.80, "clase": "Satinado Hogar", "tipo": "Galón"},
    {"pagina": 3, "codigo": "F-830-01", "desc_factura": "2 EN 1 GRIS GALON", "cant": 8.0, "precio_unit": 21.23, "total": 169.84, "clase": "Esmalte 2 en 1", "tipo": "Galón"},
    {"pagina": 3, "codigo": "F-830-04", "desc_factura": "2 EN 1 GRIS 1/4", "cant": 12.0, "precio_unit": 6.60, "total": 79.20, "clase": "Esmalte 2 en 1", "tipo": "1/4 Galón"},
    {"pagina": 3, "codigo": "F-721-04", "desc_factura": "BARNIZ CAOBA CLARO 1/4", "cant": 12.0, "precio_unit": 7.37, "total": 88.44, "clase": "Barniz", "tipo": "1/4 Galón"},
    {"pagina": 3, "codigo": "F-722-04", "desc_factura": "BARNIZ CAOBA OSCURO 1/4", "cant": 12.0, "precio_unit": 7.37, "total": 88.44, "clase": "Barniz", "tipo": "1/4 Galón"},
    {"pagina": 3, "codigo": "F-722-01", "desc_factura": "BARNIZ CAOBA OSCURO GAL", "cant": 4.0, "precio_unit": 24.75, "total": 99.00, "clase": "Barniz", "tipo": "Galón"},
    {"pagina": 3, "codigo": "F-721-01", "desc_factura": "BARNIZ CAOBA CLARO GAL", "cant": 4.0, "precio_unit": 24.75, "total": 99.00, "clase": "Barniz", "tipo": "Galón"},
    {"pagina": 3, "codigo": "THINNER-01", "desc_factura": "SOLVENTE MULTIUSO FLORIPAINT", "cant": 24.0, "precio_unit": 3.50, "total": 84.00, "clase": "Solvente", "tipo": "Litro / Botella"},
    {"pagina": 3, "codigo": "F-790-04", "desc_factura": "PASTA PROFESIONAL CNT", "cant": 6.0, "precio_unit": 27.39, "total": 164.34, "clase": "Pasta Profesional", "tipo": "Cuñete"},
    {"pagina": 3, "codigo": "F-790-01", "desc_factura": "PASTA PROFESIONAL GAL", "cant": 8.0, "precio_unit": 7.59, "total": 60.72, "clase": "Pasta Profesional", "tipo": "Galón"},
    {"pagina": 3, "codigo": "F-790-05", "desc_factura": "PASTA PROFESIONAL 1/4", "cant": 12.0, "precio_unit": 2.75, "total": 33.00, "clase": "Pasta Profesional", "tipo": "1/4 Galón"},
    {"pagina": 3, "codigo": "F-789-01", "desc_factura": "ANTIALCALINO GAL", "cant": 4.0, "precio_unit": 12.43, "total": 49.72, "clase": "Antialcalino", "tipo": "Galón"},
    {"pagina": 3, "codigo": "F-789-02", "desc_factura": "ANTIALCALINO 1/4", "cant": 6.0, "precio_unit": 3.85, "total": 23.10, "clase": "Antialcalino", "tipo": "1/4 Galón"},
]

def smart_round(val):
    integer_part = int(val)
    dec = val - integer_part
    if dec <= 0.15:
        return float(integer_part)
    elif dec <= 0.65:
        return integer_part + 0.5
    else:
        return float(integer_part + 1)

en_sistema = 0
no_en_sistema = 0

resultados = []

for item in items_factura:
    cod = item['codigo']
    esta = cod in maestro_dict
    costo = round(item['precio_unit'] * 0.65, 2)
    # Precio con 25% markup y smart round (que da 6$ para 4.81)
    p25 = smart_round(costo * 1.25)
    
    # Nombre estandarizado según clase y tipo
    desc_sistema = maestro_dict[cod]['descripcion'] if esta else None
    
    if esta:
        en_sistema += 1
        nombre_final = desc_sistema
    else:
        no_en_sistema += 1
        # Generar nombre según reglas
        # ...
        nombre_final = ""
    
    resultados.append({
        **item,
        "en_sistema": esta,
        "costo_calculado": costo,
        "precio_sugerido": p25,
        "desc_sistema_existente": desc_sistema
    })

print(f"Total items en factura: {len(items_factura)}")
print(f"En sistema: {en_sistema}")
print(f"NO en sistema: {no_en_sistema}")
