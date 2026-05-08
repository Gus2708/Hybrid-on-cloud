import os
import csv
import json
import urllib.request
import urllib.error
from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY

HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",
}

def upsert_batch(table: str, on_conflict: str, payload: list) -> bool:
    if not payload:
        return True
    
    if on_conflict:
        url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/{table}?on_conflict={on_conflict}"
    else:
        url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/{table}"

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.getcode()
            body = resp.read().decode(errors='ignore')
            if code in (200, 201, 204):
                return True
            print(f"Error {code}: {body}")
            return False
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else ""
        print(f"HTTPError {e.code}: {body}")
        return False
    except Exception as e:
        print(f"Exception: {e}")
        return False

def to_float(val):
    if not val:
        return 0.0
    try:
        return float(val)
    except:
        return 0.0

def to_int(val):
    if not val:
        return 0
    try:
        return int(float(val))
    except:
        return 0

def subir_clientes():
    print("Subiendo clientes...")
    path = "MAESTRO_CLIENTES.csv"
    if not os.path.exists(path):
        print(f"No existe {path}")
        return

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        batch = []
        total = 0
        for row in reader:
            batch.append({
                "codigo_cliente": row["CLT_CODIGO"],
                "nombre": row["CLT_DESCRIPCION"],
                "rif": row["CLT_RIF"],
                "telefono": row.get("CLT_TELEFONO", ""),
                "direccion": row.get("CLT_DIRECCION1", "")
            })
            if len(batch) >= 1000:
                if not upsert_batch("clientes", "codigo_cliente", batch):
                    print("Error subiendo lote de clientes.")
                total += len(batch)
                batch = []
                print(f"  ...{total} clientes subidos.")
        
        if batch:
            upsert_batch("clientes", "codigo_cliente", batch)
            total += len(batch)
            print(f"  ...{total} clientes subidos.")

def subir_ventas():
    print("\nSubiendo ventas cabecera...")
    path = "VENTAS_CABECERA.csv"
    if not os.path.exists(path):
        print(f"No existe {path}")
        return

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        batch = []
        total = 0
        for row in reader:
            batch.append({
                "documento": row["THT_DOCUMENTO"],
                "fecha_emision": row["THT_FECHAEMISION"] if row["THT_FECHAEMISION"] else None,
                "rif_cliente": row.get("THT_RIFCLIENTE", ""),
                "total_neto": to_float(row["THT_TOTALNETO"]),
                "total_impuesto": to_float(row.get("THT_TOTALIMPUESTO", 0)),
                "status": to_int(row["THT_STATUS"]),
                "numero_control": row["THT_NUMEROCONTROL"],
                "metodo_pago": row.get("METODO_PAGO", ""),
                "created_at": row.get("FECHA_HORA_COMPLETA"), # Sobreescribir con hora real
                "id_unico": to_int(row.get("THT_IDUNICO", 0))
            })
            if len(batch) >= 1000:
                if not upsert_batch("ventas", "id_unico", batch):
                    print("Error subiendo lote de ventas.")
                total += len(batch)
                batch = []
                print(f"  ...{total} ventas subidas.")
        
        if batch:
            upsert_batch("ventas", "id_unico", batch)
            total += len(batch)
            print(f"  ...{total} ventas subidas.")

def subir_ventas_detalle():
    print("\nSubiendo ventas detalle...")
    path = "VENTAS_DETALLE.csv"
    if not os.path.exists(path):
        print(f"No existe {path}")
        return

    # Usaremos insert sin on_conflict ya que es autoincrement y se exporta completo.
    # En la base de datos se debe trunca primero o solo insertar nuevos. 
    # Para ser simple, y como ventas_detalle no tiene unique key mas que el identity, usaremos on_conflict vacio
    
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        batch = []
        total = 0
        for row in reader:
            batch.append({
                "documento": row["TBT_DOCUMENTO"],
                "codigo_producto": row["TBT_CODIGO"],
                "cantidad": to_float(row["TBT_CANTIDAD"]),
                "precio_venta": to_float(row["TBT_PRECIODEVENTA"]),
                "costo_str": row.get("TBT_CTOCOSTOSTR", "")
            })
            if len(batch) >= 1000:
                if not upsert_batch("ventas_detalle", "", batch):
                    print("Error subiendo lote de detalles.")
                total += len(batch)
                batch = []
                print(f"  ...{total} detalles subidos.")
        
        if batch:
            upsert_batch("ventas_detalle", "", batch)
            total += len(batch)
            print(f"  ...{total} detalles subidos.")

if __name__ == '__main__':
    subir_clientes()
    subir_ventas()
    subir_ventas_detalle()
    print("\n--- Migracion a Supabase finalizada ---")
