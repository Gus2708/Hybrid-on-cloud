"""
listener_directorio.py — Canal App (El Serrucho Go, Directorio) → Local (write-back de
alta de CLIENTES y PROVEEDORES a HybridLite).

Sondea `registro_clientes_app` y `registro_proveedores_app` — tablas que la app llena al
registrar un cliente/proveedor nuevo — y por cada fila con status='emitido' que todavía no
fue aplicada, da de alta la ficha en HybridLite vía flujo_directorio_real.registrar
(input real de hardware). Marca el resultado en las columnas `backend_*` de la fila y
guarda en `codigo_cliente_hybrid` / `codigo_proveedor_hybrid` el código que quedó en la
DBISAM (derivado del RIF; ver flujo_directorio_real).

HERMANO de listener_pedidos.py / listener_compras.py / listener_writeback.py (mismo
esqueleto de listener_base: guard de H:, ventana horaria, HYBRID_WRITE_ENABLED,
control_seguro, mutex del mouse que serializa los listeners, política de reintentos).

Un registro = UNA ficha = UN Guardar. El estado backend_* vive en la fila (no hay items).

RLS: registro_clientes_app deja escribir a empleados activos; registro_proveedores_app solo
a privilegiados. El backend usa SUPABASE_SERVICE_KEY (config.py) para ver las filas de todos
los usuarios; con la anon key vería 0 filas (RLS filtrando en silencio).

SEGURIDAD (calcada de listener_pedidos):
  * Con HYBRID_WRITE_ENABLED != "1" cada fila se procesa en PREVIEW (commit=False): arma y
    verifica en pantalla, pero cancela sin guardar.
  * Todo corre dentro de `with control_seguro():` (banner + F12 + BlockInput).
  * Guard de H:, ventana horaria opcional (fail-closed si mal seteada).
  * Reintentos: fallo PRE-Guardar ("abrir_hybrid","navegacion","campos") es reintentable
    hasta MAX_INTENTOS (el alta se cancela antes de devolver esas etapas). Fallo AMBIGUO
    ("guardar","verificacion_db",excepción) → 'error' inmediato sin reintentar.
  * Al arrancar recupera huérfanos ('aplicando' → 'error').

Uso:
    python listener_directorio.py            # bucle continuo
    python listener_directorio.py --once     # una sola pasada (para pruebas)
"""
import sys
import datetime
import urllib.error

import listener_base as lb

import flujo_directorio_real

try:
    from safety_control import control_seguro
except Exception:  # pragma: no cover
    control_seguro = None

log = lb.setup_logging("directorio", "directorio.log")
if lb.AVISO_SIN_SERVICE_KEY:
    log.warning(lb.AVISO_SIN_SERVICE_KEY)

MAX_INTENTOS = 3

# Config por tipo: tabla de la cola y columna donde escribir el código de Hybrid.
TABLAS = {
    "cliente":   {"tabla": "registro_clientes_app",    "codigo_col": "codigo_cliente_hybrid"},
    "proveedor": {"tabla": "registro_proveedores_app", "codigo_col": "codigo_proveedor_hybrid"},
}

# Etapas anteriores a Guardar: el alta se cancela completa antes de devolverlas
# (todo-o-nada), así que un fallo acá es 100% reintentable. "guardar" y
# "verificacion_db" quedan FUERA (ambiguas) y caen a 'error' por descarte.
ETAPAS_REINTENTABLES = ("abrir_hybrid", "navegacion", "campos")


def _get_tabla(tipo):
    tabla = TABLAS[tipo]["tabla"]
    try:
        path = (f"{tabla}?backend_status=eq.pendiente"
                f"&status=eq.emitido"
                f"&creado_por=not.is.null"
                f"&select=id,nombre,rif,backend_intentos"
                f"&order=id.asc&limit=10")
        filas = lb.rest("GET", path) or []
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore") if e.fp else ""
        log.error("HTTP %s buscando %s pendientes: %s", e.code, tipo, body[:200])
        return []
    except Exception as e:
        log.error("Error buscando %s pendientes: %r", tipo, e)
        return []
    for f in filas:
        f["_tipo"] = tipo
    return filas


def get_pendientes():
    """Clientes primero, luego proveedores (orden estable)."""
    return _get_tabla("cliente") + _get_tabla("proveedor")


def update_fila(tipo, rid, **fields):
    tabla = TABLAS[tipo]["tabla"]
    try:
        lb.rest("PATCH", f"{tabla}?id=eq.{rid}", body=fields,
                extra_headers={"Prefer": "return=minimal"})
        return True
    except Exception as e:
        log.error("No pude actualizar %s %s: %r", tipo, rid, e)
        return False


def recuperar_huerfanos():
    """Marca 'error' cualquier fila que quedó en 'aplicando' de una corrida anterior
    interrumpida (no se puede saber si el Guardar llegó a aplicarse → verificar a mano)."""
    nota = ("Corrida interrumpida (quedó en 'aplicando'). Verificar en HybridLite si la "
            "ficha se creó antes de reencolar (riesgo de alta doble).")
    for tipo in TABLAS:
        tabla = TABLAS[tipo]["tabla"]
        try:
            recuperados = lb.rest(
                "PATCH", f"{tabla}?backend_status=eq.aplicando",
                body={"backend_status": "error", "backend_resultado": nota},
                extra_headers={"Prefer": "return=representation"},
            )
            n = len(recuperados) if recuperados else 0
            if n:
                log.warning("Recuperados %s %s huérfano(s) 'aplicando' → 'error'.", n, tipo)
        except Exception as e:
            log.warning("No pude recuperar huérfanos de %s (sigo igual): %r", tipo, e)


def _politica_resultado(res, intentos):
    """Traduce el resultado de flujo_directorio_real.registrar a (backend_status,
    backend_resultado). commit/ya_existe con write habilitado → 'completado'; ok sin
    commit → preview, sigue 'pendiente'; fallo reintentable → 'pendiente'/'error' según
    MAX_INTENTOS; fallo ambiguo → 'error' inmediato."""
    if res["ok"] and lb.check_hybrid_write_enabled() and res.get("etapa") in ("commit", "ya_existe"):
        return "completado", res["detalle"]
    if res["ok"]:
        return "pendiente", f"[PREVIEW] {res['detalle']}"
    etapa = res.get("etapa")
    if etapa in ETAPAS_REINTENTABLES:
        return ("error" if intentos >= MAX_INTENTOS else "pendiente"), res["detalle"]
    return "error", (f"{res['detalle']} | ATENCIÓN: la ficha pudo quedar a medias en "
                     f"HybridLite; verificar ANTES de reencolar (riesgo de alta doble).")


def procesar_registro(item):
    """Aplica UN registro (cliente o proveedor) contra HybridLite."""
    tipo = item["_tipo"]
    cfg = TABLAS[tipo]
    rid = item["id"]
    nombre = item.get("nombre")
    rif = item.get("rif")

    intentos = (item.get("backend_intentos") or 0) + 1
    if not update_fila(tipo, rid, backend_status="aplicando", backend_intentos=intentos):
        log.error("No pude marcar 'aplicando' el %s %s; salteo esta pasada.", tipo, rid)
        return

    log.info("Procesando %s %s: nombre=%r rif=%r", tipo, rid, nombre, rif)
    try:
        res = flujo_directorio_real.registrar(
            tipo, nombre, rif, commit=lb.check_hybrid_write_enabled())
    except Exception as e:
        res = {"ok": False, "etapa": "excepcion", "detalle": f"excepción: {e!r}", "codigo": None}

    status_final, resultado_final = _politica_resultado(res, intentos)
    if status_final == "completado":
        fields = {
            "backend_status": "completado",
            "backend_resultado": resultado_final,
            "backend_aplicado_en": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        if res.get("codigo"):
            fields[cfg["codigo_col"]] = res["codigo"]
        update_fila(tipo, rid, **fields)
        log.info("OK %s %s: %s", tipo, rid, resultado_final)
    elif status_final == "pendiente":
        update_fila(tipo, rid, backend_status="pendiente", backend_resultado=resultado_final)
        log.info("PENDIENTE/PREVIEW %s %s: %s", tipo, rid, resultado_final)
    else:
        update_fila(tipo, rid, backend_status="error", backend_resultado=resultado_final)
        log.error("FALLO %s %s (status=error): %s", tipo, rid, resultado_final)


_AVISO_SIN_SAFETY_CONTROL = False


def procesar_pendientes(registros):
    global _AVISO_SIN_SAFETY_CONTROL
    if not registros:
        return

    if control_seguro is None:
        if not _AVISO_SIN_SAFETY_CONTROL:
            log.warning("safety_control no disponible: procesando SIN overlay/F12/BlockInput (degradado).")
            _AVISO_SIN_SAFETY_CONTROL = True
        for reg in registros:
            procesar_registro(reg)
    else:
        with control_seguro("REGISTRANDO CLIENTES/PROVEEDORES EN HYBRIDLITE",
                            ocultar_scripts=["widget.pyw", "widget_recargo.pyw"]) as banner:
            total = len(registros)
            for n, reg in enumerate(registros, start=1):
                try:
                    banner.set_texto(
                        f"REGISTRANDO {reg['_tipo'].upper()} {n}/{total} — "
                        f"{reg.get('nombre') or reg['id']}")
                except Exception:
                    pass
                procesar_registro(reg)


if __name__ == "__main__":
    lb.correr_loop(log, __file__, "listener_directorio", get_pendientes, procesar_pendientes,
                   recuperar_huerfanos, once=("--once" in sys.argv), sujeto="registros")
