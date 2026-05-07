import csv
import os
import re

input_path = r'C:\Users\OFICINA\Desktop\Habladores $.csv'
output_path = r'C:\Users\OFICINA\Desktop\Habladores_Limpio.csv'

def process_file():
    results = []
    
    # Intenta leer el archivo original
    if not os.path.exists(input_path):
        print(f"Error: No se encuentra el archivo en {input_path}")
        return None, 0

    with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
        
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Saltar líneas vacías o que solo tienen comas
        if not line or all(c == ',' for c in line):
            i += 1
            continue
            
        if "REF." in line:
            i += 1
            continue
            
        # Extraer el nombre/descripción
        name = ""
        try:
            row = next(csv.reader([lines[i]]))
            if row:
                name = row[0].strip()
        except:
            name = line.split(',')[0].strip().strip('"')

        if not name:
            i += 1
            continue
            
        # Buscar el precio en las líneas siguientes
        price = None
        search_idx = i + 1
        found_ref = False
        
        while search_idx < len(lines) and search_idx < i + 15:
            curr_line = lines[search_idx].strip()
            
            if "REF." in curr_line:
                found_ref = True
                search_idx += 1
                continue
            
            if found_ref:
                parts = curr_line.split(',')
                for p in parts:
                    p_clean = p.strip()
                    if p_clean:
                        # Validar si es un número
                        if re.match(r'^\d+(\.\d+)?$', p_clean):
                            price = p_clean
                            break
                if price:
                    break
            
            search_idx += 1
            
        if name and price:
            results.append({'DESCRIPCION': name, 'PRECIO': price})
            i = search_idx + 1
        else:
            i += 1
            
    # Escribir el nuevo CSV
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['DESCRIPCION', 'PRECIO'])
        writer.writeheader()
        writer.writerows(results)
    
    return output_path, len(results)

if __name__ == "__main__":
    path, count = process_file()
    if path:
        print(f"Proceso completado. {count} productos guardados en {path}")
