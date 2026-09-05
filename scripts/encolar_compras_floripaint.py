"""
encolar_compras_floripaint.py — Encola en Supabase (compras_app / compras_app_items)
las Notas de Entrega de Floripaint para que listener_compras.py las registre en HybridLite.

Uso:
    python scripts/encolar_compras_floripaint.py --nota 1       # Encola Nota M000003215 (16 ítems)
    python scripts/encolar_compras_floripaint.py --nota 2       # Encola Nota M000003214 (50 ítems)
    python scripts/encolar_compras_floripaint.py --ambas        # Encola ambas notas
"""
import os
import sys
import json
import argparse
import urllib.request
import urllib.error

# Asegurar que el directorio raíz esté en sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importar configuración Supabase
try:
    from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY
except Exception as e:
    print(f"Error cargando config.py: {e}")
    sys.exit(1)


# Encabezados con service_role key para saltar RLS
write_key = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY
HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {write_key}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

CREADO_POR = "ca1d0a1f-c4e1-475a-89bb-728e3afad076"
PROVEEDOR_CODIGO = "J500342829"
PROVEEDOR_NOMBRE = "FLORIPAINT"

def rest(method, path, body=None):
    url = f"{SUPABASE_REST_URL}/rest/v1/{path}"
    data = json.dumps(body).encode('utf-8') if body else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode('utf-8')
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode(errors='ignore') if e.fp else str(e)
        print(f"Error HTTP {e.code} en {method} {path}: {err_msg}")
        raise

def encolar_nota(num_nota, doc_numero, items):
    print(f"\n=======================================================")
    print(f"  ENCOLANDO NOTA DE ENTREGA N° {doc_numero} ({len(items)} ítems)")
    print(f"=======================================================")
    
    # 1. Crear cabecera en compras_app
    cabecera = {
        "creado_por": CREADO_POR,
        "proveedor_codigo": PROVEEDOR_CODIGO,
        "proveedor_nombre": PROVEEDOR_NOMBRE,
        "nota": f"Nota de Entrega Floripaint {doc_numero}",
        "numero_documento": doc_numero,
        "status": "emitido",
        "backend_status": "pendiente",
        "backend_intentos": 0
    }
    
    res_cab = rest("POST", "compras_app", cabecera)
    if not res_cab:
        print("Error: No se pudo crear la cabecera en compras_app.")
        return None
        
    compra_id = res_cab[0]["id"]
    print(f"-> Cabecera compras_app creada con ID: {compra_id} (doc={doc_numero})")
    
    # 2. Crear ítems en compras_app_items
    filas_items = []
    for it in items:
        filas_items.append({
            "compra_id": compra_id,
            "codigo_producto": it["codigo"],
            "descripcion": it["descripcion_sistema"],
            "cantidad": it["cantidad"],
            "costo": it["costo_neto_menos_35"],
            "precio": it["precio_venta_sugerido_25"],
            "es_nuevo": (it["estado"] != "EN SISTEMA"),
            "referencia": None
        })
        
    res_items = rest("POST", "compras_app_items", filas_items)
    print(f"-> {len(res_items)} ítems insertados correctamente en compras_app_items.")
    
    nuevos_cnt = sum(1 for it in items if it["estado"] != "EN SISTEMA")
    exist_cnt = sum(1 for it in items if it["estado"] == "EN SISTEMA")
    print(f"   * Productos existentes: {exist_cnt}")
    print(f"   * Productos NUEVOS (se darán de alta): {nuevos_cnt}")
    print(f"-> Compra {compra_id} lista en estado 'pendiente'. El listener la procesará.")
    return compra_id

def main():
    parser = argparse.ArgumentParser(description="Encolar compras Floripaint")
    parser.add_argument("--nota", type=int, choices=[1, 2], help="Número de nota a encolar (1 o 2)")
    parser.add_argument("--ambas", action="store_true", help="Encolar ambas notas")
    args = parser.parse_args()
    
    if not args.nota and not args.ambas:
        parser.print_help()
        sys.exit(1)
        
    # Cargar JSON procesado
    with open('c:/Proyect/backend serrucho/scratch/floripaint_procesado.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    # Separar por nota/página
    # Nota 1 (M000003215) = Pagina 1 (16 ítems)
    # Nota 2 (M000003214) = Paginas 2 y 3 (50 ítems)
    items_nota1 = [x for x in data if x["pagina"] == 1]
    items_nota2 = [x for x in data if x["pagina"] in (2, 3)]
    
    # Ajustar THINNER-01 a THINNER-M si está presente
    for x in items_nota2:
        if x["codigo"] == "THINNER-01":
            x["codigo"] = "THINNER-M"
    
    if args.nota == 1:
        encolar_nota(1, "M000003215", items_nota1)
    elif args.nota == 2:
        encolar_nota(2, "M000003214", items_nota2)
    elif args.ambas:
        encolar_nota(1, "M000003215", items_nota1)
        encolar_nota(2, "M000003214", items_nota2)

if __name__ == "__main__":
    main()
