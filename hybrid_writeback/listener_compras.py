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
    Caso aparte: "verificacion_indisponible" — la compra SÍ se totalizó y lo
    único que falló fue leer la DBISAM para confirmarla (unidad H: caída a
    mitad del bucle). Tampoco se reintenta, pero se marca 'error' con un
    detalle que dice "ya registrada, NO reencolar" en vez del aviso ambiguo.
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
import sys
import datetime
import urllib.error

import listener_base as lb

import flujo_compra_real

try:
    from safety_control import control_seguro
except Exception:  # pragma: no cover
    control_seguro = None

log = lb.setup_logging("compras", "compras.log")
if lb.AVISO_SIN_SERVICE_KEY:
    log.warning(lb.AVISO_SIN_SERVICE_KEY)

TABLE_CAB = "compras_app"
TABLE_ITEMS = "compras_app_items"
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

# Etapas donde lo que falló fue LEER la DBISAM para confirmar, no la escritura
# (flujo_compra_real.VerificacionIndisponible: la unidad H: se cae de a ratos).
# Tampoco se reintentan -- el documento ya está en HybridLite y reencolarlo
# sería una compra doble -- pero su detalle ya dice exactamente eso, así que no
# se le pega encima el "pudo quedar a medias" genérico, que manda a buscar un
# desastre que no existe. Lección de la compra 35 (2026-08-13): quedó marcada
# 'error' con un aviso alarmante cuando en realidad sus 9 ítems estaban perfectos.
ETAPAS_VERIFICACION_ILEGIBLE = ("verificacion_indisponible",
                                "alta_producto:verificacion_indisponible")


def get_compras_pendientes():
    """Compras 'pendiente' ya emitidas por un usuario autenticado (no procesa
    borradores). `creado_por not.is.null` como segunda capa de defensa, mismo
    criterio F8 de listener_writeback: cualquier fila sin dueño autenticado no
    es una solicitud real de la app."""
    try:
        path = (f"{TABLE_CAB}?backend_status=eq.pendiente"
                f"&status=eq.emitido"
                f"&creado_por=not.is.null"
                f"&select=id,proveedor_codigo,proveedor_nombre,nota,backend_intentos,numero_documento"
                f"&order=id.asc&limit=10")
        return lb.rest("GET", path) or []
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
        filas = lb.rest("GET", path) or []
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
        lb.rest("PATCH", f"{TABLE_CAB}?id=eq.{cid}", body=fields,
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
        recuperados = lb.rest(
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
    -> 'pendiente'/'error' según MAX_INTENTOS; verificación ilegible ->
    'error' con el aviso de que SÍ quedó registrada; fallo en etapa ambigua ->
    'error' inmediato."""
    if res["ok"] and lb.check_hybrid_write_enabled() and res.get("etapa") == "commit":
        return "completado", res["detalle"]
    if res["ok"]:
        return "pendiente", f"[PREVIEW] {res['detalle']}"
    etapa = res.get("etapa")
    if etapa in ETAPAS_REINTENTABLES:
        final = "error" if intentos >= MAX_INTENTOS else "pendiente"
        return final, res["detalle"]
    if etapa in ETAPAS_VERIFICACION_ILEGIBLE:
        return "error", res["detalle"]
    resultado = (f"{res['detalle']} | ATENCIÓN: la compra pudo quedar registrada a "
                 f"medias en HybridLite; verificar ANTES de reencolar (riesgo de "
                 f"compra doble).")
    return "error", resultado


# ─── Procesamiento de una compra ───────────────────────────────────────────────
def procesar_compra(compra, n=1, total=1):
    """Aplica UNA compra completa (cabecera + items) contra HybridLite. El estado
    backend_* vive en la cabecera (compras_app), no por item."""
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

    # Número de orden/factura: si el usuario lo escribió en la app (columna
    # numero_documento), se usa ese en los dos campos de Total Operación. Si
    # lo dejó en blanco -- o solo tiene caracteres no numéricos, ya que
    # _totalizar_compra exige al menos un dígito -- se cae al id de la compra
    # (relleno, comportamiento previo).
    numero_doc_app = compra.get("numero_documento")
    if numero_doc_app and any(ch.isdigit() for ch in str(numero_doc_app)):
        doc_numero = str(numero_doc_app)
        origen_doc_numero = "numero_documento de la app"
    else:
        doc_numero = str(cid)
        origen_doc_numero = "id de la compra (numero_documento vacío)"
    log.info("Procesando compra %s: proveedor=%s (%s) %s item(s), doc_numero=%s (%s)",
             cid, proveedor_codigo, proveedor_nombre, len(items), doc_numero, origen_doc_numero)

    txt_banner = f"REGISTRANDO COMPRA {n}/{total} — OC-{cid} ({proveedor_nombre or proveedor_codigo})"
    try:
        if control_seguro is not None:
            with control_seguro(txt_banner, ocultar_scripts=["widget.pyw", "widget_recargo.pyw"]):
                res = flujo_compra_real.registrar_compra(
                    proveedor_codigo, items, doc_numero,
                    commit=lb.check_hybrid_write_enabled(), proveedor_nombre=proveedor_nombre,
                )
        else:
            res = flujo_compra_real.registrar_compra(
                proveedor_codigo, items, doc_numero,
                commit=lb.check_hybrid_write_enabled(), proveedor_nombre=proveedor_nombre,
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

    if control_seguro is None and not _AVISO_SIN_SAFETY_CONTROL:
        log.warning("safety_control no disponible: procesando SIN overlay/F12/BlockInput "
                    "(degradado, ver import al inicio del módulo).")
        _AVISO_SIN_SAFETY_CONTROL = True

    total = len(compras)
    for n, compra in enumerate(compras, start=1):
        procesar_compra(compra, n=n, total=total)


if __name__ == "__main__":
    lb.correr_loop(log, __file__, "listener_compras", get_compras_pendientes, procesar_pendientes,
                    recuperar_huerfanos, once=("--once" in sys.argv), sujeto="compras",
                    ceder_si=lb.hay_pendientes_prioritarios)
