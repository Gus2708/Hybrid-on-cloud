"""
listener_writeback.py — Canal App (El Serrucho Go) -> Local (write-back de
stock, precio, costo y ficha (descripción/referencia)).

Sondea `ordenes_cambio_items` (tabla que la app YA llena al emitir una Orden de
Cambio, ver el-serrucho-go/src/hooks/useOrdenCambio.ts) y, por cada item de una
orden con status='emitido' que todavía no fue aplicado, ajusta stock, precio/
costo y/o descripción/referencia en HybridLite vía flujo_stock_real.py,
flujo_precio_real.py y flujo_ficha_real.py (input real de hardware). El
`delta` de stock ya viene calculado por la app (nueva_existencia -
existencia_actual); el `costo` viene como snapshot en TODOS los items (haya
cambiado o no) y se compara contra HybridLite antes de decidir si hay que
escribirlo; `nueva_descripcion`/`nueva_referencia` solo vienen cuando el
usuario pidió ese cambio. Marca el resultado en columnas `backend_*`
(migración 018 en el-serrucho-go; vocabulario de estados `pendiente /
aplicando / error / completado`, backfill en migración 019).

No toca `ordenes_cambio.status` ni el PDF: ese flujo lo sigue manejando la app
igual que hoy. Este listener corre en paralelo, es independiente.

RLS de `ordenes_cambio_items` solo deja ver/editar al dueño autenticado, así que
el backend necesita SUPABASE_SERVICE_KEY (config.py) para leer las filas de
todos los usuarios. Con solo la anon key el listener vería siempre 0 filas —
no es un error, es RLS filtrando en silencio.

ORQUESTACIÓN por pasada (procesar_pendientes): los pendientes se agrupan por
orden_id (preservando el orden por id asc de get_pendientes) y se procesan en
TRES FASES GLOBALES (pedido del dueño: primero TODAS las cantidades, después
TODOS los precios, y por último TODOS los cambios de ficha):
  1. FASE STOCK GLOBAL. Para cada orden con items de stock, un documento de
     ajuste: 2+ items -> flujo_stock_real.ajustar_stock_lote (abre la ventana
     una vez, totaliza una vez; lotes largos se trocean en documentos de
     MAX_FILAS_LOTE filas); 1 item -> ajustar_stock individual. Todas las
     órdenes hacen su fase de stock ANTES de tocar ningún precio.
  2. FASE PRECIO/COSTO GLOBAL después, item por item de todas las órdenes
     (flujo_precio_real.set_precio_costo: costo PRIMERO, precio después, en
     una sola sesión de Ficha, que se reutiliza entre items consecutivos).
     Si un item tenía parte de stock y esa parte FALLÓ, su parte de
     precio/costo NO se ejecuta esta pasada (se reintenta completa en la
     próxima corrida; precio y costo son valores absolutos e idempotentes,
     así que repetir la parte de stock ya aplicada junto con precio/costo no
     hace daño).
  3. FASE FICHA GLOBAL (descripción/referencia) al final, item por item, vía
     flujo_ficha_real.set_ficha (Modificar + buscar + cargar, reutilizando la
     misma Ficha que la fase 2). Descripción/referencia son valores absolutos
     e idempotentes, así que no hay chequeo de "¿falló una fase anterior?":
     se procesan siempre que el item tenga metadata pendiente.
El banner de seguridad muestra el avance en vivo (orden/fase/ítem actual).
El estado final de cada item es la fusión de las partes que efectivamente se
ejecutaron (Stock y/o Precio/Costo y/o Ficha): 'completado' solo si todas
cerraron en etapa "commit"; '[PREVIEW] ...' si todas fueron ok pero sin commit
real; si alguna parte falló, se aplica la política de reintentos de siempre
sobre ESA parte (ver SEGURIDAD más abajo).

SEGURIDAD:
  * Mientras HYBRID_WRITE_ENABLED no sea "1", cada item se procesa en modo
    PREVIEW (commit=False): navega y verifica en pantalla, pero cancela sin
    persistir nada en HybridLite.
  * Todo el procesamiento de una pasada (si hay al menos un item pendiente)
    corre dentro de `with control_seguro():` (safety_control.py): banner
    rojo topmost + hotkey F12 de aborto + BlockInput si hay privilegios de
    admin. Si el módulo no está disponible (import falla), se degrada con
    gracia: procesa igual pero SIN overlay, con un log.warning una sola vez
    (no por pasada, por vida del proceso).
  * `delta` NULL -> error inmediato (dato mal generado, no se reintenta).
    `delta` 0 -> se marca 'completado' sin tocar HybridLite (nada que aplicar).
  * Detección de cambio de costo, fail-closed: se compara el `costo` del item
    contra flujo_precio_real.db_costo_usd(codigo) (lectura directa de DBISAM,
    sin abrir la ficha). Si esa lectura devuelve None (no se puede leer), NO
    se asume que hay cambio de costo — abrir la ficha de cada item a ciegas
    "por si acaso" sería más riesgoso que no tocar el costo esa pasada. Se
    avisa con un log.warning una sola vez por proceso.
  * Guard de unidad `H:`: si `TExistenciaInv.Dat` no es accesible (caída de
    red / VPN), la pasada NO pide pendientes ni procesa nada (evita quemar
    intentos por un FileNotFoundError de arranque).
  * Ventana horaria opcional `HYBRID_WRITE_WINDOW` ("HH:MM-HH:MM", hora local,
    soporta cruce de medianoche): fuera de la ventana el bucle continuo no
    procesa nada. Si está seteada pero no parsea, es FAIL-CLOSED (no procesa).
    Solo aplica al bucle continuo con HYBRID_WRITE_ENABLED=1; `--once` la
    ignora (corrida manual supervisada).
  * Reintentos limitados y conservadores: un fallo en una etapa PRE-commit
    ("abrir_hybrid", "carga/conteo", "escritura", "aceptar") reintenta hasta
    MAX_INTENTOS; un fallo en cualquier etapa AMBIGUA (post-commit, o
    excepción) marca 'error' de inmediato, sin reintentar — el ajuste de
    stock es relativo (delta) y reintentar un commit ambiguo puede aplicarlo
    dos veces y desajustar el inventario real.
  * Al arrancar, recupera huérfanos: items que quedaron en 'aplicando' por una
    corrida anterior interrumpida se marcan 'error' (mismo motivo: no se sabe
    si el commit llegó a aplicarse).
  * En bucle continuo (sin --once), si HYBRID_WRITE_ENABLED != 1 no se procesa
    nada (evita tomar el mouse en preview sin fin cada POLL_INTERVAL).
  * Al arrancar, se loguea la fecha de modificación del propio archivo
    (`codigo listener del ...`) — lección de un incidente real donde un
    proceso viejo quedó corriendo en memoria y procesó pendientes con código
    stale sin que nadie lo notara; ahora queda en writeback.log para cruzar
    contra el historial de git.

Uso:
    python listener_writeback.py            # bucle continuo
    python listener_writeback.py --once     # una sola pasada (para pruebas)
"""
import sys
import datetime
import urllib.error

import listener_base as lb

import flujo_stock_real
import flujo_precio_real
import flujo_ficha_real

try:
    from safety_control import control_seguro
except Exception:  # pragma: no cover
    control_seguro = None

log = lb.setup_logging("writeback", "writeback.log")
if lb.AVISO_SIN_SERVICE_KEY:
    log.warning(lb.AVISO_SIN_SERVICE_KEY)

TABLE = "ordenes_cambio_items"
MAX_INTENTOS = 3

# Etapas de flujo_stock_real.ajustar_stock[_lote]() y flujo_precio_real.
# set_precio_costo() anteriores a cualquier commit en HybridLite: un fallo ahí
# es reintentable sin riesgo. Cualquier otra etapa (post-commit, ambigua) o
# una excepción se tratan como error inmediato — ver _politica_resultado (F5).
ETAPAS_REINTENTABLES = ("abrir_hybrid", "carga/conteo", "escritura", "aceptar")


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
                f"precio_actual,nuevo_precio,costo,"
                f"nueva_descripcion,nueva_referencia,"
                f"ordenes_cambio!inner(status,creado_por)"
                f"&ordenes_cambio.status=eq.emitido"
                f"&ordenes_cambio.creado_por=not.is.null"
                f"&order=id.asc&limit=50")
        return lb.rest("GET", path) or []
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else ""
        log.error("HTTP %s buscando pendientes: %s", e.code, body[:200])
        return []
    except Exception as e:
        log.error("Error buscando pendientes: %r", e)
        return []


def update_item(iid, **fields):
    try:
        lb.rest("PATCH", f"{TABLE}?id=eq.{iid}", body=fields,
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
        recuperados = lb.rest(
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


# ─── Detección de cambios por item ─────────────────────────────────────────────
_AVISO_SIN_SAFETY_CONTROL = False
_AVISO_SIN_COSTO_DB = False


def _tiene_stock_cambio(item):
    delta = item.get("delta")
    nueva_existencia = item.get("nueva_existencia")
    return nueva_existencia is not None and delta is not None and float(delta) != 0


def _tiene_precio_cambio(item):
    precio_actual = item.get("precio_actual")
    nuevo_precio = item.get("nuevo_precio")
    return nuevo_precio is not None and precio_actual is not None and float(nuevo_precio) != float(precio_actual)


def _tiene_costo_cambio(item, cache_costo_db):
    """F9 — costo vía DBISAM, fail-closed.

    La app manda `costo` como snapshot en TODOS los items (haya cambiado o
    no), así que no alcanza con "item trae costo": hay que comparar contra lo
    que hoy tiene HybridLite (flujo_precio_real.db_costo_usd, lectura directa
    de DBISAM, sin abrir la ficha). Si esa lectura falla (None), NO asumimos
    que hay cambio — abrir la ficha de cada item a ciegas para "ver si acaso"
    sería más riesgoso que no tocar el costo esta pasada. Se avisa una sola
    vez por proceso (no una vez por item) para no inundar el log.
    """
    global _AVISO_SIN_COSTO_DB
    costo = item.get("costo")
    if costo is None:
        return False
    codigo = item.get("codigo_producto")
    if codigo not in cache_costo_db:
        try:
            cache_costo_db[codigo] = flujo_precio_real.db_costo_usd(codigo)
        except Exception as e:
            log.warning("db_costo_usd(%s) lanzó excepción, tratando como no legible: %r", codigo, e)
            cache_costo_db[codigo] = None
    db_costo = cache_costo_db[codigo]
    if db_costo is None:
        if not _AVISO_SIN_COSTO_DB:
            log.warning("no puedo leer costo de DBISAM; cambios de costo no se aplicarán "
                        "automáticamente esta pasada.")
            _AVISO_SIN_COSTO_DB = True
        return False
    return abs(float(costo) - float(db_costo)) > 0.01


def _tiene_metadata_cambio(item):
    """Descripción/referencia son valores ABSOLUTOS que la app manda solo
    cuando el usuario pidió cambiarlos (a diferencia de `costo`, que viaja
    siempre como snapshot): basta con que vengan no vacíos."""
    nd = item.get("nueva_descripcion")
    nr = item.get("nueva_referencia")
    return (nd is not None and str(nd).strip() != "") or (nr is not None and str(nr).strip() != "")


# ─── Política de reintentos / traducción resultado -> estado ──────────────────
def _politica_resultado(res, intentos):
    """Traduce un resultado {"ok","etapa","detalle"} de un flujo a
    (status, resultado) según la política conservadora de F5:
    commit real -> 'completado'; ok pero sin commit -> preview, sigue
    'pendiente'; fallo en etapa reintentable -> 'pendiente'/'error' según
    MAX_INTENTOS; fallo en etapa ambigua -> 'error' inmediato."""
    if res["ok"] and lb.check_hybrid_write_enabled() and res.get("etapa") == "commit":
        return "completado", res["detalle"]
    if res["ok"]:
        return "pendiente", f"[PREVIEW] {res['detalle']}"
    etapa = res.get("etapa")
    if etapa in ETAPAS_REINTENTABLES:
        final = "error" if intentos >= MAX_INTENTOS else "pendiente"
        return final, res["detalle"]
    resultado = (f"{res['detalle']} | ATENCIÓN: fallo en etapa ambigua "
                 f"(etapa={etapa!r}) — verificar en HybridLite si el ajuste "
                 f"se aplicó ANTES de reencolar manualmente (riesgo de "
                 f"ajuste doble/precio parcial).")
    return "error", resultado


def _aplicar_resultado_final(iid, partes, intentos):
    """Fusiona 1 o 2 partes ({"nombre": str, "res": dict}) en el estado final
    de un item y persiste con update_item(). `partes` solo trae las fases que
    realmente se ejecutaron (una fase salteada por F10 no aparece acá)."""
    combinados = []
    peor_status_rank = {"completado": 0, "pendiente": 1, "error": 2}
    status_final = "completado"
    stock_commiteado = False
    for parte in partes:
        status, resultado = _politica_resultado(parte["res"], intentos)
        combinados.append(f"{parte['nombre']}: {resultado}")
        if parte["nombre"] == "Stock" and status == "completado":
            stock_commiteado = True
        if peor_status_rank[status] > peor_status_rank[status_final]:
            status_final = status

    # GUARDA anti doble-ajuste de kardex (audit 2026-07-23): el Stock es un delta
    # RELATIVO (documento permanente). Si esa parte YA commiteó pero una fase
    # hermana (Precio/Costo/Ficha) quedó 'pendiente' para reintento, reencolar el
    # item haría que el próximo pase RE-APLIQUE el delta sobre una existencia que
    # ya lo incluye -> DOBLE ajuste. Se degrada a 'error' (revisión manual, misma
    # filosofía que las etapas ambiguas): el stock aplicado NO se pierde; solo la
    # fase hermana pendiente hay que re-emitirla a mano. Precio/Costo/Ficha son
    # valores ABSOLUTOS e idempotentes, así que si commitean y falla el stock (u
    # otra absoluta) reencolar es seguro y esta guarda no aplica. Reachability
    # ínfima -la app separa stock de precio/ficha en items distintos- pero el
    # blindaje es barato y cierra el hueco a futuro.
    if stock_commiteado and status_final == "pendiente":
        status_final = "error"
        combinados.append("ATENCIÓN: el STOCK ya se aplicó (delta de kardex) pero otra "
                          "fase quedó pendiente; NO se reencola para no re-aplicar el delta "
                          "(doble ajuste). Aplicar la fase faltante a mano.")

    resultado_final = " | ".join(combinados)
    if status_final == "completado":
        update_item(iid, backend_status="completado", backend_resultado=resultado_final,
                    backend_aplicado_en=datetime.datetime.now(datetime.timezone.utc).isoformat())
        log.info("OK item %s: %s", iid, resultado_final)
    elif status_final == "pendiente":
        update_item(iid, backend_status="pendiente", backend_resultado=resultado_final)
        log.info("PENDIENTE/PREVIEW item %s: %s", iid, resultado_final)
    else:
        update_item(iid, backend_status="error", backend_resultado=resultado_final)
        log.error("FALLO item %s (status=error): %s", iid, resultado_final)
    return status_final


# ─── Fase STOCK de una orden (F10 — lote si hay >=2 items) ─────────────────────
_LOCK_FALLIDO = {"ok": False, "etapa": "carga/conteo",
                  "detalle": "No pude marcar 'aplicando' en Supabase (fallo de red/API); "
                             "no se tocó HybridLite para este item, reintentable."}


def _fase_stock_orden(items_con_stock):
    """Aplica la parte de stock de una orden. Devuelve dict[item_id -> dict con
    resultado de flujo_stock_real] SOLO para los items con cambio de stock."""
    resultados = {}
    if not items_con_stock:
        return resultados

    if len(items_con_stock) >= 2:
        lote = []
        for item in items_con_stock:
            iid = item["id"]
            intentos = (item.get("backend_intentos") or 0) + 1
            if not update_item(iid, backend_status="aplicando", backend_intentos=intentos):
                # No se pudo tomar el lock optimista: fuera del lote, no se
                # toca Hybrid para este item esta pasada (reintentable).
                resultados[iid] = dict(_LOCK_FALLIDO)
                continue
            lote.append({"item_id": iid, "codigo": item.get("codigo_producto"),
                         "delta": float(item["delta"])})
        if lote:
            log.info("Fase stock en LOTE: %s item(s) -> ajustar_stock_lote", len(lote))
            try:
                res_lote = flujo_stock_real.ajustar_stock_lote(lote, commit=lb.check_hybrid_write_enabled())
            except Exception as e:
                res_lote = {"ok": False, "etapa": "excepcion", "detalle": f"excepción: {e!r}", "resultados": {}}
            resultados_por_id = res_lote.get("resultados") or {}
            for entrada in lote:
                iid = entrada["item_id"]
                if iid in resultados_por_id:
                    resultados[iid] = resultados_por_id[iid]
                else:
                    # El lote entero falló antes de poder discriminar por fila
                    # (p.ej. excepción o fallo abriendo Hybrid): todos heredan
                    # el resultado global del lote.
                    resultados[iid] = {"ok": res_lote["ok"], "etapa": res_lote["etapa"],
                                        "detalle": res_lote["detalle"]}
    else:
        item = items_con_stock[0]
        iid = item["id"]
        intentos = (item.get("backend_intentos") or 0) + 1
        if not update_item(iid, backend_status="aplicando", backend_intentos=intentos):
            resultados[iid] = dict(_LOCK_FALLIDO)
            return resultados
        codigo = item.get("codigo_producto")
        delta = float(item["delta"])
        log.info("Fase stock INDIVIDUAL: item %s codigo=%s delta=%s", iid, codigo, delta)
        try:
            resultados[iid] = flujo_stock_real.ajustar_stock(codigo, delta,
                                                              commit=lb.check_hybrid_write_enabled(), delta=True)
        except Exception as e:
            resultados[iid] = {"ok": False, "etapa": "excepcion", "detalle": f"excepción: {e!r}"}

    return resultados


# ─── Fase PRECIO/COSTO de un item ──────────────────────────────────────────────
def _fase_precio_costo_item(item, ya_estaba_aplicando):
    """Aplica la parte de precio/costo de UN item. `ya_estaba_aplicando`
    indica si el item ya venía marcado 'aplicando' por la fase de stock (para
    no reescribir backend_intentos dos veces)."""
    iid = item["id"]
    codigo = item.get("codigo_producto")
    nuevo_precio = item.get("nuevo_precio")
    costo = item.get("costo")
    tiene_precio = _tiene_precio_cambio(item)
    tiene_costo = item.get("_tiene_costo_cambio", False)

    if not ya_estaba_aplicando:
        intentos = (item.get("backend_intentos") or 0) + 1
        if not update_item(iid, backend_status="aplicando", backend_intentos=intentos):
            return dict(_LOCK_FALLIDO)

    log.info("Fase precio/costo: item %s codigo=%s nuevo_precio=%s nuevo_costo=%s",
              iid, codigo, nuevo_precio if tiene_precio else None, costo if tiene_costo else None)
    try:
        return flujo_precio_real.set_precio_costo(
            codigo,
            nuevo_precio=float(nuevo_precio) if tiene_precio else None,
            nuevo_costo=float(costo) if tiene_costo else None,
            commit=lb.check_hybrid_write_enabled(),
        )
    except Exception as e:
        return {"ok": False, "etapa": "excepcion", "detalle": f"excepción: {e!r}"}


# ─── Fase FICHA (descripción/referencia) de un item ────────────────────────────
def _fase_metadata_item(item, ya_estaba_aplicando):
    """Aplica la parte de descripción/referencia de UN item. `ya_estaba_aplicando`
    indica si el item ya venía marcado 'aplicando' por una fase anterior (stock
    o precio/costo) esta misma pasada, para no reescribir backend_intentos ni
    volver a tomar el lock optimista dos veces."""
    iid = item["id"]
    codigo = item.get("codigo_producto")
    nd = item.get("nueva_descripcion")
    nr = item.get("nueva_referencia")
    nd = str(nd).strip() if nd is not None and str(nd).strip() != "" else None
    nr = str(nr).strip() if nr is not None and str(nr).strip() != "" else None

    if not ya_estaba_aplicando:
        intentos = (item.get("backend_intentos") or 0) + 1
        if not update_item(iid, backend_status="aplicando", backend_intentos=intentos):
            return dict(_LOCK_FALLIDO)

    log.info("Fase Ficha (descripcion/referencia): item %s codigo=%s nueva_descripcion=%s "
              "nueva_referencia=%s", iid, codigo, nd, nr)
    try:
        return flujo_ficha_real.set_ficha(
            codigo, nueva_descripcion=nd, nueva_referencia=nr,
            commit=lb.check_hybrid_write_enabled(),
        )
    except Exception as e:
        # etapa reintentable: descripción/referencia son valores absolutos e
        # idempotentes (ver docstring de flujo_ficha_real), así que incluso
        # una excepción inesperada acá es segura de reintentar.
        return {"ok": False, "etapa": "aceptar", "detalle": f"excepción: {e!r}"}


# ─── Orquestación de una pasada completa ───────────────────────────────────────
def procesar_pendientes(items):
    """Agrupa `items` (ya ordenados por id asc, ver get_pendientes) por orden,
    y por cada orden corre FASE STOCK (lote si hay >=2 items con cambio de
    stock) y luego FASE PRECIO/COSTO item por item. Ver docstring del módulo
    (sección ORQUESTACIÓN) para la política completa."""
    global _AVISO_SIN_SAFETY_CONTROL
    if not items:
        return

    if control_seguro is None:
        if not _AVISO_SIN_SAFETY_CONTROL:
            log.warning("safety_control no disponible: procesando SIN overlay/F12/BlockInput "
                        "(degradado, ver import al inicio del módulo).")
            _AVISO_SIN_SAFETY_CONTROL = True
        _procesar_pendientes_impl(items)
    else:
        # ocultar el widget del backend (topmost, tapa/come clics de los
        # diálogos de HybridLite) mientras el bot trabaja; se restaura al salir.
        with control_seguro(ocultar_scripts=["widget.pyw", "widget_recargo.pyw"]) as banner:
            _procesar_pendientes_impl(items, banner)


def _texto_item(item):
    """Etiqueta legible de un item para el panel lateral de pendientes."""
    desc = (item.get("descripcion") or "").strip()
    codigo = item.get("codigo_producto") or "?"
    return f"{desc} ({codigo})" if desc else codigo


def _procesar_pendientes_impl(items, banner=None):
    """TRES FASES GLOBALES sobre todas las órdenes de la pasada (pedido del
    dueño): primero TODAS las cantidades (un documento de ajuste por orden),
    después TODOS los precios/costos, y por último TODOS los cambios de
    descripción/referencia. Además de respetar el orden natural del trabajo,
    evita intercalar ventanas: la Ficha se reutiliza entre todos los items de
    las fases 2 y 3 sin que un ajuste de stock intermedio obligue a cerrarla y
    reabrirla."""

    def _avisar(texto):
        # actualiza la línea principal del banner de seguridad (si existe)
        if banner is None:
            return
        try:
            banner.set_texto(texto)
        except Exception:
            pass

    # panel lateral: lista completa de items de la pasada, tachando los que
    # ya quedaron 'completado' (a medida que se van resolviendo). El orden
    # de aparición es el de `items` (ya viene por id asc de get_pendientes).
    orden_lista = [item["id"] for item in items]
    textos_por_id = {item["id"]: _texto_item(item) for item in items}
    hecho_por_id = {item["id"]: False for item in items}

    def _refrescar_lista():
        if banner is None:
            return
        try:
            banner.set_lista([(textos_por_id[iid], hecho_por_id[iid]) for iid in orden_lista])
        except Exception:
            pass

    _refrescar_lista()

    ordenes = {}
    for item in items:
        ordenes.setdefault(item.get("orden_id"), []).append(item)

    cache_costo_db = {}
    items_por_id = {}
    partes_por_item = {}
    stock_por_orden = []        # [(orden_id, [items_con_stock])] en orden de llegada
    precio_costo_global = []    # items con cambio de precio/costo, todas las órdenes
    metadata_global = []        # items con cambio de descripción/referencia, todas las órdenes

    # ── Clasificación global + completar los items sin cambios ────────────────
    for orden_id, items_orden in ordenes.items():
        log.info("=== Orden %s: %s item(s) pendiente(s) ===", orden_id, len(items_orden))
        items_con_stock = []
        for item in items_orden:
            items_por_id[item["id"]] = item
            item["_tiene_stock_cambio"] = _tiene_stock_cambio(item)
            item["_tiene_precio_cambio"] = _tiene_precio_cambio(item)
            item["_tiene_costo_cambio"] = _tiene_costo_cambio(item, cache_costo_db)
            item["_tiene_metadata_cambio"] = _tiene_metadata_cambio(item)
            if (not item["_tiene_stock_cambio"] and not item["_tiene_precio_cambio"]
                    and not item["_tiene_costo_cambio"] and not item["_tiene_metadata_cambio"]):
                update_item(item["id"], backend_status="completado",
                            backend_resultado="Sin cambios de stock, precio, costo ni "
                                               "descripción/referencia a realizar.",
                            backend_aplicado_en=datetime.datetime.now(datetime.timezone.utc).isoformat())
                log.info("Item %s sin cambios reales -> 'completado' sin tocar HybridLite.", item["id"])
                hecho_por_id[item["id"]] = True
                _refrescar_lista()
                continue
            if item["_tiene_stock_cambio"]:
                items_con_stock.append(item)
            if item["_tiene_precio_cambio"] or item["_tiene_costo_cambio"]:
                precio_costo_global.append(item)
            if item["_tiene_metadata_cambio"]:
                metadata_global.append(item)
        if items_con_stock:
            stock_por_orden.append((orden_id, items_con_stock))

    # ── FASE 1 GLOBAL: todas las CANTIDADES (un documento por orden) ──────────
    resultados_stock = {}
    for orden_id, items_con_stock in stock_por_orden:
        _avisar(f"AJUSTANDO STOCK — ORDEN OC-{orden_id} ({len(items_con_stock)} PRODUCTO/S)")
        try:
            res_orden = _fase_stock_orden(items_con_stock)
        except Exception as e:
            res_orden = {item["id"]: {"ok": False, "etapa": "excepcion", "detalle": f"excepción: {e!r}"}
                         for item in items_con_stock}
        resultados_stock.update(res_orden)
    for iid, res in resultados_stock.items():
        partes_por_item.setdefault(iid, []).append({"nombre": "Stock", "res": res})

    # ── FASE 2 GLOBAL: todos los PRECIOS/COSTOS, item por item ───────────────
    total_pc = len(precio_costo_global)
    for n, item in enumerate(precio_costo_global, start=1):
        iid = item["id"]
        stock_res = resultados_stock.get(iid)
        if stock_res is not None and not stock_res["ok"]:
            # F10 — el item tenía parte de stock y falló: no tocamos su
            # parte de precio/costo esta pasada (el reintento re-corre
            # todo; precio/costo son valores absolutos e idempotentes).
            log.warning("Item %s: se salta fase precio/costo esta pasada porque su "
                        "parte de stock falló (etapa=%s).", iid, stock_res.get("etapa"))
            continue
        _avisar(f"CAMBIANDO PRECIO/COSTO {n}/{total_pc} — {item.get('codigo_producto')}")
        try:
            res_pc = _fase_precio_costo_item(item, ya_estaba_aplicando=iid in resultados_stock)
        except Exception as e:
            res_pc = {"ok": False, "etapa": "excepcion", "detalle": f"excepción: {e!r}"}
        partes_por_item.setdefault(iid, []).append({"nombre": "Precio/Costo", "res": res_pc})

    # ── FASE 3 GLOBAL: descripción/referencia (Ficha), item por item ──────────
    # `aplicando_ids` acumula todo item ya marcado 'aplicando' en las fases 1 y
    # 2 de ESTA pasada, para que _fase_metadata_item no vuelva a tomar el lock
    # optimista ni a pisar backend_intentos por segunda/tercera vez.
    aplicando_ids = set(resultados_stock.keys()) | {item["id"] for item in precio_costo_global}
    total_meta = len(metadata_global)
    for n, item in enumerate(metadata_global, start=1):
        iid = item["id"]
        ya_estaba_aplicando = iid in aplicando_ids
        _avisar(f"EDITANDO DATOS {n}/{total_meta} — {item.get('codigo_producto')}")
        try:
            res_meta = _fase_metadata_item(item, ya_estaba_aplicando)
        except Exception as e:
            res_meta = {"ok": False, "etapa": "excepcion", "detalle": f"excepción: {e!r}"}
        partes_por_item.setdefault(iid, []).append({"nombre": "Ficha", "res": res_meta})

    # ── Estados finales por item ───────────────────────────────────────────────
    _avisar("GUARDANDO RESULTADOS…")
    for iid, partes in partes_por_item.items():
        item = items_por_id[iid]
        intentos = (item.get("backend_intentos") or 0) + 1
        status_final = _aplicar_resultado_final(iid, partes, intentos)
        if status_final == "completado":
            hecho_por_id[iid] = True
            _refrescar_lista()

    # Higiene de cierre: el flujo de precio/costo deja la Ficha abierta a
    # propósito (la reutiliza entre items de la misma pasada), pero no debe
    # quedar abierta en el POS al terminar — un empleado podría encontrarla
    # y guardar algo sin querer.
    try:
        flujo_stock_real._cerrar_ficha_si_abierta()
    except Exception as e:
        log.warning("No pude cerrar la Ficha al final de la pasada: %r", e)

    # La instancia de Hybrid usada es una AISLADA (ver abrir_hybrid.py), nunca
    # la del empleado: minimizarla (no cerrarla) evita dejar una segunda
    # ventana de Hybrid tapando la pantalla; se restaura sola en la próxima
    # pasada que tenga trabajo pendiente.
    try:
        import abrir_hybrid
        abrir_hybrid.minimizar_aislada()
    except Exception as e:
        log.warning("No pude minimizar la instancia aislada de Hybrid: %r", e)


if __name__ == "__main__":
    lb.correr_loop(log, __file__, "listener_writeback", get_pendientes, procesar_pendientes,
                    recuperar_huerfanos, once=("--once" in sys.argv), sujeto="items",
                    ceder_si=lb.hay_pendientes_prioritarios)
