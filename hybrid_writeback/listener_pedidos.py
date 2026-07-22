"""
listener_pedidos.py — Canal App (El Serrucho Go, Pedidos) -> Local (write-back de
pedidos a HybridLite).

Sondea `pedidos_app` (cabecera) / `pedidos_app_items` (detalle) — tablas que la
app llena al emitir un PEDIDO (cliente + items con cantidad) — y por cada pedido
con status='emitido' que todavía no fue aplicado, lo registra en HybridLite como
"Pédidos de clientes" (documento Tipo 10 / Status 4) vía
flujo_pedido_real.registrar_pedido (input real de hardware). Caja lo factura
después enlazando por DOCUMENTOORIGEN. Marca el resultado en las columnas
`backend_*` de la CABECERA (un pedido = UN documento de Hybrid, un solo Totalizar)
y guarda en `documento_hybrid` el número que Hybrid autoasignó (ej '00004692').

HERMANO de listener_compras.py / listener_writeback.py (mismo esqueleto de
listener_base: guard de H:, ventana horaria, HYBRID_WRITE_ENABLED, control_seguro,
mutex del mouse que serializa los tres listeners, política de reintentos).

Diferencias con compras: los items NO llevan costo/precio (el pedido usa el precio
maestro del producto), NO hay número de documento (Hybrid lo autoasigna), y el
pedido NO mueve el kardex (bajo riesgo; un pedido errado se cancela/ignora).

RLS de pedidos_app/pedidos_app_items deja ver/escribir a empleados activos (un
pedido es venta de primera línea, no compra), así que el backend necesita
SUPABASE_SERVICE_KEY (config.py) para leer los pedidos de todos los usuarios. Con
solo la anon key vería 0 filas — RLS filtrando en silencio, sin error.

SEGURIDAD (calcada de listener_compras, ver ese módulo para el detalle):
  * Mientras HYBRID_WRITE_ENABLED no sea "1", cada pedido se procesa en modo
    PREVIEW (commit=False): arma y verifica en pantalla, pero cancela sin
    persistir (todo-o-nada, ver flujo_pedido_real.registrar_pedido).
  * Todo corre dentro de `with control_seguro():` (banner + F12 + BlockInput).
  * Guard de unidad H:, ventana horaria opcional (fail-closed si mal seteada).
  * Reintentos: fallo PRE-Totalizar ("abrir_hybrid","navegacion","carga_item") es
    reintentable hasta MAX_INTENTOS (el pedido se cancela completo antes de
    devolver esas etapas). Fallo AMBIGUO ("totalizar","verificacion_db",excepción)
    -> 'error' inmediato sin reintentar (pudo quedar a medias; reencolar arriesga
    un pedido doble).
  * Al arrancar recupera huérfanos ('aplicando' -> 'error') y loguea la fecha de
    modificación del propio archivo (lección F11 de listener_writeback).

Uso:
    python listener_pedidos.py            # bucle continuo
    python listener_pedidos.py --once     # una sola pasada (para pruebas)
"""
import sys
import datetime
import urllib.error

import listener_base as lb

import flujo_pedido_real

try:
    from safety_control import control_seguro
except Exception:  # pragma: no cover
    control_seguro = None

log = lb.setup_logging("pedidos", "pedidos.log")
if lb.AVISO_SIN_SERVICE_KEY:
    log.warning(lb.AVISO_SIN_SERVICE_KEY)

TABLE_CAB = "pedidos_app"
TABLE_ITEMS = "pedidos_app_items"
MAX_INTENTOS = 3

# Etapas de flujo_pedido_real.registrar_pedido() anteriores a Totalizar: el pedido
# se cancela completo antes de devolver estas etapas (todo-o-nada), así que un
# fallo acá es 100% reintentable sin riesgo de pedido doble. "totalizar" y
# "verificacion_db" quedan FUERA (ambiguas) y caen a la rama 'error' por descarte.
ETAPAS_REINTENTABLES = ("abrir_hybrid", "navegacion", "carga_item")


def get_pedidos_pendientes():
    """Pedidos 'pendiente' ya emitidos por un usuario autenticado (no borradores).
    `creado_por not.is.null` como segunda capa de defensa: una fila sin dueño
    autenticado no es una solicitud real de la app."""
    try:
        path = (f"{TABLE_CAB}?backend_status=eq.pendiente"
                f"&status=eq.emitido"
                f"&creado_por=not.is.null"
                f"&select=id,cliente_codigo,cliente_nombre,nota,backend_intentos"
                f"&order=id.asc&limit=10")
        return lb.rest("GET", path) or []
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else ""
        log.error("HTTP %s buscando pedidos pendientes: %s", e.code, body[:200])
        return []
    except Exception as e:
        log.error("Error buscando pedidos pendientes: %r", e)
        return []


def get_items(pedido_id):
    """Items de un pedido, mapeados a la forma que espera
    flujo_pedido_real.registrar_pedido: {"codigo","cantidad"} (la tabla usa
    codigo_producto). Sin costo/precio (el pedido usa el precio maestro)."""
    try:
        path = (f"{TABLE_ITEMS}?pedido_id=eq.{pedido_id}"
                f"&select=codigo_producto,descripcion,cantidad"
                f"&order=id.asc")
        filas = lb.rest("GET", path) or []
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else ""
        log.error("HTTP %s buscando items del pedido %s: %s", e.code, pedido_id, body[:200])
        return []
    except Exception as e:
        log.error("Error buscando items del pedido %s: %r", pedido_id, e)
        return []

    return [
        {
            "codigo": fila["codigo_producto"],
            "cantidad": float(fila["cantidad"]),
        }
        for fila in filas
    ]


def update_pedido(pid, **fields):
    try:
        lb.rest("PATCH", f"{TABLE_CAB}?id=eq.{pid}", body=fields,
                extra_headers={"Prefer": "return=minimal"})
        return True
    except Exception as e:
        log.error("No pude actualizar pedido %s: %r", pid, e)
        return False


def recuperar_huerfanos():
    """Al arrancar, marca 'error' cualquier pedido que quedó en 'aplicando' de una
    corrida anterior interrumpida. No se puede saber si Totalizar llegó a aplicarse
    antes del corte -> requiere verificación manual antes de reencolar."""
    nota = ("Corrida interrumpida (quedó en 'aplicando'). Verificar en HybridLite/caja "
            "si el pedido se registró antes de reencolar (riesgo de pedido doble).")
    try:
        recuperados = lb.rest(
            "PATCH", f"{TABLE_CAB}?backend_status=eq.aplicando",
            body={"backend_status": "error", "backend_resultado": nota},
            extra_headers={"Prefer": "return=representation"},
        )
        n = len(recuperados) if recuperados else 0
        if n:
            log.warning("Recuperados %s pedido(s) huérfano(s) en 'aplicando' -> 'error'.", n)
        else:
            log.debug("Sin huérfanos 'aplicando' al arrancar.")
    except Exception as e:
        log.warning("No pude chequear/recuperar huérfanos 'aplicando' (sigo igual): %r", e)


# ─── Política de reintentos / traducción resultado -> estado ──────────────────
def _politica_resultado(res, intentos):
    """Traduce un resultado {"ok","etapa","detalle",...} de
    flujo_pedido_real.registrar_pedido a (backend_status, backend_resultado):
    commit real -> 'completado'; ok sin commit -> preview, sigue 'pendiente';
    fallo en etapa reintentable -> 'pendiente'/'error' según MAX_INTENTOS; fallo
    en etapa ambigua -> 'error' inmediato."""
    if res["ok"] and lb.check_hybrid_write_enabled() and res.get("etapa") == "commit":
        return "completado", res["detalle"]
    if res["ok"]:
        return "pendiente", f"[PREVIEW] {res['detalle']}"
    etapa = res.get("etapa")
    if etapa in ETAPAS_REINTENTABLES:
        final = "error" if intentos >= MAX_INTENTOS else "pendiente"
        return final, res["detalle"]
    resultado = (f"{res['detalle']} | ATENCIÓN: el pedido pudo quedar registrado a "
                 f"medias en HybridLite; verificar en caja ANTES de reencolar "
                 f"(riesgo de pedido doble).")
    return "error", resultado


# ─── Procesamiento de un pedido ───────────────────────────────────────────────
def procesar_pedido(pedido):
    """Aplica UN pedido completo (cabecera + items) contra HybridLite. El estado
    backend_* vive en la cabecera (pedidos_app), no por item."""
    pid = pedido["id"]
    cliente_codigo = pedido.get("cliente_codigo")
    cliente_nombre = pedido.get("cliente_nombre")

    intentos = (pedido.get("backend_intentos") or 0) + 1
    if not update_pedido(pid, backend_status="aplicando", backend_intentos=intentos):
        log.error("No pude marcar 'aplicando' el pedido %s en Supabase; salteo esta pasada.", pid)
        return

    items = get_items(pid)
    if not items:
        update_pedido(pid, backend_status="completado",
                      backend_resultado="Pedido sin items.",
                      backend_aplicado_en=datetime.datetime.now(datetime.timezone.utc).isoformat())
        log.info("Pedido %s sin items -> 'completado' sin tocar HybridLite.", pid)
        return

    log.info("Procesando pedido %s: cliente=%s (%s) %s item(s)",
             pid, cliente_codigo, cliente_nombre, len(items))
    try:
        res = flujo_pedido_real.registrar_pedido(
            cliente_codigo, items,
            commit=lb.check_hybrid_write_enabled(), cliente_nombre=cliente_nombre,
        )
    except Exception as e:
        res = {"ok": False, "etapa": "excepcion", "detalle": f"excepción: {e!r}"}

    status_final, resultado_final = _politica_resultado(res, intentos)
    if status_final == "completado":
        update_pedido(pid, backend_status="completado", backend_resultado=resultado_final,
                      documento_hybrid=res.get("documento"),
                      backend_aplicado_en=datetime.datetime.now(datetime.timezone.utc).isoformat())
        log.info("OK pedido %s: %s", pid, resultado_final)
    elif status_final == "pendiente":
        update_pedido(pid, backend_status="pendiente", backend_resultado=resultado_final)
        log.info("PENDIENTE/PREVIEW pedido %s: %s", pid, resultado_final)
    else:
        update_pedido(pid, backend_status="error", backend_resultado=resultado_final)
        log.error("FALLO pedido %s (status=error): %s", pid, resultado_final)


# ─── Orquestación de una pasada completa ───────────────────────────────────────
_AVISO_SIN_SAFETY_CONTROL = False


def procesar_pendientes(pedidos):
    global _AVISO_SIN_SAFETY_CONTROL
    if not pedidos:
        return

    if control_seguro is None:
        if not _AVISO_SIN_SAFETY_CONTROL:
            log.warning("safety_control no disponible: procesando SIN overlay/F12/BlockInput "
                        "(degradado, ver import al inicio del módulo).")
            _AVISO_SIN_SAFETY_CONTROL = True
        for pedido in pedidos:
            procesar_pedido(pedido)
    else:
        with control_seguro("REGISTRANDO PEDIDOS EN HYBRIDLITE",
                            ocultar_scripts=["widget.pyw", "widget_recargo.pyw"]) as banner:
            total = len(pedidos)
            for n, pedido in enumerate(pedidos, start=1):
                try:
                    banner.set_texto(
                        f"REGISTRANDO PEDIDO {n}/{total} — "
                        f"PED-{pedido['id']} ({pedido.get('cliente_nombre') or pedido.get('cliente_codigo')})")
                except Exception:
                    pass
                procesar_pedido(pedido)


if __name__ == "__main__":
    lb.correr_loop(log, __file__, "listener_pedidos", get_pedidos_pendientes, procesar_pendientes,
                   recuperar_huerfanos, once=("--once" in sys.argv), sujeto="pedidos",
                   ceder_si=lb.hay_pendientes_prioritarios)
