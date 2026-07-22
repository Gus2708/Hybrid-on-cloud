"""
flujo_pedido_real.py — Registro de un PEDIDO de cliente (documento Tipo 10) en
HybridLiteOS con INPUT REAL de hardware.

Replica la coreografía grabada del dueño el 2026-07-21 (ver
grabar_flujo_20260721_144806.log, fuente de verdad). Es una versión SIMPLIFICADA
de flujo_compra_real.py: el pedido es un documento de VENTA "blando" —
NO mueve el kardex (el stock baja recién al FACTURARLO en caja), así que crear un
pedido es de bajo riesgo (uno errado se cancela/ignora, sin impacto contable).

Secuencia (registrar_pedido, un solo documento de Pedidos):
  1. Menú principal -> 'Pédidos de clientes' (TAdvGlassButton, sic con tilde) ->
     abre/reutiliza TFormHTransaccion_Pedidos 'Transacciones : : PEDIDOS'.
  2. CLIENTE: botón 'F1' (fila Cliente) -> Busqueda De Clientes
     (TForm_BusquedaConfDb) -> Ed_Buscar: código -> ENTER (posiciona) -> doble-clic
     fila (selecciona). Mismo patrón EXACTO que seleccionar_proveedor de compras.
  3. Por cada ítem (el foco arranca en la celda Código de la grilla TAdvStringGrid,
     con UN clic solo en el primero; los siguientes el cursor baja solo):
       código -> ENTER (carga el producto) -> cantidad -> ENTER -> ENTER (postea).
     NO hay costo, NO hay precio, NO abre 'Costos y Precios' (usa el precio maestro).
  4. commit=True, tras el último ítem: '&Totalizar' -> TFrmTotalOperacion ->
     'T&otalizar' (SIN número de documento — se autoasigna; SIN comprobante/Vista
     Previa porque esta PC no tiene impresora fiscal) -> 'Salir' de Pedidos.
     commit=False (preview): NO se totaliza — 'Cancelar' (confirmando) + 'Salir'.
     TODO-O-NADA: cualquier fallo pre-Totalizar cancela el documento completo.
  5. Verificación (solo commit) contra DBISAM: se lee el ÚLTIMO documento Tipo 10
     de TTransaccionvta y se comparan cliente + códigos/cantidades contra lo pedido.

# CALIBRAR EN VIVO (marcado con CALIBRAR en el código): la micro-secuencia del
# posteo de ítem (el 2º ENTER) y las posiciones de campo del header (cliente) se
# tomaron de UNA sola grabación; conviene una corrida de PREVIEW supervisada para
# afinarlas antes de habilitar commit en el listener.

SEGURIDAD: preview por defecto (llena y verifica en pantalla, NO totaliza);
--commit aplica de verdad y verifica contra la base.

USO:
    python flujo_pedido_real.py 001 --items "01404:2"
    python flujo_pedido_real.py 001 --items "01404:2,03618:1" --commit
"""
import os
import sys
import time
import logging

import win32gui
import win32con
import pydbisam

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import flujo_precio as fp            # helpers de ventanas + constantes de clase
import flujo_precio_real as fpr       # _focus, _esperar_refresco, _click_boton_dialogo
import flujo_stock_real as fsr        # _cerrar_ficha_si_abierta (modelo de apertura)
import realinput as ri

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pedido_real")

DIR = os.path.dirname(os.path.abspath(__file__))

PEDIDOS_CLASS = "TFormHTransaccion_Pedidos"   # title='Transacciones : : PEDIDOS'
TOTAL_CLASS = "TFrmTotalOperacion"            # title='Total Operación'
PREVIEW_CLASS = "TfrxPreviewForm"             # comprobante (no debería aparecer en esta PC)
CONF_CLASS = "TFConfirmacion"                 # diálogo de confirmación SI/NO genérico

RUTA_VTA = r"H:\HybridLite\HybridEmpresa\HybridDataBase\TTransaccionvta.dat"
RUTA_DET = r"H:\HybridLite\HybridEmpresa\HybridDataBase\TDetalleVta.dat"

TIPO_PEDIDO = 10                              # THT_TIPO / TBT_TIPOOPERACION del pedido
TOL_CANT = 0.001                              # tolerancia de cantidad en la verificación

# Coordenadas relativas (fallbacks por posición) tomadas de la grabación
# 2026-07-21; se usan SOLO si la localización por título/clase no encuentra el
# control. Relativas a la ventana correspondiente.
MENU_PEDIDOS_GRUPO_REL = (150, 120)   # clic en el grupo del menú (Panel7) que despliega Pedidos
CLIENTE_F1_REL = (298, 147)           # botón 'F1' de la fila Cliente
ITEM_GRID_REL = (84, 331)             # celda Código de la grilla (TAdvStringGrid), 1er ítem
TOTALIZAR_REL = (631, 707)            # botón '&Totalizar'
TOTAL_OPERAR_REL = (558, 660)         # botón 'T&otalizar' de TFrmTotalOperacion
SALIR_REL = (742, 701)                # botón '&Salir'


class PedidoError(Exception):
    pass


# ── utilidades compartidas (mismo patrón que flujo_compra_real) ──────────────
def _focus(hwnd):
    if not hwnd:
        return
    try:
        fp._win(hwnd).set_focus()
    except Exception:
        pass
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.25)


def _confirmar_lo_que_pregunte(timeout=5):
    """Responde afirmativamente a CUALQUIER diálogo de confirmación/alerta
    (TFConfirmacion / TMessageForm). Cubre el 'Cancelar' de Pedidos (responder SÍ)
    y cualquier alerta que aparezca al Totalizar. Mismo criterio que compras."""
    t0 = time.time()
    respondido = False
    while time.time() - t0 < timeout:
        h = fp._find_hwnd(CONF_CLASS) or fp._find_hwnd("TMessageForm")
        if not h:
            if respondido:
                return True
            time.sleep(0.3)
            continue
        _focus(h)
        m = fp._win(h)
        for titulo in ("&Ok", "Ok", "&OK", "OK", "&Aceptar", "Aceptar",
                       "&Continuar", "Continuar",
                       "&SI", "SI", "Sí", "&Sí", "&Yes", "Yes"):
            try:
                b = m.child_window(title=titulo)
                r = b.rectangle()
                ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                log.info("Confirmación '%s' pulsada.", titulo)
                respondido = True
                time.sleep(0.6)
                break
            except Exception:
                continue
        time.sleep(0.3)
    return respondido


def _leer_cliente_header(hped):
    """Lee el campo Cliente del header de Pedidos para VERIFICAR la selección.
    # CALIBRAR: la franja de posición del campo Cliente se estima a partir del
    # botón F1 grabado (rel_top≈147); se toma el THybridEdit de la columna
    # izquierda con top cercano. Devuelve el texto ('' si no se encontró)."""
    if not hped:
        return ""
    ped = fp._win(hped)
    L, T, _, _ = win32gui.GetWindowRect(hped)
    mejor = ""
    for c in ped.descendants(class_name="THybridEdit"):
        r = c.rectangle()
        rel_top = r.top - T
        rel_left = r.left - L
        txt = (c.window_text() or "").strip()
        if rel_left >= 40 or not txt:
            continue
        # banda del header alrededor de la fila Cliente (F1 en rel_top≈147)
        if 120 <= rel_top < 175:
            mejor = txt
    return mejor


# ── apertura de la ventana de Pedidos ────────────────────────────────────────
def abrir_pedidos():
    """Garantiza que TFormHTransaccion_Pedidos esté abierta. Reutiliza si ya
    está; si no, cierra la Ficha residual y navega Menú -> 'Pédidos de clientes'.
    Devuelve su hwnd."""
    ha = fp._find_hwnd(PEDIDOS_CLASS)
    if ha:
        log.info("Ventana de Pedidos ya abierta, reutilizando.")
        return ha

    fsr._cerrar_ficha_si_abierta()

    hmain = fp._find_hwnd(fp.MAIN_CLASS)
    if not hmain:
        raise PedidoError("HybridLiteOS no está abierto (no veo el módulo principal).")
    main = fp._win(hmain)
    _focus(hmain)
    time.sleep(0.2)

    try:
        btn = main.child_window(title="Pédidos de clientes", class_name="TAdvGlassButton")
        btn.wait("exists visible", timeout=1.5)
    except Exception:
        # el grupo del menú aún no está desplegado -> abrirlo por el panel (fallback)
        L, T, _, _ = win32gui.GetWindowRect(hmain)
        ri.click(L + MENU_PEDIDOS_GRUPO_REL[0], T + MENU_PEDIDOS_GRUPO_REL[1])
        time.sleep(0.8)
        btn = main.child_window(title="Pédidos de clientes", class_name="TAdvGlassButton")
        btn.wait("exists visible", timeout=8)

    r = btn.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)

    t0 = time.time()
    while time.time() - t0 < 15:
        ha = fp._find_hwnd(PEDIDOS_CLASS)
        if ha:
            time.sleep(0.5)
            return ha
        time.sleep(0.3)
    raise PedidoError("No abrió la ventana de Pedidos (TFormHTransaccion_Pedidos).")


# ── cliente ──────────────────────────────────────────────────────────────────
def seleccionar_cliente(ped, cliente_codigo, cliente_nombre=None):
    """Botón F1 de la fila Cliente -> Busqueda De Clientes -> Ed_Buscar: código ->
    ENTER (posiciona) -> ENTER/doble-clic (selecciona). Patrón EXACTO de
    seleccionar_proveedor. Verifica en pantalla que el cliente no quedó vacío
    (y, si se pasa cliente_nombre, que coincide)."""
    hped = fp._find_hwnd(PEDIDOS_CLASS)
    _focus(hped)

    try:
        boton = ped.child_window(title="F1", class_name="TFlatButton")
        r = boton.rectangle()
        ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    except Exception:
        L, T, _, _ = win32gui.GetWindowRect(hped)
        ri.click(L + CLIENTE_F1_REL[0], T + CLIENTE_F1_REL[1])

    hbusq = fp._wait_for(fp.BUSQ_CLASS, desc="Busqueda De Clientes")
    busq = fp._win(hbusq)
    time.sleep(0.25)
    _focus(hbusq)

    ed = busq.child_window(class_name="THybridEdit", found_index=0)
    r = ed.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    time.sleep(0.15)
    ri.clear_field()
    ri.type_text(str(cliente_codigo))
    time.sleep(0.2)
    ri.press("ENTER")                                    # ejecuta la búsqueda

    posicionado = fpr._esperar_refresco(busq, str(cliente_codigo), timeout=6.0)
    log.info("Busqueda De Clientes posicionada en %s: %s", cliente_codigo, posicionado)

    if fp._find_hwnd(fp.BUSQ_CLASS):
        _focus(hbusq)
        ri.press("ENTER")                                # selecciona la fila posicionada
        time.sleep(0.5)

    if fp._find_hwnd(fp.BUSQ_CLASS):
        # fallback: doble-clic en la fila posicionada (patrón grabado)
        try:
            grid = busq.child_window(class_name="TDBGrid")
            gr = grid.rectangle()
            ri.click(gr.left + 100, gr.top + 26, double=True)
            time.sleep(0.5)
        except Exception:
            pass

    if fp._find_hwnd("TMessageForm"):
        raise PedidoError(f"Apareció un diálogo de error buscando el cliente {cliente_codigo}.")
    if fp._find_hwnd(fp.BUSQ_CLASS):
        raise PedidoError(f"La Busqueda De Clientes no se cerró tras seleccionar {cliente_codigo}.")

    cli_ui = _leer_cliente_header(fp._find_hwnd(PEDIDOS_CLASS))
    if not cli_ui:
        # no bloqueante duro: el header puede leerse distinto; avisamos fuerte
        log.warning("No pude leer el cliente en el header tras seleccionar %s "
                    "(# CALIBRAR _leer_cliente_header). Continuo con cautela.", cliente_codigo)
    elif cliente_nombre and cliente_nombre.strip().upper() not in cli_ui.upper():
        raise PedidoError(f"El cliente quedó como {cli_ui!r}, no coincide con el esperado "
                          f"{cliente_nombre!r} (código {cliente_codigo}). Abortando el pedido.")
    else:
        log.info("Cliente %s seleccionado, header: %r", cliente_codigo, cli_ui)


# ── ítems de la grilla ──────────────────────────────────────────────────────
def cargar_item(codigo, cantidad, es_primero=False):
    """Teclea un ítem en la grilla de Pedidos:
        (solo el 1er ítem) clic en la celda Código de la grilla TAdvStringGrid
        código -> ENTER (carga) -> cantidad -> ENTER -> ENTER (postea la fila)
    NO hay costo ni precio (usa el precio maestro del producto). Lanza PedidoError
    ante cualquier diálogo de error; el llamador cancela TODO el documento.

    # CALIBRAR: el 2º ENTER (posteo) se tomó de la grabación; si en vivo la fila
    # no postea o pide algo más, ajustar aquí. Los ítems siguientes NO re-clickean
    # la grilla (el cursor baja solo tras postear, igual que en compras)."""
    hped = fp._find_hwnd(PEDIDOS_CLASS)

    if es_primero:
        _focus(hped)
        # clic en la celda Código de la grilla (localizar TAdvStringGrid; fallback coord)
        try:
            ped = fp._win(hped)
            grid = ped.child_window(class_name="TAdvStringGrid", found_index=0)
            gr = grid.rectangle()
            ri.click(gr.left + 68, gr.top + 34)
        except Exception:
            L, T, _, _ = win32gui.GetWindowRect(hped)
            ri.click(L + ITEM_GRID_REL[0], T + ITEM_GRID_REL[1])
        time.sleep(0.2)

    # drenar cualquier alerta previa colgada antes de teclear este código
    if fp._find_hwnd(CONF_CLASS) or fp._find_hwnd("TMessageForm"):
        _confirmar_lo_que_pregunte(timeout=2)
        _focus(hped)

    ri.type_code(str(codigo))
    time.sleep(0.15)
    ri.press("ENTER")                    # carga el producto; el cursor salta a Cantidad
    time.sleep(0.5)

    # un diálogo de error acá = código inexistente / producto no válido
    if fp._find_hwnd("TMessageForm"):
        raise PedidoError(f"Error al cargar el ítem {codigo} (¿código inexistente?).")

    ri.type_number(f"{float(cantidad):g}")
    time.sleep(0.1)
    ri.press("ENTER")                    # confirma la cantidad
    time.sleep(0.2)
    ri.press("ENTER")                    # postea la fila / baja a la siguiente  # CALIBRAR
    time.sleep(0.3)

    # drenar una alerta tardía (p.ej. 'llegó al mínimo') para que no se cuele al siguiente
    _confirmar_lo_que_pregunte(timeout=1.0)

    log.info("Ítem %s cargado (cant=%s).", codigo, cantidad)


# ── cierre del documento ─────────────────────────────────────────────────────
def _cancelar_pedido(hped):
    """Descarta el documento completo (preview o fallo pre-commit): botón
    'Cancelar' + responder SÍ. Si no hay botón Cancelar, cae a Salir (que debería
    descartar un documento sin totalizar)."""
    hped = hped or fp._find_hwnd(PEDIDOS_CLASS)
    if not hped:
        return
    _focus(hped)
    ped = fp._win(hped)
    cancelado = False
    for titulo in ("C&ancelar", "Cancelar", "&Cancelar"):
        try:
            b = ped.child_window(title=titulo, class_name="TFlatButton")
            r = b.rectangle()
            ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
            cancelado = True
            time.sleep(0.8)
            break
        except Exception:
            continue
    if cancelado:
        _confirmar_lo_que_pregunte(timeout=5)
    else:
        log.warning("No encontré botón 'Cancelar' en Pedidos; salgo con Salir "
                    "(el documento sin totalizar no debería persistir). # CALIBRAR")


def _salir_pedidos():
    """Cierra la ventana de Pedidos: botón '&Salir', responde confirmaciones, y si
    sigue abierta fuerza WM_CLOSE. Se llama SIEMPRE al final."""
    hped = fp._find_hwnd(PEDIDOS_CLASS)
    if not hped:
        return
    _focus(hped)
    ped = fp._win(hped)
    for titulo in ("&Salir", "Salir"):
        try:
            b = ped.child_window(title=titulo, class_name="TFlatButton")
            r = b.rectangle()
            ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
            time.sleep(0.8)
            break
        except Exception:
            continue
    else:
        L, T, _, _ = win32gui.GetWindowRect(hped)
        ri.click(L + SALIR_REL[0], T + SALIR_REL[1])
        time.sleep(0.8)
    _confirmar_lo_que_pregunte(timeout=3)
    for _ in range(3):
        h = fp._find_hwnd(PEDIDOS_CLASS)
        if not h:
            return
        try:
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass
        time.sleep(0.4)


def _totalizar_pedido(hped):
    """'&Totalizar' -> TFrmTotalOperacion -> 'T&otalizar' (SIN número de documento,
    SIN comprobante). Reintenta el clic a Totalizar (la ventana puede no estar al
    frente cuando cae el clic real). Devuelve True si el flujo llegó al final."""
    htot = None
    for intento in range(1, 4):
        _focus(hped)
        time.sleep(0.4)
        ped = fp._win(hped)
        try:
            b = ped.child_window(title="&Totalizar", class_name="TFlatButton")
            r = b.rectangle()
            ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
        except Exception:
            L, T, _, _ = win32gui.GetWindowRect(hped)
            ri.click(L + TOTALIZAR_REL[0], T + TOTALIZAR_REL[1])
        _confirmar_lo_que_pregunte(timeout=2)
        t0 = time.time()
        while time.time() - t0 < 5:
            htot = fp._find_hwnd(TOTAL_CLASS)
            if htot:
                break
            time.sleep(0.3)
        if htot:
            break
        log.warning("Intento %s: Total Operación no apareció tras Totalizar, reintento.", intento)
    if not htot:
        raise PedidoError("No apareció Total Operación (TFrmTotalOperacion) tras 3 intentos.")

    _focus(htot)
    tot = fp._win(htot)
    # SIN número de documento (autoasignado): clic directo en 'T&otalizar'
    try:
        b = tot.child_window(title="T&otalizar", class_name="TFlatButton")
        r = b.rectangle()
        ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    except Exception:
        L, T, _, _ = win32gui.GetWindowRect(htot)
        ri.click(L + TOTAL_OPERAR_REL[0], T + TOTAL_OPERAR_REL[1])
    time.sleep(0.5)

    # esta PC no tiene impresora fiscal -> no debería abrir Vista Previa; por si
    # acaso, se cierra igual que en compras.
    for _ in range(3):
        h = fp._find_hwnd(PREVIEW_CLASS)
        if not h:
            break
        try:
            win32gui.SetForegroundWindow(h)
            time.sleep(0.2)
            ri.press("ESC")
            time.sleep(0.3)
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass
        time.sleep(0.4)

    _confirmar_lo_que_pregunte(timeout=2)
    if fp._find_hwnd(TOTAL_CLASS):
        raise PedidoError("La ventana Total Operación no se cerró tras totalizar.")
    return True


# ── verificación contra DBISAM ───────────────────────────────────────────────
def _ultimo_pedido_db():
    """Lee el ÚLTIMO documento Tipo 10 de TTransaccionvta (mayor THT_AUTOINCREMENT)
    y sus líneas de TDetalleVta. Devuelve (header_dict, [detalle_dict, ...]) o
    (None, []) si no hay pedidos."""
    dbv = pydbisam.PyDBISAM(RUTA_VTA)
    cols_v = dbv.fields()
    iv = {n: i for i, n in enumerate(cols_v)}
    total_v = dbv.total_rows

    # Optimización: buscar primero en la cola (últimas 200 filas) marcha atrás
    mejor = None
    start_v = max(0, total_v - 200)
    for i in range(total_v - 1, start_v - 1, -1):
        row = dbv.row(i)
        if row and row[iv["THT_TIPO"]] == TIPO_PEDIDO:
            mejor = row
            break

    # Fallback a recorrido completo si la cola no arrojó ningún pedido
    if mejor is None:
        for row in dbv.rows():
            if row[iv["THT_TIPO"]] != TIPO_PEDIDO:
                continue
            if mejor is None or row[iv["THT_AUTOINCREMENT"]] > mejor[iv["THT_AUTOINCREMENT"]]:
                mejor = row

    if mejor is None:
        return None, []
    header = dict(zip(cols_v, mejor))
    auto = header["THT_AUTOINCREMENT"]

    dbd = pydbisam.PyDBISAM(RUTA_DET)
    cols_d = dbd.fields()
    idd = {n: i for i, n in enumerate(cols_d)}
    total_d = dbd.total_rows
    detalle = []

    # Optimización: buscar detalles en la cola (últimas 500 filas)
    start_d = max(0, total_d - 500)
    for i in range(start_d, total_d):
        row = dbd.row(i)
        if row and row[idd["TBT_TIPOOPERACION"]] == TIPO_PEDIDO and \
                row[idd["TBT_OPERACION_AUTOINCREMENT"]] == auto:
            detalle.append(dict(zip(cols_d, row)))

    # Fallback a recorrido completo de detalles
    if not detalle:
        for row in dbd.rows():
            if row[idd["TBT_TIPOOPERACION"]] == TIPO_PEDIDO and \
                    row[idd["TBT_OPERACION_AUTOINCREMENT"]] == auto:
                detalle.append(dict(zip(cols_d, row)))

    return header, detalle


def _verificar_pedido_db(cliente_codigo, items, cliente_nombre=None):
    """Confirma que el último pedido Tipo 10 en DBISAM corresponde a lo pedido:
    cliente (rif/nombre) + un ítem por código con la cantidad correcta.
    Devuelve (ok: bool, detalle: str, documento: str|None)."""
    header, detalle = _ultimo_pedido_db()
    if header is None:
        return False, "no hay ningún documento Tipo 10 en la base tras totalizar.", None

    doc = header.get("THT_DOCUMENTO")
    rif = str(header.get("THT_RIFCLIENTE") or "").strip()
    persona = str(header.get("THT_PERSONACONTACTO") or "").strip()

    fallos = []
    # cliente: el código pedido suele coincidir con el rif/código; si se pasó
    # nombre, se verifica contra PersonaContacto.
    cod = str(cliente_codigo).strip()
    if cod and cod not in (rif, str(header.get("THT_RESPONSABLE") or "").strip()):
        log.warning("El cliente del pedido en DB (rif=%r) no coincide literal con el "
                    "código %r; puede ser normal si el código != rif.", rif, cod)
    if cliente_nombre and cliente_nombre.strip().upper() not in persona.upper():
        fallos.append(f"cliente en DB={persona!r}, esperaba {cliente_nombre!r}")

    # ítems: mapa codigo -> cantidad en el detalle
    en_db = {}
    for d in detalle:
        c = str(d.get("TBT_CODIGO") or "").strip()
        en_db[c] = en_db.get(c, 0.0) + float(d.get("TBT_CANTIDAD") or 0)
    for it in items:
        c = str(it["codigo"]).strip()
        if c not in en_db:
            fallos.append(f"el ítem {c} no aparece en el detalle del pedido")
        elif abs(en_db[c] - float(it["cantidad"])) > TOL_CANT:
            fallos.append(f"ítem {c}: cantidad en DB={en_db[c]}, esperaba {it['cantidad']}")

    if fallos:
        return False, f"pedido doc={doc}: " + "; ".join(fallos), doc
    return True, (f"pedido doc={doc} VERIFICADO en DB (cliente={persona!r}, "
                  f"{len(items)} ítem(s), status={header.get('THT_STATUS')})."), doc


# ── orquestador ──────────────────────────────────────────────────────────────
def registrar_pedido(cliente_codigo, items, commit=False, cliente_nombre=None):
    """items: list[dict] {"codigo": str, "cantidad": float}.
    Return: {"ok": bool, "etapa": str, "detalle": str}.
    etapas éxito: "commit" | "preview"
    etapas fallo PRE-commit (reintentables, documento cancelado completo):
      "abrir_hybrid" | "navegacion" (abrir/cliente) | "carga_item"
    etapas fallo AMBIGUAS (NO reintentar solo): "totalizar" | "verificacion_db"
    REGLA DE ORO: cualquier fallo antes de Totalizar -> Cancelar + Salir + etapa
    pre-commit. El pedido es TODO-O-NADA (un documento)."""
    if not items:
        return {"ok": False, "etapa": "navegacion", "detalle": "La lista de items está vacía."}

    codigos_norm = [str(it["codigo"]).strip().lower() for it in items]
    vistos, dups = set(), set()
    for c in codigos_norm:
        (dups if c in vistos else vistos).add(c)
    if dups:
        return {"ok": False, "etapa": "navegacion",
                "detalle": f"Códigos duplicados en el pedido: {sorted(dups)}. Nada se tocó."}

    import abrir_hybrid
    ok, msg = abrir_hybrid.asegurar_hybrid()
    if not ok:
        return {"ok": False, "etapa": "abrir_hybrid", "detalle": msg}

    # navegación PRE-escritura: abrir Pedidos + seleccionar cliente
    try:
        hped = abrir_pedidos()
        ped = fp._win(hped)
        seleccionar_cliente(ped, cliente_codigo, cliente_nombre)
    except (PedidoError, fp.FlujoError) as e:
        _cancelar_pedido(fp._find_hwnd(PEDIDOS_CLASS))
        _salir_pedidos()
        return {"ok": False, "etapa": "navegacion",
                "detalle": f"No pude llegar a la carga de ítems (nada se tocó): {e}"}

    # ítems: cualquier fallo cancela el DOCUMENTO COMPLETO (todo-o-nada)
    primero = True
    for it in items:
        try:
            cargar_item(it["codigo"], it["cantidad"], es_primero=primero)
            primero = False
        except PedidoError as e:
            _cancelar_pedido(fp._find_hwnd(PEDIDOS_CLASS))
            _salir_pedidos()
            return {"ok": False, "etapa": "carga_item",
                    "detalle": f"Pedido CANCELADO completo (todo-o-nada), fallo en "
                               f"{it['codigo']}: {e}"}

    if not commit:
        _cancelar_pedido(fp._find_hwnd(PEDIDOS_CLASS))
        _salir_pedidos()
        return {"ok": True, "etapa": "preview",
                "detalle": f"Preview de {len(items)} ítem(s) armado en pantalla y "
                           f"DESCARTADO (sin --commit; documento cancelado)."}

    # COMMIT: Totalizar (etapa AMBIGUA si falla)
    hped = fp._find_hwnd(PEDIDOS_CLASS)
    try:
        _totalizar_pedido(hped)
    except (PedidoError, fp.FlujoError) as e:
        return {"ok": False, "etapa": "totalizar",
                "detalle": f"No pude confirmar la totalización del pedido: {e}"}

    _salir_pedidos()
    time.sleep(0.8)

    try:
        ok_db, detalle_db, documento = _verificar_pedido_db(cliente_codigo, items, cliente_nombre)
    except Exception as e:
        return {"ok": False, "etapa": "verificacion_db",
                "detalle": f"Pedido totalizado pero no pude verificar en DB: {e}"}

    if ok_db:
        return {"ok": True, "etapa": "commit", "detalle": detalle_db, "documento": documento}
    return {"ok": False, "etapa": "verificacion_db",
            "detalle": f"¡ALERTA! {detalle_db}", "documento": documento}


# ── CLI ──────────────────────────────────────────────────────────────────────
def _parse_items(spec):
    """'COD:cant,COD2:cant2' -> list[dict]."""
    items = []
    for par in spec.split(","):
        partes = par.split(":")
        if len(partes) != 2:
            raise ValueError(f"Ítem inválido: {par!r} (formato codigo:cantidad)")
        codigo, cantidad = partes
        codigo = codigo.strip()
        if not codigo:
            raise ValueError(f"Ítem inválido: {par!r} (código vacío)")
        items.append({"codigo": codigo, "cantidad": float(cantidad)})
    return items


if __name__ == "__main__":
    _raw = sys.argv[1:]
    args = []
    i = 0
    while i < len(_raw):
        tok = _raw[i]
        if tok == "--items":
            i += 2
            continue
        if not tok.startswith("--"):
            args.append(tok)
        i += 1

    if len(args) < 1 or "--items" not in _raw:
        print('Uso: python flujo_pedido_real.py <cliente_codigo> '
              '--items "COD:cant,COD2:cant2" [--commit]')
        sys.exit(1)

    cliente_codigo = args[0]
    items_spec = _raw[_raw.index("--items") + 1]
    try:
        items = _parse_items(items_spec)
    except ValueError as e:
        print(f"Error parseando --items: {e}")
        sys.exit(1)

    try:
        res = registrar_pedido(cliente_codigo, items, commit="--commit" in _raw)
        print("\n=== RESULTADO ===")
        for k, v in res.items():
            print(f"  {k}: {v}")
    finally:
        # Cierra la instancia AISLADA que ESTE proceso abrió, para no dejar
        # ventanas de Hybrid acumuladas en corridas standalone. El listener
        # (proceso largo que REUTILIZA una sola instancia entre pasadas) importa
        # registrar_pedido directamente y NO pasa por este __main__, así que su
        # reuso no se rompe.
        try:
            import abrir_hybrid
            abrir_hybrid.cerrar_aislada()
        except Exception as e:
            print(f"(aviso: no pude cerrar la instancia aislada de Hybrid: {e})")
