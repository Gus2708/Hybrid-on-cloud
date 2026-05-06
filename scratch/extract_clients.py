import re
import os

ruta_clientes = r"h:\HybridLite\HybridEmpresa\HybridDataBase\TClientes.dat"

def extraer_clientes():
    print(f"Leyendo: {ruta_clientes}")
    with open(ruta_clientes, 'rb') as f:
        contenido = f.read()

    # Buscar cadenas que parezcan RIFs (ej. J-12345678-9 o V-12345678)
    # y los textos a su alrededor.
    
    # DBISAM almacena los records en bloques. Vamos a buscar bloques que tengan RIF.
    matches = re.finditer(b'([JVGE][-]?\d{6,9}[-]?\d?)', contenido, re.IGNORECASE)
    
    clientes_encontrados = []
    for match in matches:
        offset = match.start()
        rif = match.group(1).decode('latin-1', errors='ignore')
        
        # Leer el bloque alrededor del RIF para obtener nombre y código
        # El nombre del cliente probablemente esté antes o después.
        bloque = contenido[max(0, offset-200) : min(len(contenido), offset+200)]
        
        # Extraer todas las cadenas legibles en este bloque
        cadenas = [x.decode('latin-1', errors='ignore').strip() for x in re.findall(b'[\x20-\x7E\xA0-\xFF]{4,}', bloque)]
        
        clientes_encontrados.append({
            'rif': rif,
            'cadenas_cercanas': cadenas
        })
        
        if len(clientes_encontrados) >= 5:
            break

    for c in clientes_encontrados:
        print(f"RIF: {c['rif']}")
        print(f"Cadenas: {c['cadenas_cercanas']}")
        print("-" * 40)

if __name__ == '__main__':
    extraer_clientes()
