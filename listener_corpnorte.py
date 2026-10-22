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

# Listener de consultas a Corporación Norte: Serrucho Go inserta una fila en
# consultas_corpnorte (status 'pendiente'); este proceso resuelve el producto en el
# catálogo del proveedor, pregunta el stock a la API local (api-corporacionnorte,
# puerto 5002) y escribe el resultado en la misma fila. La app la lee por polling.
#
# Resolución: primero por código exacto (hash en la API); si no hay coincidencia, por
# similitud de embeddings (RPC corpnorte_equivalentes) y se consulta el stock de cada
# candidato. Es el gemelo de listener_maxcam.py.

LOG_FILE = "listener_corpnorte.log"
_MAX_LOG_BYTES = 5 * 1024 * 1024
CORPNORTE_API = os.environ.get("CORPNORTE_API_URL", "http://127.0.0.1:5002")
POLL_SECONDS = 3
API_TIMEOUT = 60
UMBRAL_SIMILITUD = 0.6
MAX_CANDIDATOS = 3
RETENCION_DIAS = 3
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


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

# Lectura y escritura con la service key (consultas_corpnorte no admite UPDATE a anon).
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
    q = f"{REST}/rest/v1/consultas_corpnorte?id=eq.{row_id}"
    if only_status:
        q += f"&status=eq.{only_status}"
    fields = {**fields, "actualizado_en": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    return http("PATCH", q, HEADERS_REP, fields)


def api_disponibilidad(**params):
    pairs = [(k, v) for k, v in params.items() if v]
    url = f"{CORPNORTE_API}/disponibilidad?{urllib.parse.urlencode(pairs)}"
    return http("GET", url, {}, timeout=API_TIMEOUT)


def candidato(info, similitud):
    return {
        "sku": info["codigo"],
        "nombre": info["nombre"],
        "marca": info.get("marca"),
        "similitud": round(similitud, 3),
        "disponible": info["disponible"],
        "stock": info.get("stock") or 0,
        "precio": info.get("precio"),
        "bulto": info.get("bulto"),
        # False cuando la API no pudo consultar el sitio y sirvió el catálogo guardado.
        "en_vivo": info.get("en_vivo", True),
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

    sugeridos = http("POST", f"{REST}/rest/v1/rpc/corpnorte_equivalentes", HEADERS, {
        "p_codigo_interno": codigo_interno,
        "p_limite": MAX_CANDIDATOS,
        "p_umbral": UMBRAL_SIMILITUD,
    }) or []
    candidatos = []
    for s in sugeridos:
        info = api_disponibilidad(codigo=s["codigo"])
        if info and info.get("encontrado"):
            candidatos.append(candidato(info, s["similitud"]))
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
        patch(rid, {"status": "error", "error": "API Corporación Norte no disponible"})
        log(f"{codigo}: API no disponible: {e!r}")
    except Exception as e:
        patch(rid, {"status": "error", "error": str(e)[:200]})
        log(f"{codigo}: error: {e!r}")


def limpiar_viejas():
    limite = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=RETENCION_DIAS)).isoformat()
    http("DELETE", f"{REST}/rest/v1/consultas_corpnorte?creado_en=lt.{urllib.parse.quote(limite)}")


def main():
    log("=== Listener Corporación Norte iniciado ===")
    try:  # filas que quedaron 'procesando' porque este proceso murió a medias
        http("PATCH", f"{REST}/rest/v1/consultas_corpnorte?status=eq.procesando", HEADERS,
             {"status": "pendiente"})
    except Exception as e:
        log(f"No se pudo recuperar filas colgadas: {e!r}")

    fails, last_clean = 0, 0.0
    while True:
        try:
            pendientes = http("GET", f"{REST}/rest/v1/consultas_corpnorte?status=eq.pendiente"
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
