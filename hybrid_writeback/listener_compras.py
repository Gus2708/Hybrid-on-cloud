"""
listener_compras.py — Canal App (El Serrucho Go, Lista de Compras) -> Local
(write-back de compras a HybridLite).

Sondea `compras_app` (cabecera) / `compras_app_items` (detalle) — tablas que
la app llena al emitir una compra desde la Lista de Compras (proveedor +
items con cantidad/costo/precio) — y por cada compra con status='emitido' que
todavía no fue aplicada, la registra en HybridLite como "Compra de
mercancías" (clase 5, NOTAS DE ENTREGA) vía flujo_compra_real.registrar_compra
(input real de hardware, ver ese módulo). Marca el resultado en las columnas
`backend_*` de la CABECERA (migración 022 en el-serrucho-go): a diferencia de
ordenes_cambio_items (estado por ítem), una compra es UN documento de Hybrid
(un solo Totalizar), así que el estado vive en compras_app, no por fila de
compras_app_items.

Este listener es HERMANO de listener_writeback.py (mismo esqueleto: guard de
H:, ventana horaria opcional, HYBRID_WRITE_ENABLED, control_seguro, política
de reintentos). Corre como proceso SEPARADO; ambos toman el mouse real, por
eso safety_control.control_seguro ahora serializa el acceso entre los dos con
un Mutex de Windows con nombre (ver safety_control._adquirir_mutex_mouse).

RLS de compras_app/compras_app_items solo deja ver/editar al dueño
autenticado (mismo patrón que ordenes_cambio), así que el backend necesita
SUPABASE_SERVICE_KEY (config.py) para leer las compras de todos los usuarios.
Con solo la anon key el listener vería siempre 0 filas — no es un error, es
RLS filtrando en silencio.

SEGURIDAD (calcada de listener_writeback, ver ese módulo para el detalle
completo de cada punto):
  * Mientras HYBRID_WRITE_ENABLED no sea "1", cada compra se procesa en modo
    PREVIEW (commit=False): navega y verifica en pantalla, pero cancela sin
    persistir nada en HybridLite (la compra es TODO-O-NADA, ver
    flujo_compra_real.registrar_compra).
  * Todo el procesamiento de una pasada corre dentro de `with
    control_seguro():` (banner rojo + F12 + BlockInput si hay admin). Si el
    módulo no está disponible, se degrada con gracia: procesa igual pero SIN
    overlay, con un log.warning una sola vez por vida del proceso.
  * Guard de unidad `H:`: si `TExistenciaInv.Dat` no es accesible, la pasada
    NO pide pendientes ni procesa nada.
  * Ventana horaria opcional `HYBRID_WRITE_WINDOW` ("HH:MM-HH:MM", hora
    local, soporta cruce de medianoche): fuera de la ventana el bucle
    continuo no procesa nada. Si está seteada pero no parsea, es FAIL-CLOSED.
    Solo aplica al bucle continuo con HYBRID_WRITE_ENABLED=1; `--once` la
    ignora (corrida manual supervisada).
  * Reintentos limitados: un fallo en etapa PRE-Totalizar ("abrir_hybrid",
    "navegacion", "carga_item", "precio_item") es reintentable hasta
    MAX_INTENTOS — la compra se cancela completa antes de devolver esas
    etapas, así que reintentar no deja nada a medias. Un fallo en etapa
    AMBIGUA ("totalizar", "verificacion_db", excepción) marca 'error' de
    inmediato sin reintentar: la compra pudo haber quedado registrada a
    medias en HybridLite y reencolarla arriesga una compra doble.
  * Al arrancar, recupera huérfanos: compras que quedaron en 'aplicando' por
    una corrida anterior interrumpida se marcan 'error' (mismo motivo: no se
    sabe si Totalizar llegó a aplicarse).
  * En bucle continuo (sin --once), si HYBRID_WRITE_ENABLED != 1 no se
    procesa nada (evita tomar el mouse en preview sin fin cada POLL_INTERVAL).
  * Al arrancar, se loguea la fecha de modificación del propio archivo
    ("codigo listener del ...") — misma lección de listener_writeback (F11).

Uso:
    python listener_compras.py            # bucle continuo
    python listener_compras.py --once     # una sola pasada (para pruebas)
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

import flujo_compra_real
import read_db_existencia

try:
    from safety_control import control_seguro
except Exception:  # pragma: no cover
    control_seguro = None

HYBRID_WRITE_ENABLED = os.environ.get("HYBRID_WRITE_ENABLED") == "1"

# force=True: los módulos importados arriba (flujo_compra_real, etc.) ya
# llamaron logging.basicConfig con solo StreamHandler, y basicConfig es no-op
# si el root ya tiene handlers -> sin force, el FileHandler NUNCA se agregaba
# y bajo pythonw (consola a DEVNULL) el listener corría sin dejar rastro en
# compras.log. Archivo PROPIO (compras.log), NO writeback.log — procesos
# separados, logs separados.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    force=True,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "compras.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger("compras")

TABLE_CAB = "compras_app"
TABLE_ITEMS = "compras_app_items"
POLL_INTERVAL = 8          # segundos entre sondeos
MAX_INTENTOS = 3

# Etapas de flujo_compra_real.registrar_compra() anteriores a Totalizar: la
# compra se cancela completa antes de devolver estas etapas (todo-o-nada), así
# que un fallo acá es 100% reintentable sin riesgo de doble aplicación.
# "alta_producto:abrir_ficha" / "alta_producto:campos" / "alta_producto:costos_precios"
# son las etapas reintentables de crear_producto (Ficha nueva descartada con
# Cancelar/Salir ANTES de Guardar, nada persistido todavía -- ver ese docstring);
# "alta_producto:guardar"/"alta_producto:verificacion_db" son AMBIGUAS (el
# Guardar ya se pulsó, el alta pudo haber quedado creada en HybridLite) y por
# eso NO están acá -- quedan fuera de esta tupla y caen en la rama "ambigua"
# de _politica_resultado por descarte (no matchean ETAPAS_REINTENTABLES).
ETAPAS_REINTENTABLES = ("abrir_hybrid", "navegacion", "carga_item", "precio_item",
                        "alta_producto:abrir_ficha", "alta_producto:campos",
                        "alta_producto:costos_precios")

API_KEY = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY
if not SUPABASE_SERVICE_KEY:
    log.warning("SUPABASE_SERVICE_KEY no configurada en config.py/.env: usando la "
                "anon key, que por RLS NO puede ver compras_app de otros usuarios. "
                "Agregar SUPABASE_SERVICE_KEY para que este listener funcione de verdad.")
HEADERS = {
    "apikey": API_KEY,
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}


# ─── Guard de disponibilidad de H: ─────────────────────────────────────────────
def _h_disponible():
    """True si el .Dat de existencia es accesible (unidad H: / share montado).

    Si H: está caída (VPN, red, etc.), flujo_compra_real revienta apenas
    arranca a leer la DB de verificación. Chequear esto ANTES de pedir
    pendientes evita quemar intentos de compras válidas por una caída de red
    ajena a ellas.
    """
    return os.path.exists(read_db_existencia.RUTA)


# ─── Ventana horaria opcional (HYBRID_WRITE_WINDOW) ────────────────────────────
# Copiado (no importado) de listener_writeback.py a propósito: cada listener
# corre como proceso separado y esta lógica es corta; copiarla evita acoplar
# los dos listeners a un módulo compartido nuevo solo por esto.
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


def get_compras_pendientes():
    """Compras 'pendiente' ya emitidas por un usuario autenticado (no procesa
    borradores). `creado_por not.is.null` como segunda capa de defensa, mismo
    criterio F8 de listener_writeback: cualquier fila sin dueño autenticado no
    es una solicitud real de la app."""
    try:
        path = (f"{TABLE_CAB}?backend_status=eq.pendiente"
                f"&status=eq.emitido"
                f"&creado_por=not.is.null"
                f"&select=id,proveedor_codigo,proveedor_nombre,nota,backend_intentos"
                f"&order=id.asc&limit=10")
        return _rest("GET", path) or []
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else ""
        log.error("HTTP %s buscando compras pendientes: %s", e.code, body[:200])
        return []
    except Exception as e:
        log.error("Error buscando compras pendientes: %r", e)
        return []


def get_items(compra_id):
    """Items de una compra, mapeados a la forma que espera
    flujo_compra_real.registrar_compra: {"codigo","cantidad","costo","precio",
    "es_nuevo","referencia","descripcion"} (la tabla usa codigo_producto; el
    flujo usa "codigo"). "es_nuevo"/"referencia" son opcionales en la tabla
    (columnas todavía no migradas a la fecha de este cambio); se leen con
    .get() defensivo, así que si no existen en compras_app_items simplemente
    viajan como False/None y ningún ítem se trata como alta nueva."""
    try:
        path = (f"{TABLE_ITEMS}?compra_id=eq.{compra_id}"
                f"&select=codigo_producto,descripcion,referencia,es_nuevo,cantidad,costo,precio"
                f"&order=id.asc")
        filas = _rest("GET", path) or []
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else ""
        log.error("HTTP %s buscando items de compra %s: %s", e.code, compra_id, body[:200])
        return []
    except Exception as e:
        log.error("Error buscando items de compra %s: %r", compra_id, e)
        return []

    return [
        {
            "codigo": fila["codigo_producto"],
            "cantidad": float(fila["cantidad"]),
            "costo": float(fila["costo"]),
            "precio": float(fila["precio"]),
            "es_nuevo": bool(fila.get("es_nuevo")),
            "referencia": fila.get("referencia"),
            "descripcion": fila.get("descripcion"),
        }
        for fila in filas
    ]


def update_compra(cid, **fields):
    try:
        _rest("PATCH", f"{TABLE_CAB}?id=eq.{cid}", body=fields,
              extra_headers={"Prefer": "return=minimal"})
        return True
    except Exception as e:
        log.error("No pude actualizar compra %s: %r", cid, e)
        return False


def recuperar_huerfanos():
    """Al arrancar, marca 'error' cualquier compra que haya quedado en
    'aplicando' de una corrida anterior interrumpida (crash, kill, corte de
    luz, etc.). No se puede saber si Totalizar llegó a aplicarse en
    HybridLite antes del corte, así que se trata como ambiguo: requiere
    verificación manual antes de reencolar."""
    nota = ("Corrida interrumpida (quedó en 'aplicando'). Verificar en HybridLite "
            "si la compra se registró antes de reencolar (riesgo de compra doble).")
    try:
        recuperados = _rest(
            "PATCH", f"{TABLE_CAB}?backend_status=eq.aplicando",
            body={"backend_status": "error", "backend_resultado": nota},
            extra_headers={"Prefer": "return=representation"},
        )
        n = len(recuperados) if recuperados else 0
        if n:
            log.warning("Recuperadas %s compra(s) huérfana(s) en 'aplicando' -> 'error'.", n)
        else:
            log.debug("Sin huérfanas 'aplicando' al arrancar.")
    except Exception as e:
        log.warning("No pude chequear/recuperar huérfanas 'aplicando' (sigo igual): %r", e)


# ─── Política de reintentos / traducción resultado -> estado ──────────────────
def _politica_resultado(res, intentos):
    """Traduce un resultado {"ok","etapa","detalle",...} de
    flujo_compra_real.registrar_compra a (backend_status, backend_resultado),
    misma política F5 de listener_writeback: commit real -> 'completado'; ok
    pero sin commit -> preview, sigue 'pendiente'; fallo en etapa reintentable
    -> 'pendiente'/'error' según MAX_INTENTOS; fallo en etapa ambigua ->
    'error' inmediato."""
    if res["ok"] and HYBRID_WRITE_ENABLED and res.get("etapa") == "commit":
        return "completado", res["detalle"]
    if res["ok"]:
        return "pendiente", f"[PREVIEW] {res['detalle']}"
    etapa = res.get("etapa")
    if etapa in ETAPAS_REINTENTABLES:
        final = "error" if intentos >= MAX_INTENTOS else "pendiente"
        return final, res["detalle"]
    resultado = (f"{res['detalle']} | ATENCIÓN: la compra pudo quedar registrada a "
                 f"medias en HybridLite; verificar ANTES de reencolar (riesgo de "
                 f"compra doble).")
    return "error", resultado


# ─── Procesamiento de una compra ───────────────────────────────────────────────
def procesar_compra(compra):
    """Aplica UNA compra completa (cabecera + items) contra HybridLite. El
    estado backend_* vive en la cabecera (compras_app), no por item."""
    cid = compra["id"]
    proveedor_codigo = compra.get("proveedor_codigo")
    proveedor_nombre = compra.get("proveedor_nombre")

    intentos = (compra.get("backend_intentos") or 0) + 1
    if not update_compra(cid, backend_status="aplicando", backend_intentos=intentos):
        # No se pudo tomar el lock optimista: no se toca Hybrid esta pasada
        # (reintentable, nada se tocó).
        log.error("No pude marcar 'aplicando' la compra %s en Supabase; salteo esta pasada.", cid)
        return

    items = get_items(cid)
    if not items:
        update_compra(cid, backend_status="completado",
                      backend_resultado="Compra sin items.",
                      backend_aplicado_en=datetime.datetime.now(datetime.timezone.utc).isoformat())
        log.info("Compra %s sin items -> 'completado' sin tocar HybridLite.", cid)
        return

    doc_numero = str(cid)  # número de relleno para Total Operación (el usuario dijo que da igual)
    log.info("Procesando compra %s: proveedor=%s (%s) %s item(s), doc_numero=%s",
             cid, proveedor_codigo, proveedor_nombre, len(items), doc_numero)
    try:
        res = flujo_compra_real.registrar_compra(
            proveedor_codigo, items, doc_numero,
            commit=HYBRID_WRITE_ENABLED, proveedor_nombre=proveedor_nombre,
        )
    except Exception as e:
        res = {"ok": False, "etapa": "excepcion", "detalle": f"excepción: {e!r}"}

    status_final, resultado_final = _politica_resultado(res, intentos)
    if status_final == "completado":
        update_compra(cid, backend_status="completado", backend_resultado=resultado_final,
                      backend_aplicado_en=datetime.datetime.now(datetime.timezone.utc).isoformat())
        log.info("OK compra %s: %s", cid, resultado_final)
    elif status_final == "pendiente":
        update_compra(cid, backend_status="pendiente", backend_resultado=resultado_final)
        log.info("PENDIENTE/PREVIEW compra %s: %s", cid, resultado_final)
    else:
        update_compra(cid, backend_status="error", backend_resultado=resultado_final)
        log.error("FALLO compra %s (status=error): %s", cid, resultado_final)


# ─── Orquestación de una pasada completa ───────────────────────────────────────
_AVISO_SIN_SAFETY_CONTROL = False


def procesar_pendientes(compras):
    global _AVISO_SIN_SAFETY_CONTROL
    if not compras:
        return

    if control_seguro is None:
        if not _AVISO_SIN_SAFETY_CONTROL:
            log.warning("safety_control no disponible: procesando SIN overlay/F12/BlockInput "
                        "(degradado, ver import al inicio del módulo).")
            _AVISO_SIN_SAFETY_CONTROL = True
        for compra in compras:
            procesar_compra(compra)
    else:
        # ocultar el widget del backend (topmost, tapa/come clics de los
        # diálogos de HybridLite) mientras el bot trabaja; se restaura al salir.
        with control_seguro("REGISTRANDO COMPRAS EN HYBRIDLITE",
                            ocultar_scripts=["widget.pyw", "widget_recargo.pyw"]) as banner:
            total = len(compras)
            for n, compra in enumerate(compras, start=1):
                try:
                    banner.set_texto(
                        f"REGISTRANDO COMPRA {n}/{total} — "
                        f"OC-{compra['id']} ({compra.get('proveedor_nombre') or compra.get('proveedor_codigo')})")
                except Exception:
                    pass
                procesar_compra(compra)


def loop(once=False):
    global HYBRID_WRITE_ENABLED
    HYBRID_WRITE_ENABLED = os.environ.get("HYBRID_WRITE_ENABLED") == "1"
    log.info("=== listener_compras iniciado (HYBRID_WRITE_ENABLED=%s, tabla=%s) ===",
             HYBRID_WRITE_ENABLED, TABLE_CAB)
    # Misma lección F11 de listener_writeback: deja la fecha de modificación
    # del propio archivo en el log en cada arranque, para poder cruzar "¿qué
    # versión corrió realmente esta noche?" contra el historial de git.
    log.info("codigo listener del %s",
             datetime.datetime.fromtimestamp(os.path.getmtime(__file__)).strftime("%Y-%m-%d %H:%M"))
    if not HYBRID_WRITE_ENABLED and not once:
        log.warning("HYBRID_WRITE_ENABLED != 1: en bucle continuo NO se procesan "
                     "compras (evita tomar el mouse en preview sin fin). Usá --once "
                     "para una pasada de prueba en preview, o poné "
                     "HYBRID_WRITE_ENABLED=1 para aplicar cambios reales.")
    if HYBRID_WRITE_WINDOW_ERROR:
        log.error("%s -> FAIL-CLOSED: en bucle continuo no se procesará nada "
                   "hasta corregir la variable.", HYBRID_WRITE_WINDOW_ERROR)
    elif HYBRID_WRITE_WINDOW:
        log.info("HYBRID_WRITE_WINDOW activa: %s", _HYBRID_WRITE_WINDOW_RAW)

    recuperar_huerfanos()

    # Anti-spam: solo logueamos cuando el motivo de "no proceso nada" cambia
    # (o cuando se vuelve a estado operativo), no en cada iteración.
    ultimo_motivo_skip = None

    while True:
        HYBRID_WRITE_ENABLED = os.environ.get("HYBRID_WRITE_ENABLED") == "1"
        if not (HYBRID_WRITE_ENABLED or once):
            if once:
                break
            time.sleep(POLL_INTERVAL)
            continue

        motivo_skip = None
        try:
            if not _h_disponible():
                motivo_skip = ("h_caida", "Unidad H: (\\\\PRINCIPAL\\Happs) no accesible "
                                          "-> no se piden ni procesan compras pendientes esta pasada.")
            elif HYBRID_WRITE_ENABLED and not once and HYBRID_WRITE_WINDOW_ERROR:
                motivo_skip = ("ventana_invalida", HYBRID_WRITE_WINDOW_ERROR + " -> FAIL-CLOSED.")
            elif (HYBRID_WRITE_ENABLED and not once and HYBRID_WRITE_WINDOW
                  and not _dentro_de_ventana(HYBRID_WRITE_WINDOW)):
                motivo_skip = ("fuera_de_ventana",
                                f"Fuera de HYBRID_WRITE_WINDOW ({_HYBRID_WRITE_WINDOW_RAW}) "
                                f"-> no se procesan compras pendientes esta pasada.")

            if motivo_skip is None:
                if ultimo_motivo_skip is not None:
                    log.info("Vuelve a estado operativo: se procesan compras pendientes normalmente.")
                    ultimo_motivo_skip = None
                if HYBRID_WRITE_ENABLED or once:
                    procesar_pendientes(get_compras_pendientes())
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
