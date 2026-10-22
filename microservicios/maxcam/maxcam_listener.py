import os
import sys

if sys.executable.lower().endswith("pythonw.exe"):
    try:
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")
    except: pass

import json
import time
import datetime
import urllib.error
import urllib.parse
import urllib.request

# Listener de consultas a Maxcam: Serrucho Go inserta una fila en
# consultas_maxcam (status 'pendiente'); este proceso resuelve el SKU de Maxcam
# del producto, pregunta el stock de Barquisimeto a la API local (maxcam_api.py,
# puerto 5001) y escribe el resultado en la misma fila. La app la lee por polling.
#
# Resolución del SKU: primero por código exacto (hash en la API); si no hay
# coincidencia, por similitud de embeddings (RPC maxcam_equivalentes) y se
# consulta el stock de cada candidato.

LOG_FILE = "maxcam_listener.log"
_MAX_LOG_BYTES = 5 * 1024 * 1024
MAXCAM_API = os.environ.get("MAXCAM_API_URL", "http://127.0.0.1:5001")
POLL_SECONDS = 3
API_TIMEOUT = 130          # la primera consulta tras arrancar la API construye el índice (~76 s)
UMBRAL_SIMILITUD = 0.6
MAX_CANDIDATOS = 3
RETENCION_DIAS = 3
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Vive en microservicios/maxcam: config y supabase_rest son los del backend. Se agrega al
# FINAL de sys.path para que ningún módulo del microservicio los tape.
BACKEND_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", ".."))
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)


def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        path = os.path.join(BASE_DIR, LOG_FILE)
        if os.path.exists(path) and os.path.getsize(path) > _MAX_LOG_BYTES:
            bak = path + ".1"
            if os.path.exists(bak): os.remove(bak)
            os.rename(path, bak)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except: pass
    print(f"[{timestamp}] {message.encode('ascii', 'replace').decode('ascii')}")


try:
    import config
    REST = config.SUPABASE_REST_URL.rstrip("/")
    from supabase_rest import build_write_headers
except Exception as e:
    print(f"Error: config/supabase_rest no disponibles: {e}")
    sys.exit(1)

# Lectura y escritura con la service key (consultas_maxcam no admite UPDATE a anon).
HEADERS = build_write_headers(extra_prefer="return=minimal")
HEADERS_REP = build_write_headers(extra_prefer="return=representation")


def http(method, url, headers=None, body=None, timeout=30):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    # headers={} (llamadas a la API local) no debe caer en HEADERS: llevan la service key.
    req = urllib.request.Request(url, data=data, headers=HEADERS if headers is None else headers,
                                 method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None


def patch(row_id, fields, only_status=None):
    q = f"{REST}/rest/v1/consultas_maxcam?id=eq.{row_id}"
    if only_status:
        q += f"&status=eq.{only_status}"
    fields = {**fields, "actualizado_en": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    return http("PATCH", q, HEADERS_REP, fields)


def api_disponibilidad(**params):
    pairs = [(k, v) for k, v in params.items() if v]
    url = f"{MAXCAM_API}/disponibilidad?{urllib.parse.urlencode(pairs)}"
    return http("GET", url, {}, timeout=API_TIMEOUT)


def candidato(info, similitud, marca=None):
    return {
        "sku": info["sku"],
        "nombre": info["nombre"],
        "marca": marca,
        "similitud": round(similitud, 3),
        "disponible": info["disponible"],
        "stock_bq": info["stock_bq"],
        "precio": info.get("precio"),
        "cant_caja": info.get("cant_caja"),
    }


def resolver(codigo_interno):
    q = f"{REST}/rest/v1/productos?codigo_interno=eq.{urllib.parse.quote(codigo_interno, safe='')}" \
        "&select=codigo_interno,descripcion,codigo_barras,referencia"
    rows = http("GET", q)
    if not rows:
        raise ValueError("Producto no encontrado en el inventario")
    p = rows[0]

    exacto = api_disponibilidad(codigo=p["codigo_interno"], referencia=p.get("referencia"),
                                barras=p.get("codigo_barras"))
    if exacto and exacto.get("encontrado"):
        return {"metodo": "codigo", "candidatos": [candidato(exacto, 1.0)]}

    sugeridos = http("POST", f"{REST}/rest/v1/rpc/maxcam_equivalentes", HEADERS, {
        "p_codigo_interno": codigo_interno,
        "p_limite": MAX_CANDIDATOS,
        "p_umbral": UMBRAL_SIMILITUD,
    }) or []
    candidatos = []
    for s in sugeridos:
        info = api_disponibilidad(codigo=s["sku"])
        if info and info.get("encontrado"):
            candidatos.append(candidato(info, s["similitud"], s.get("marca")))
    return {"metodo": "similitud", "candidatos": candidatos}


def procesar(row):
    rid, codigo = row["id"], row["codigo_interno"]
    # Reclamar la fila: si otra instancia ya la tomó, PATCH no devuelve nada.
    if not patch(rid, {"status": "procesando"}, only_status="pendiente"):
        return
    try:
        resultado = resolver(codigo)
        resultado["consultado_en"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        patch(rid, {"status": "listo", "resultado": resultado, "error": None})
        log(f"{codigo}: {resultado['metodo']}, {len(resultado['candidatos'])} candidato(s)")
    except urllib.error.URLError as e:
        patch(rid, {"status": "error", "error": "API Maxcam no disponible"})
        log(f"{codigo}: API no disponible: {e!r}")
    except Exception as e:
        patch(rid, {"status": "error", "error": str(e)[:200]})
        log(f"{codigo}: error: {e!r}")


def limpiar_viejas():
    limite = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=RETENCION_DIAS)).isoformat()
    http("DELETE", f"{REST}/rest/v1/consultas_maxcam?creado_en=lt.{urllib.parse.quote(limite)}")


def main():
    log("=== Listener Maxcam iniciado ===")
    try:  # filas que quedaron 'procesando' porque este proceso murió a medias
        http("PATCH", f"{REST}/rest/v1/consultas_maxcam?status=eq.procesando", HEADERS,
             {"status": "pendiente"})
    except Exception as e:
        log(f"No se pudo recuperar filas colgadas: {e!r}")

    fails, last_clean = 0, 0.0
    while True:
        try:
            pendientes = http("GET", f"{REST}/rest/v1/consultas_maxcam?status=eq.pendiente"
                                     "&order=creado_en.asc&limit=5&select=id,codigo_interno")
            if fails >= 3:
                log("Conexión con Supabase recuperada.")
            fails = 0
            for row in pendientes or []:
                procesar(row)
            if time.time() - last_clean > 3600:
                limpiar_viejas()
                last_clean = time.time()
        except Exception as e:
            fails += 1
            if fails <= 3 or fails % 30 == 0:
                log(f"Error de red/Supabase ({fails} seguidos): {e!r}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
