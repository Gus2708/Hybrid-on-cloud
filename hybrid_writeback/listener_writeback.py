"""
listener_writeback.py — Canal App (El Serrucho Go) -> Local (write-back de stock).

Sondea `ordenes_cambio_items` (tabla que la app YA llena al emitir una Orden de
Cambio, ver el-serrucho-go/src/hooks/useOrdenCambio.ts) y, por cada item de una
orden con status='emitido' que todavía no fue aplicado, ajusta el stock en
HybridLite vía flujo_stock_real.py (input real de hardware), usando el `delta`
que la propia app ya calcula (nueva_existencia - existencia_actual). Marca el
resultado en columnas nuevas `backend_*` (migración 018 en el-serrucho-go;
vocabulario de estados `pendiente / aplicando / error / completado`, backfill
en migración 019).

No toca `ordenes_cambio.status` ni el PDF: ese flujo lo sigue manejando la app
igual que hoy. Este listener corre en paralelo, es independiente.

RLS de `ordenes_cambio_items` solo deja ver/editar al dueño autenticado, así que
el backend necesita SUPABASE_SERVICE_KEY (config.py) para leer las filas de
todos los usuarios. Con solo la anon key el listener vería siempre 0 filas —
no es un error, es RLS filtrando en silencio.

SEGURIDAD:
  * Mientras HYBRID_WRITE_ENABLED no sea "1", cada item se procesa en modo
    PREVIEW (commit=False): navega y verifica en pantalla, pero cancela sin
    persistir nada en HybridLite.
  * Procesa un item a la vez (sin concurrencia sobre la app).
  * `delta` NULL -> error inmediato (dato mal generado, no se reintenta).
    `delta` 0 -> se marca 'completado' sin tocar HybridLite (nada que aplicar).
  * Guard de unidad `H:`: si `TExistenciaInv.Dat` no es accesible (caída de
    red / VPN), la pasada NO pide pendientes ni procesa nada (evita quemar
    intentos por un FileNotFoundError de arranque).
  * Ventana horaria opcional `HYBRID_WRITE_WINDOW` ("HH:MM-HH:MM", hora local,
    soporta cruce de medianoche): fuera de la ventana el bucle continuo no
    procesa nada. Si está seteada pero no parsea, es FAIL-CLOSED (no procesa).
    Solo aplica al bucle continuo con HYBRID_WRITE_ENABLED=1; `--once` la
    ignora (corrida manual supervisada).
  * Reintentos limitados y conservadores: un fallo en una etapa PRE-commit
    ("abrir_hybrid", "carga/conteo") reintenta hasta MAX_INTENTOS; un fallo en
    cualquier etapa AMBIGUA (post-commit, o excepción) marca 'error' de
    inmediato, sin reintentar — el ajuste es relativo (delta) y reintentar un
    commit ambiguo puede aplicarlo dos veces y desajustar el inventario real.
  * Al arrancar, recupera huérfanos: items que quedaron en 'aplicando' por una
    corrida anterior interrumpida se marcan 'error' (mismo motivo: no se sabe
    si el commit llegó a aplicarse).
  * En bucle continuo (sin --once), si HYBRID_WRITE_ENABLED != 1 no se procesa
    nada (evita tomar el mouse en preview sin fin cada POLL_INTERVAL).

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
    SUPABASE_SERVICE_KEY = getattr(config, "SUPABASE_SERVICE_KEY", "")
except Exception as e:  # pragma: no cover
    print(f"No pude cargar config.py del backend: {e}")
    sys.exit(1)

import flujo_stock_real
import read_db_existencia

HYBRID_WRITE_ENABLED = os.environ.get("HYBRID_WRITE_ENABLED") == "1"

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

TABLE = "ordenes_cambio_items"
POLL_INTERVAL = 8          # segundos entre sondeos
MAX_INTENTOS = 3

# Etapas de flujo_stock_real.ajustar_stock() anteriores a cualquier commit en
# HybridLite: un fallo ahí es reintentable sin riesgo. Cualquier otra etapa
# (post-commit, ambigua) o una excepción se tratan como error inmediato en
# procesar() — ver comentario ahí (F5).
ETAPAS_REINTENTABLES = ("abrir_hybrid", "carga/conteo")

API_KEY = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY
if not SUPABASE_SERVICE_KEY:
    log.warning("SUPABASE_SERVICE_KEY no configurada en config.py/.env: usando la "
                "anon key, que por RLS NO puede ver ordenes_cambio_items de otros "
                "usuarios. Agregar SUPABASE_SERVICE_KEY para que este listener "
                "funcione de verdad.")
HEADERS = {
    "apikey": API_KEY,
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}


# ─── Guard de disponibilidad de H: ─────────────────────────────────────────────
def _h_disponible():
    """True si el .Dat de existencia es accesible (unidad H: / share montado).

    Si H: está caída (VPN, red, etc.), flujo_stock_real revienta con
    FileNotFoundError apenas arranca a leer la DB de verificación. Chequear
    esto ANTES de pedir pendientes evita quemar intentos de items válidos por
    una caída de red ajena a ellos.
    """
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
_HYBRID_WRITE_WINDOW_RAW = os.environ.get("HYBRID_WRITE_WINDOW", "").strip()
HYBRID_WRITE_WINDOW = None
HYBRID_WRITE_WINDOW_ERROR = None
if _HYBRID_WRITE_WINDOW_RAW:
    try:
        HYBRID_WRITE_WINDOW = _parse_ventana(_HYBRID_WRITE_WINDOW_RAW)
    except ValueError as e:
        HYBRID_WRITE_WINDOW_ERROR = (
            f"HYBRID_WRITE_WINDOW={_HYBRID_WRITE_WINDOW_RAW!r} inválida "
            f"(esperado 'HH:MM-HH:MM'): {e!r}"
        )


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
    """Items 'pendiente' cuya orden ya fue emitida (no procesar borradores).

    F8 — filtro `creado_por NOT NULL`: la tabla tiene DOBLE USO. Además de la
    app, sync_ajustes.py inserta acá ESPEJOS HISTÓRICOS de los movimientos
    locales de HybridLite (ajustes/compras hechos en la tienda), con
    `creado_por` NULL y firma `[Local Inv ID: n]`/`[Local Com ID: n]` en la
    nota de la cabecera. Esos espejos YA están aplicados localmente: si se
    procesaran acá se re-aplicarían en HybridLite y se armaría un bucle de
    retroalimentación (re-aplicar -> se vuelve a espejar -> se vuelve a
    re-aplicar) que destruye el inventario. Solo las órdenes creadas por un
    usuario autenticado de la app son solicitudes reales. (Segunda capa de
    defensa: sync_ajustes.py inserta sus items ya en 'completado'.)
    """
    try:
        path = (f"{TABLE}?backend_status=eq.pendiente"
                f"&select=id,orden_id,codigo_producto,descripcion,delta,"
                f"existencia_actual,nueva_existencia,backend_intentos,"
                f"ordenes_cambio!inner(status,creado_por)"
                f"&ordenes_cambio.status=eq.emitido"
                f"&ordenes_cambio.creado_por=not.is.null"
                f"&order=id.asc&limit=10")
        return _rest("GET", path) or []
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else ""
        log.error("HTTP %s buscando pendientes: %s", e.code, body[:200])
        return []
    except Exception as e:
        log.error("Error buscando pendientes: %r", e)
        return []


def update_item(iid, **fields):
    try:
        _rest("PATCH", f"{TABLE}?id=eq.{iid}", body=fields,
              extra_headers={"Prefer": "return=minimal"})
        return True
    except Exception as e:
        log.error("No pude actualizar item %s: %r", iid, e)
        return False


def recuperar_huerfanos():
    """Al arrancar, marca 'error' cualquier item que haya quedado en
    'aplicando' de una corrida anterior interrumpida (crash, kill, corte de
    luz, etc.). No se puede saber si el commit llegó a aplicarse en HybridLite
    antes del corte, así que se trata como ambiguo: requiere verificación
    manual antes de reencolar (mismo criterio que F5 para etapas ambiguas).
    """
    nota = ("Corrida interrumpida (quedó en 'aplicando'). Verificar en "
            "HybridLite si el ajuste se aplicó antes de reencolar manualmente "
            "— riesgo de ajuste doble.")
    try:
        recuperados = _rest(
            "PATCH", f"{TABLE}?backend_status=eq.aplicando",
            body={"backend_status": "error", "backend_resultado": nota},
            extra_headers={"Prefer": "return=representation"},
        )
        n = len(recuperados) if recuperados else 0
        if n:
            log.warning("Recuperados %s item(s) huérfano(s) en 'aplicando' -> 'error'.", n)
        else:
            log.debug("Sin huérfanos 'aplicando' al arrancar.")
    except Exception as e:
        log.warning("No pude chequear/recuperar huérfanos 'aplicando' (sigo igual): %r", e)


# ─── Procesamiento de un item ──────────────────────────────────────────────────
def procesar(item):
    iid = item["id"]
    codigo = item.get("codigo_producto")
    delta = item.get("delta")
    intentos = (item.get("backend_intentos") or 0) + 1

    log.info("Procesando item %s (orden %s): codigo=%s delta=%s intento=%s",
              iid, item.get("orden_id"), codigo, delta, intentos)

    # F1: delta NULL -> el dato no se generó bien (probablemente falta
    # existencia_actual en la orden). No es reintentable: no consume el
    # mecanismo de intentos, va directo a 'error' para revisión manual.
    if delta is None:
        update_item(iid, backend_status="error",
                    backend_resultado="delta llegó NULL (probable existencia_actual "
                                       "faltante en la orden). Corregir/recrear el item "
                                       "desde la app; no se reintenta automáticamente.")
        log.error("Item %s con delta NULL -> 'error' sin reintentar.", iid)
        return

    # F1: delta 0 -> nada que ajustar en HybridLite. Se completa directo sin
    # tocar la app (evita un ciclo de input real de ~30s para no-operación).
    if float(delta) == 0:
        update_item(iid, backend_status="completado",
                    backend_resultado="delta 0: nada que aplicar.",
                    backend_aplicado_en=datetime.datetime.now(datetime.timezone.utc).isoformat())
        log.info("Item %s con delta 0 -> 'completado' sin tocar HybridLite.", iid)
        return

    # Marca 'aplicando' (lock optimista)
    if not update_item(iid, backend_status="aplicando", backend_intentos=intentos):
        return

    try:
        res = flujo_stock_real.ajustar_stock(codigo, float(delta),
                                              commit=HYBRID_WRITE_ENABLED, delta=True)
    except Exception as e:
        res = {"ok": False, "etapa": "excepcion", "detalle": f"excepción: {e!r}"}

    # Con HYBRID_WRITE_ENABLED apagado, todo queda en preview: nunca se marca
    # 'completado' aunque el resultado sea ok, para no confundirlo con un commit real.
    # El llamador (loop) sólo invoca procesar() en modo preview para pruebas puntuales
    # (--once), nunca en bucle continuo, para no reintentar el item sin fin.
    if res["ok"] and HYBRID_WRITE_ENABLED and res.get("etapa") == "commit":
        update_item(iid, backend_status="completado", backend_resultado=res["detalle"],
                    backend_aplicado_en=datetime.datetime.now(datetime.timezone.utc).isoformat())
        log.info("OK item %s: %s", iid, res["detalle"])
    elif res["ok"]:
        update_item(iid, backend_status="pendiente", backend_resultado=f"[PREVIEW] {res['detalle']}")
        log.info("PREVIEW item %s (HYBRID_WRITE_ENABLED=0, no se aplicó): %s", iid, res["detalle"])
    else:
        # F5: política de reintentos conservadora. El ajuste es RELATIVO
        # (delta), así que reintentar tras un commit en etapa ambigua puede
        # aplicar el delta DOS VECES y desajustar el inventario real. Solo
        # las etapas anteriores a cualquier intento de commit (abrir_hybrid,
        # carga/conteo) son reintentables; cualquier otra etapa (totalizar,
        # verificacion_db, etc.) o una excepción van a 'error' de inmediato,
        # sin importar cuántos intentos queden, con una advertencia explícita
        # para revisión manual antes de reencolar.
        etapa = res.get("etapa")
        if etapa in ETAPAS_REINTENTABLES:
            final = "error" if intentos >= MAX_INTENTOS else "pendiente"
            update_item(iid, backend_status=final, backend_resultado=res["detalle"])
            log.warning("FALLO item %s (%s, etapa=%s reintentable): %s",
                        iid, final, etapa, res["detalle"])
        else:
            resultado = (f"{res['detalle']} | ATENCIÓN: fallo en etapa ambigua "
                         f"(etapa={etapa!r}) — verificar en HybridLite si el ajuste "
                         f"se aplicó ANTES de reencolar manualmente (riesgo de "
                         f"ajuste doble).")
            update_item(iid, backend_status="error", backend_resultado=resultado)
            log.error("FALLO item %s (error inmediato, etapa=%s NO reintentable): %s",
                      iid, etapa, res["detalle"])


def loop(once=False):
    log.info("=== listener_writeback iniciado (HYBRID_WRITE_ENABLED=%s, tabla=%s) ===",
             HYBRID_WRITE_ENABLED, TABLE)
    if not HYBRID_WRITE_ENABLED and not once:
        log.warning("HYBRID_WRITE_ENABLED != 1: en bucle continuo NO se procesan "
                     "items (evita tomar el mouse en preview sin fin). Usá --once "
                     "para una pasada de prueba en preview, o poné "
                     "HYBRID_WRITE_ENABLED=1 para aplicar cambios reales.")
    if HYBRID_WRITE_WINDOW_ERROR:
        log.error("%s -> FAIL-CLOSED: en bucle continuo no se procesará nada "
                   "hasta corregir la variable.", HYBRID_WRITE_WINDOW_ERROR)
    elif HYBRID_WRITE_WINDOW:
        log.info("HYBRID_WRITE_WINDOW activa: %s", _HYBRID_WRITE_WINDOW_RAW)

    # F6: recupera items que quedaron en 'aplicando' de una corrida anterior
    # interrumpida (crash, corte de luz, etc.) antes de arrancar a procesar.
    recuperar_huerfanos()

    # F4: anti-spam — solo logueamos cuando el motivo de "no proceso nada"
    # cambia (o cuando se vuelve a estado operativo), no en cada iteración.
    ultimo_motivo_skip = None

    while True:
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
                # F2: guard de H: a nivel de pasada. Sin esto, ajustar_stock
                # revienta con FileNotFoundError al leer TExistenciaInv.Dat y
                # se quema un intento de items que no tienen ninguna culpa.
                motivo_skip = ("h_caida", "Unidad H: (\\\\PRINCIPAL\\Happs) no accesible "
                                          "-> no se piden ni procesan pendientes esta pasada.")
            elif HYBRID_WRITE_ENABLED and not once and HYBRID_WRITE_WINDOW_ERROR:
                # F3: ventana mal configurada = fail-closed, solo en bucle continuo.
                motivo_skip = ("ventana_invalida", HYBRID_WRITE_WINDOW_ERROR + " -> FAIL-CLOSED.")
            elif (HYBRID_WRITE_ENABLED and not once and HYBRID_WRITE_WINDOW
                  and not _dentro_de_ventana(HYBRID_WRITE_WINDOW)):
                # F3: fuera de la ventana horaria configurada (solo bucle continuo).
                motivo_skip = ("fuera_de_ventana",
                                f"Fuera de HYBRID_WRITE_WINDOW ({_HYBRID_WRITE_WINDOW_RAW}) "
                                f"-> no se procesan pendientes esta pasada.")

            if motivo_skip is None:
                if ultimo_motivo_skip is not None:
                    log.info("Vuelve a estado operativo: se procesan pendientes normalmente.")
                    ultimo_motivo_skip = None
                if HYBRID_WRITE_ENABLED or once:
                    for item in get_pendientes():
                        procesar(item)
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


if __name__ == "__main__":
    loop(once="--once" in sys.argv)
