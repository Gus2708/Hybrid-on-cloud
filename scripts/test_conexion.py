"""
test_conexion.py — Diagnóstico de conectividad para Hybrid on Cloud.

Ejecutar:
    python test_conexion.py

Verifica:
    1. CSV fuente existe y es legible
    2. Configuración de Supabase presente
    3. Conexión a la REST de Supabase (GET)
    4. Upsert de prueba con 1 fila dummy (POST)
"""
import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

# Asegurar que podemos importar desde el mismo directorio
sys.path.insert(0, str(Path(__file__).parent))

# ─── Colores (compatibles con Windows PowerShell) ────────────────────────────
import sys
import io
# Forzar UTF-8 en la salida para evitar UnicodeEncodeError en Windows CP1252
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
elif sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def _ok(msg):  print(f"  [OK]  {msg}")
def _err(msg): print(f"  [!!]  {msg}")
def _inf(msg): print(f"  [--]  {msg}")


def check_csv():
    print("\n[1/4] Verificando CSV fuente...")
    try:
        from config import CSV_SOURCE_PATH
        path = CSV_SOURCE_PATH
    except Exception as e:
        _err(f"No se pudo importar config: {e}")
        return False

    if not os.path.exists(path):
        _err(f"CSV no encontrado: {path}")
        return False

    _ok(f"CSV encontrado: {path}")
    try:
        import csv
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            filas = sum(1 for row in reader if row and len(row) >= 7 and row[0].strip() and row[0].strip()[0].isdigit())
        _ok(f"Filas válidas en CSV: {filas}")
        _inf(f"Encabezado: {header}")
        return True
    except Exception as e:
        _err(f"Error leyendo CSV: {e}")
        return False


def check_config():
    print("\n[2/4] Verificando configuración Supabase...")
    try:
        from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY, TASA_BS_DEFAULT
    except Exception as e:
        _err(f"No se pudo importar config: {e}")
        return None, None

    if not SUPABASE_REST_URL:
        _err("SUPABASE_REST_URL no configurada")
    else:
        _ok(f"SUPABASE_REST_URL: {SUPABASE_REST_URL}")

    if not SUPABASE_ANON_KEY:
        _err("SUPABASE_ANON_KEY no configurada")
    else:
        _ok(f"SUPABASE_ANON_KEY: ...{SUPABASE_ANON_KEY[-12:]} (últimos 12 chars)")

    _inf(f"TASA_BS_DEFAULT: {TASA_BS_DEFAULT} Bs/USD")

    return SUPABASE_REST_URL, SUPABASE_ANON_KEY


def check_get(rest_url: str, anon_key: str):
    print("\n[3/4] Probando GET a Supabase REST (tabla productos)...")
    url = f"{rest_url.rstrip('/')}/rest/v1/productos?limit=3"
    headers = {
        "apikey": anon_key,
        "Authorization": f"Bearer {anon_key}",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            code = resp.getcode()
            body = resp.read().decode(errors="ignore")
            if code == 200:
                filas = json.loads(body) if body else []
                _ok(f"GET exitoso — {len(filas)} filas devueltas")
                if filas:
                    _inf(f"Primera fila: {json.dumps(filas[0], ensure_ascii=False)[:120]}")
                return True
            else:
                _err(f"HTTP {code}: {body[:200]}")
                return False
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else "(sin cuerpo)"
        _err(f"HTTPError {e.code}: {body[:300]}")
        if e.code == 404:
            _inf("  -> La tabla 'productos' puede no existir. Crear con sql/crear_tabla_productos.sql")
        elif e.code == 401:
            _inf("  -> ANON_KEY inválida o RLS bloqueando acceso anónimo")
        return False
    except Exception as e:
        _err(f"Excepción: {e}")
        return False


def check_upsert(rest_url: str, anon_key: str):
    print("\n[4/4] Probando upsert de prueba (1 fila dummy)...")
    url = f"{rest_url.rstrip('/')}/rest/v1/productos?on_conflict=codigo_interno"
    payload = [{
        "codigo_interno": "TEST-DIAG-001",
        "descripcion":    "PRODUCTO DE DIAGNOSTICO - BORRAR",
        "unidad":         "PZA",
        "codigo_barras":  "0000000000000",
        "costo":          0.01,
        "precio_venta":   0.01,
        "existencia":     0.0,
    }]
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "apikey": anon_key,
        "Authorization": f"Bearer {anon_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            code = resp.getcode()
            if code in (200, 201, 204):
                _ok(f"Upsert exitoso (HTTP {code})")
                _inf("  -> Puedes borrar la fila TEST-DIAG-001 desde el dashboard de Supabase")
                return True
            body = resp.read().decode(errors="ignore")
            _err(f"HTTP {code}: {body[:200]}")
            return False
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else "(sin cuerpo)"
        _err(f"HTTPError {e.code}: {body[:300]}")
        if e.code == 409:
            _inf("  -> Conflicto: la fila TEST-DIAG-001 ya existe y no se pudo hacer merge")
        return False
    except Exception as e:
        _err(f"Excepción: {e}")
        return False


def main():
    from config import SAAS_NAME
    print("=" * 55)
    print(f"  DIAGNÓSTICO — {SAAS_NAME}")
    print("=" * 55)

    r1 = check_csv()
    rest_url, anon_key = check_config()

    if not rest_url or not anon_key:
        print("\n[DIAG] Sin configuración REST válida. Parar aquí.")
        print("       -> Editar config.py o crear archivo .env con:")
        print("         SUPABASE_REST_URL=https://tu-proyecto.supabase.co")
        print("         SUPABASE_ANON_KEY=eyJ...")
        sys.exit(1)

    r3 = check_get(rest_url, anon_key)
    r4 = check_upsert(rest_url, anon_key)

    print("\n" + "=" * 55)
    print("  RESUMEN")
    print("=" * 55)
    resultados = [
        ("CSV fuente",      r1),
        ("Config Supabase", bool(rest_url and anon_key)),
        ("GET REST",        r3),
        ("Upsert REST",     r4),
    ]
    all_ok = True
    for nombre, ok in resultados:
        estado = "OK" if ok else "FALLO"
        print(f"  {estado:6s}  {nombre}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("  Todo OK. Puedes ejecutar:")
        print("    python sync.py once")
        print("    python app.py")
    else:
        print("  Hay errores. Revisar los mensajes de [!!] arriba.")
    print("=" * 55)


if __name__ == "__main__":
    main()
