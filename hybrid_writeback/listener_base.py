"""
listener_base.py — Base común de listener_writeback y listener_compras: config,
logging, guards (H:, ventana horaria, toggle del widget), cliente REST y bucle
principal. La lógica de dominio (qué se sondea y cómo se aplica) vive en cada
listener.
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
    SUPABASE_SERVICE_KEY = getattr(config, "SUPABASE_SERVICE_KEY", "")
except Exception as e:  # pragma: no cover
    print(f"No pude cargar config.py del backend: {e}")
    sys.exit(1)

API_KEY = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY
# El warning de service-key faltante NO se emite acá (todavía no hay logging
# configurado en el import del base): cada listener lo loguea con su propio
# logger, tras llamar setup_logging(), usando este texto genérico.
AVISO_SIN_SERVICE_KEY = None
if not SUPABASE_SERVICE_KEY:
    AVISO_SIN_SERVICE_KEY = (
        "SUPABASE_SERVICE_KEY no configurada en config.py/.env: usando la "
        "anon key, que por RLS NO puede ver las tablas de otros usuarios. "
        "Agregar SUPABASE_SERVICE_KEY para que este listener funcione de verdad."
    )
HEADERS = {
    "apikey": API_KEY,
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}


def setup_logging(nombre_logger, archivo_log):
    """Configura logging para un listener y devuelve su logger.

    Llamar DESPUÉS de importar los módulos de flujo (flujo_stock_real,
    flujo_precio_real, flujo_compra_real, etc.).

    force=True: los módulos importados antes (flujo_stock_real, etc.) ya
    llamaron logging.basicConfig con solo StreamHandler, y basicConfig es
    no-op si el root ya tiene handlers -> sin force, el FileHandler NUNCA se
    agregaba y bajo pythonw (consola a DEVNULL) el listener corría sin dejar
    rastro en el archivo de log.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             archivo_log), encoding="utf-8"),
        ],
    )
    return logging.getLogger(nombre_logger)


_last_known_enabled = None

def check_hybrid_write_enabled():
    global _last_known_enabled
    default_enabled = os.environ.get("HYBRID_WRITE_ENABLED") == "1"
    if _last_known_enabled is None:
        _last_known_enabled = default_enabled
    try:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "writeback_settings.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                _last_known_enabled = data.get("enabled", default_enabled)
    except Exception:
        pass
    return _last_known_enabled


# ─── Guard de disponibilidad de H: ─────────────────────────────────────────────
def _h_disponible():
    """True si el .Dat de existencia es accesible (unidad H: / share montado).

    Si H: está caída (VPN, red, etc.), los flujos revientan con
    FileNotFoundError apenas arrancan a leer la DB de verificación. Chequear
    esto ANTES de pedir pendientes evita quemar intentos de items válidos por
    una caída de red ajena a ellos.
    """
    import read_db_existencia
    return os.path.exists(read_db_existencia.RUTA)


# ─── Ventana horaria opcional (HYBRID_WRITE_WINDOW) ────────────────────────────
def _parse_ventana(valor):
    """Parsea "HH:MM-HH:MM" a (inicio, fin) como datetime.time.

    Devuelve None si `valor` es vacío/None (sin restricción horaria).
    Lanza ValueError si `valor` está seteado pero no tiene el formato esperado
    (el llamador debe tratar eso como FAIL-CLOSED: no procesar nada).
    """
    if not valor:
        return None
    ini_s, _, fin_s = valor.partition("-")
    ini = datetime.datetime.strptime(ini_s.strip(), "%H:%M").time()
    fin = datetime.datetime.strptime(fin_s.strip(), "%H:%M").time()
    return ini, fin


def _dentro_de_ventana(ventana, ahora=None):
    """True si `ahora` (datetime.time, default = hora local actual) cae dentro
    de `ventana` = (inicio, fin). Soporta ventanas que cruzan medianoche
    (ej. "19:30-07:30"): si inicio > fin, está dentro cuando ahora >= inicio
    O ahora < fin."""
    ini, fin = ventana
    if ahora is None:
        ahora = datetime.datetime.now().time()
    if ini <= fin:
        return ini <= ahora < fin
    return ahora >= ini or ahora < fin


# Parseo único al inicio (no en cada iteración del bucle). Si la variable está
# seteada pero es inválida, HYBRID_WRITE_WINDOW_ERROR guarda el motivo y el
# bucle se comporta FAIL-CLOSED (como si siempre estuviera fuera de ventana).
HYBRID_WRITE_WINDOW_RAW = os.environ.get("HYBRID_WRITE_WINDOW", "").strip()
HYBRID_WRITE_WINDOW = None
HYBRID_WRITE_WINDOW_ERROR = None
if HYBRID_WRITE_WINDOW_RAW:
    try:
        HYBRID_WRITE_WINDOW = _parse_ventana(HYBRID_WRITE_WINDOW_RAW)
    except ValueError as e:
        HYBRID_WRITE_WINDOW_ERROR = (
            f"HYBRID_WRITE_WINDOW={HYBRID_WRITE_WINDOW_RAW!r} inválida "
            f"(esperado 'HH:MM-HH:MM'): {e!r}"
        )


# ─── Helpers REST ─────────────────────────────────────────────────────────────
def rest(method, path, body=None, extra_headers=None):
    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/{path}"
    headers = dict(HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None


# ─── Prioridad: altas de directorio (cliente/proveedor) primero que todo ──────
DIRECTORIO_TABLAS = ("registro_clientes_app", "registro_proveedores_app")


def hay_pendientes_prioritarios():
    """True si hay altas de cliente/proveedor 'pendiente' esperando aplicarse.

    Los otros listeners (compras / pedidos / ajustes) CEDEN el paso mientras esto
    sea True: un cliente/proveedor nuevo debe existir en HybridLite ANTES de la
    compra/pedido/ajuste que lo referencia. listener_directorio NO llama a esto
    (es el prioritario y no cede ante nadie).

    FAIL-OPEN: ante cualquier error de red/consulta devuelve False (no bloquea a
    los demás por una falla ajena). Un registro que falla llega a 'error' tras
    MAX_INTENTOS, así que un pendiente NUNCA bloquea de forma permanente.
    """
    for tabla in DIRECTORIO_TABLAS:
        try:
            path = (f"{tabla}?backend_status=eq.pendiente"
                    f"&status=eq.emitido&creado_por=not.is.null&select=id&limit=1")
            if rest("GET", path):
                return True
        except Exception:
            continue
    return False


POLL_INTERVAL = 5          # segundos entre sondeos (reducido de 8 para detección más rápida)


# ─── Bucle principal ────────────────────────────────────────────────────────
def correr_loop(log, listener_file, nombre, get_pendientes, procesar_pendientes,
                 recuperar_huerfanos, once=False, sujeto="pendientes", ceder_si=None):
    """`ceder_si`: callable opcional; si devuelve True, este listener CEDE el paso esta
    pasada (no procesa nada). Se usa para que compras/pedidos/ajustes esperen a que las
    altas de cliente/proveedor pendientes se apliquen primero. Solo aplica en bucle
    continuo (un --once manual no se bloquea)."""
    HYBRID_WRITE_ENABLED = check_hybrid_write_enabled()
    log.info("=== %s iniciado (HYBRID_WRITE_ENABLED=%s) ===", nombre, HYBRID_WRITE_ENABLED)
    # F11 — lección de un incidente real: un proceso viejo quedó corriendo en
    # memoria y procesó pendientes con código stale (una corrección ya
    # publicada en el archivo nunca llegó a aplicarse) sin que nadie lo
    # notara hasta después. Este log deja la fecha de modificación del
    # archivo en cada arranque, para poder cruzar "¿qué versión corrió
    # realmente esta noche?" contra el historial de git.
    log.info("codigo listener del %s",
             datetime.datetime.fromtimestamp(os.path.getmtime(listener_file)).strftime("%Y-%m-%d %H:%M"))
    if not HYBRID_WRITE_ENABLED and not once:
        log.warning("HYBRID_WRITE_ENABLED != 1: en bucle continuo NO se procesan "
                     "%s (evita tomar el mouse en preview sin fin). Usá --once "
                     "para una pasada de prueba en preview, o poné "
                     "HYBRID_WRITE_ENABLED=1 para aplicar cambios reales.", sujeto)
    if HYBRID_WRITE_WINDOW_ERROR:
        log.error("%s -> FAIL-CLOSED: en bucle continuo no se procesará nada "
                   "hasta corregir la variable.", HYBRID_WRITE_WINDOW_ERROR)
    elif HYBRID_WRITE_WINDOW:
        log.info("HYBRID_WRITE_WINDOW activa: %s", HYBRID_WRITE_WINDOW_RAW)

    # F6: recupera items que quedaron en 'aplicando' de una corrida anterior
    # interrumpida (crash, corte de luz, etc.) antes de arrancar a procesar.
    recuperar_huerfanos()

    # F4: anti-spam — solo logueamos cuando el motivo de "no proceso nada"
    # cambia (o cuando se vuelve a estado operativo), no en cada iteración.
    ultimo_motivo_skip = None

    while True:
        HYBRID_WRITE_ENABLED = check_hybrid_write_enabled()
        if not (HYBRID_WRITE_ENABLED or once):
            # Nada que hacer y ya se avisó una vez arriba (fuera del bucle):
            # no tocar ultimo_motivo_skip para no disparar un "vuelve a
            # estado operativo" falso si más tarde se prende HYBRID_WRITE_ENABLED.
            if once:
                break
            time.sleep(POLL_INTERVAL)
            continue

        motivo_skip = None
        try:
            if not _h_disponible():
                # F2: guard de H: a nivel de pasada. Sin esto, los flujos
                # revientan con FileNotFoundError al leer TExistenciaInv.Dat y
                # se quema un intento de items que no tienen ninguna culpa.
                motivo_skip = ("h_caida", "Unidad H: (\\\\PRINCIPAL\\Happs) no accesible "
                                          f"-> no se piden ni procesan {sujeto} esta pasada.")
            elif HYBRID_WRITE_ENABLED and not once and HYBRID_WRITE_WINDOW_ERROR:
                # F3: ventana mal configurada = fail-closed, solo en bucle continuo.
                motivo_skip = ("ventana_invalida", HYBRID_WRITE_WINDOW_ERROR + " -> FAIL-CLOSED.")
            elif (HYBRID_WRITE_ENABLED and not once and HYBRID_WRITE_WINDOW
                  and not _dentro_de_ventana(HYBRID_WRITE_WINDOW)):
                # F3: fuera de la ventana horaria configurada (solo bucle continuo).
                motivo_skip = ("fuera_de_ventana",
                                f"Fuera de HYBRID_WRITE_WINDOW ({HYBRID_WRITE_WINDOW_RAW}) "
                                f"-> no se procesan {sujeto} esta pasada.")
            elif ceder_si is not None and not once and ceder_si():
                # Prioridad: hay altas de cliente/proveedor pendientes -> este listener
                # cede el paso hasta que se apliquen (se registran primero que todo).
                motivo_skip = ("ceder_prioridad",
                                "Hay altas de cliente/proveedor pendientes; cedo el paso "
                                f"hasta aplicarlas (no se procesan {sujeto} esta pasada).")

            if motivo_skip is None:
                if ultimo_motivo_skip is not None:
                    log.info("Vuelve a estado operativo: se procesan %s normalmente.", sujeto)
                    ultimo_motivo_skip = None
                if HYBRID_WRITE_ENABLED or once:
                    procesar_pendientes(get_pendientes())
            else:
                clave, mensaje = motivo_skip
                if clave != ultimo_motivo_skip:
                    log.warning(mensaje)
                    ultimo_motivo_skip = clave
        except Exception as e:
            log.error("Error en bucle: %r", e)
        if once:
            break
        time.sleep(POLL_INTERVAL)
