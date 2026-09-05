"""
encolar_precios_floripaint.py — Encola en Supabase (ordenes_cambio / ordenes_cambio_items)
la actualización de costos y precios corregidos (+16% IVA y descuentos diferenciados)
para que listener_writeback.py los aplique en HybridLite.

Uso:
    python scripts/encolar_precios_floripaint.py --test         # Encola solo 1 item (F-404-01) para prueba
    python scripts/encolar_precios_floripaint.py --nota 1       # Encola Nota 1 (16 items)
    python scripts/encolar_precios_floripaint.py --nota 2       # Encola Nota 2 (50 items)
    python scripts/encolar_precios_floripaint.py --ambas        # Encola ambas notas (66 items)
    python scripts/encolar_precios_floripaint.py --monitor <ID> # Monitorea una orden en vivo
"""
import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
import pydbisam

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY
except Exception as e:
    print(f"Error cargando config.py: {e}")
    sys.exit(1)

write_key = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY
HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {write_key}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

CREADO_POR = "ca1d0a1f-c4e1-475a-89bb-728e3afad076"
RUTA_DB_PRECIOS = r"H:\HybridLite\HybridEmpresa\HybridDataBase\TCostoPrecioInv.Dat"

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

def obtener_precios_actuales_dbisam(codigos):
    """Lee precios y costos actuales de DBISAM en una sola pasada rápida."""
    db = pydbisam.PyDBISAM(RUTA_DB_PRECIOS)
    fields = db.fields()
    idx = {n: i for i, n in enumerate(fields)}
    cod_i = idx["TPC_CODIGOPRODUCTO"]
    tipo_i = idx["TPC_TIPO"]
    costo_i = idx["TPC_COSTOACTUAL"]
    pvp_i = idx["TPC_PVPCONIMPUESTO1"]
    
    found = {}
    for row in db.rows():
        cod = str(row[cod_i]).strip()
        if cod in codigos and row[tipo_i] == 1:
            found[cod] = {
                "costo": float(row[costo_i]) if row[costo_i] is not None else 0.0,
                "precio": float(row[pvp_i]) if row[pvp_i] is not None else 0.0
            }
    return found

def encolar_orden_cambio(titulo_nota, items):
    print(f"\n=======================================================")
    print(f"  ENCOLANDO ORDEN DE PRECIOS/COSTOS: {titulo_nota} ({len(items)} items)")
    print(f"=======================================================")
    
    # 1. Obtener datos actuales de DBISAM
    codigos_set = set()
    for it in items:
        cod = it["codigo"]
        if cod == "THINNER-01":
            cod = "THINNER-M"
        codigos_set.add(cod)
        
    db_info = obtener_precios_actuales_dbisam(codigos_set)
    print(f"-> Datos de DBISAM leídos para {len(db_info)} productos.")
    
    # 2. Crear cabecera ordenes_cambio
    cabecera = {
        "creado_por": CREADO_POR,
        "nota": titulo_nota,
        "status": "emitido",
        "aprobacion_estado": "no_aplica"
    }
    
    res_cab = rest("POST", "ordenes_cambio", cabecera)
    if not res_cab:
        print("Error: No se pudo crear cabecera en ordenes_cambio.")
        return None
        
    orden_id = res_cab[0]["id"]
    print(f"-> Orden de Cambio creada con ID: {orden_id}")
    
    # 3. Crear items en ordenes_cambio_items
    filas = []
    for it in items:
        cod = it["codigo"]
        if cod == "THINNER-01":
            cod = "THINNER-M"
            
        p_actual = db_info.get(cod, {}).get("precio", 0.0)
        c_actual = db_info.get(cod, {}).get("costo", 0.0)
        p_nuevo = float(it["precio_venta_sugerido_25"])
        c_nuevo = float(it["costo"])
        
        filas.append({
            "orden_id": orden_id,
            "codigo_producto": cod,
            "descripcion": it["descripcion_sistema"],
            "delta": 0.0,
            "existencia_actual": None,
            "nueva_existencia": None,
            "precio_actual": p_actual,
            "nuevo_precio": p_nuevo,
            "costo": c_nuevo,
            "backend_status": "pendiente",
            "backend_intentos": 0
        })
        
    res_items = rest("POST", "ordenes_cambio_items", filas)
    print(f"-> {len(res_items)} items insertados en ordenes_cambio_items.")
    print(f"-> Orden {orden_id} lista en estado 'emitido'. listener_writeback la procesará.")
    return orden_id

def monitorear_orden(orden_id, timeout_min=15):
    print(f"\n--- Monitoreando Orden de Cambio {orden_id} ---")
    t0 = time.time()
    max_s = timeout_min * 60
    while time.time() - t0 < max_s:
        items = rest("GET", f"ordenes_cambio_items?orden_id=eq.{orden_id}&select=id,codigo_producto,backend_status,backend_resultado")
        if not items:
            print("Esperando items...")
            time.sleep(3)
            continue
            
        counts = {}
        for it in items:
            st = it["backend_status"]
            counts[st] = counts.get(st, 0) + 1
            
        total = len(items)
        completados = counts.get("completado", 0)
        pendientes = counts.get("pendiente", 0)
        aplicando = counts.get("aplicando", 0)
        errores = counts.get("error", 0)
        
        print(f"[{int(time.time()-t0)}s] Total: {total} | Completados: {completados} | Aplicando: {aplicando} | Pendientes: {pendientes} | Errores: {errores}")
        
        if completados + errores == total and total > 0:
            print(f"\nFinalizado! {completados}/{total} completados ({errores} errores).")
            if errores > 0:
                print("Items con error:")
                for it in items:
                    if it["backend_status"] == "error":
                        print(f"  * {it['codigo_producto']}: {it['backend_resultado']}")
            return True
            
        time.sleep(3)
        
    print("Timeout alcanzado en monitoreo.")
    return False

def main():
    parser = argparse.ArgumentParser(description="Encolar actualizacion de precios y costos Floripaint")
    parser.add_argument("--test", action="store_true", help="Encolar 1 solo item de prueba (F-404-01)")
    parser.add_argument("--nota", type=int, choices=[1, 2], help="Numero de nota a encolar (1 o 2)")
    parser.add_argument("--ambas", action="store_true", help="Encolar ambas notas")
    parser.add_argument("--monitor", type=int, help="Monitorear una orden por ID")
    args = parser.parse_args()
    
    if args.monitor:
        monitorear_orden(args.monitor)
        return
        
    if not (args.test or args.nota or args.ambas):
        parser.print_help()
        sys.exit(1)
        
    with open('c:/Proyect/backend serrucho/scratch/floripaint_procesado.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    if args.test:
        test_item = [x for x in data if x["codigo"] == "F-404-01"]
        oid = encolar_orden_cambio("Prueba Precios Floripaint - F-404-01", test_item)
        if oid:
            monitorear_orden(oid, timeout_min=3)
    elif args.nota == 1:
        items1 = [x for x in data if x["pagina"] == 1]
        oid = encolar_orden_cambio("Actualizacion Precios Floripaint - Nota M000003215 (16 items)", items1)
        if oid:
            monitorear_orden(oid, timeout_min=10)
    elif args.nota == 2:
        items2 = [x for x in data if x["pagina"] in (2, 3)]
        oid = encolar_orden_cambio("Actualizacion Precios Floripaint - Nota M000003214 (50 items)", items2)
        if oid:
            monitorear_orden(oid, timeout_min=20)
    elif args.ambas:
        items1 = [x for x in data if x["pagina"] == 1]
        items2 = [x for x in data if x["pagina"] in (2, 3)]
        oid1 = encolar_orden_cambio("Actualizacion Precios Floripaint - Nota M000003215 (16 items)", items1)
        if oid1:
            monitorear_orden(oid1, timeout_min=10)
        oid2 = encolar_orden_cambio("Actualizacion Precios Floripaint - Nota M000003214 (50 items)", items2)
        if oid2:
            monitorear_orden(oid2, timeout_min=20)

if __name__ == "__main__":
    main()
