"""
listener_writeback.py — Canal App -> Local (write-back).

Sondea la tabla Supabase `cambios_solicitados`, y por cada solicitud 'pendiente'
aplica el cambio en HybridLite vía hybrid_ui.py, marcando el resultado en la nube.

Diseñado para correr JUNTO a remote_listener.py (no lo reemplaza). Es independiente
para no tocar el código de producción existente.

SEGURIDAD:
  * Mientras hybrid_ui.DRY_RUN sea True (por defecto), NO toca la app: solo simula
    y registra. Habilita escritura real con  set HYBRID_WRITE_ENABLED=1.
  * Procesa de a una solicitud por vez (sin concurrencia sobre la app).
  * Reintentos limitados; si supera el máximo, marca 'error' y no insiste.

Uso:
    python listener_writeback.py            # bucle continuo
    python listener_writeback.py --once     # una sola pasada (para pruebas)
"""
import os
import sys
import json
import time
import datetime
import logging
import urllib.request
import urllib.error

# Reutiliza la configuración del backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
    SUPABASE_REST_URL = config.SUPABASE_REST_URL
    SUPABASE_ANON_KEY = config.SUPABASE_ANON_KEY
except Exception as e:  # pragma: no cover
    print(f"No pude cargar config.py del backend: {e}")
    sys.exit(1)

import hybrid_ui

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "writeback.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger("writeback")

TABLE = "cambios_solicitados"
POLL_INTERVAL = 8          # segundos entre sondeos
MAX_INTENTOS = 3
HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    "Content-Type": "application/json",
}


# ─── Helpers REST ─────────────────────────────────────────────────────────────
def _rest(method, path, body=None, extra_headers=None):
    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/{path}"
    headers = dict(HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None


def get_pendientes():
    try:
        path = (f"{TABLE}?status=eq.pendiente"
                f"&select=id,tipo,codigo_producto,valor_nuevo,delta,motivo,intentos"
                f"&order=solicitado_en.asc&limit=10")
        return _rest("GET", path) or []
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else ""
        log.error("HTTP %s buscando pendientes: %s", e.code, body[:200])
        return []
    except Exception as e:
        log.error("Error buscando pendientes: %r", e)
        return []


def update_solicitud(cid, **fields):
    fields.setdefault("aplicado_en", datetime.datetime.now(datetime.timezone.utc).isoformat())
    try:
        _rest("PATCH", f"{TABLE}?id=eq.{cid}", body=fields,
              extra_headers={"Prefer": "return=minimal"})
        return True
    except Exception as e:
        log.error("No pude actualizar solicitud %s: %r", cid, e)
        return False


# ─── Procesamiento de una solicitud ───────────────────────────────────────────
def procesar(sol):
    cid = sol["id"]
    tipo = sol.get("tipo")
    codigo = sol.get("codigo_producto")
    intentos = (sol.get("intentos") or 0) + 1

    log.info("Procesando %s: tipo=%s codigo=%s intento=%s", cid, tipo, codigo, intentos)

    # Marca 'aplicando' (lock optimista)
    if not update_solicitud(cid, status="aplicando", intentos=intentos):
        return

    try:
        if tipo == "precio":
            res = hybrid_ui.set_price(codigo, float(sol["valor_nuevo"]))
        elif tipo == "stock":
            res = hybrid_ui.adjust_stock(codigo, float(sol["delta"]), sol.get("motivo") or "")
        else:
            res = {"ok": False, "detalle": f"tipo desconocido: {tipo}", "valor_anterior": None}
    except hybrid_ui.NotCalibratedError as e:
        res = {"ok": False, "detalle": f"SIN CALIBRAR: {e}", "valor_anterior": None}
    except Exception as e:
        res = {"ok": False, "detalle": f"excepción: {e!r}", "valor_anterior": None}

    if res["ok"]:
        update_solicitud(cid, status="aplicado", resultado=res["detalle"],
                         valor_anterior=res.get("valor_anterior"))
        log.info("OK %s: %s", cid, res["detalle"])
    else:
        # Si agotó intentos -> error definitivo; si no, vuelve a 'pendiente'
        final = "error" if intentos >= MAX_INTENTOS else "pendiente"
        update_solicitud(cid, status=final, resultado=res["detalle"])
        log.warning("FALLO %s (%s): %s", cid, final, res["detalle"])


def loop(once=False):
    log.info("=== listener_writeback iniciado (DRY_RUN=%s, tabla=%s) ===",
             hybrid_ui.DRY_RUN, TABLE)
    while True:
        try:
            for sol in get_pendientes():
                procesar(sol)
        except Exception as e:
            log.error("Error en bucle: %r", e)
        if once:
            break
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    loop(once="--once" in sys.argv)
