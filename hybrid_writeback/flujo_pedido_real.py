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

PRECIO MANUAL (2026-07-28): cada ítem puede traer un precio propio en USD CON
IVA; se teclea TAL CUAL en la celda Precio de la grilla, con el sufijo '$' (misma
convención que el costo en compras). Sin precio, el ítem usa el precio maestro
—comportamiento histórico—. La secuencia está CONFIRMADA contra la grabación
grabar_flujo_20260728_165901.log y las unidades contra el doc 00004749.

USO:
    python flujo_pedido_real.py 001 --items "01404:2"
    python flujo_pedido_real.py 001 --items "01404:2,03618:1" --commit
    python flujo_pedido_real.py 001 --items "01404:2:15.90"     # precio manual
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
import colisiones                     # clave de búsqueda segura (código vs referencia)
import alias_manager as am            # traducción de códigos de proveedor / alias
import realinput as ri

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pedido_real")

DIR = os.path.dirname(os.path.abspath(__file__))

PEDIDOS_CLASS = "TFormHTransaccion_Pedidos"   # title='Transacciones : : PEDIDOS'
GRID_EDIT_CLASSES = ("THybridEdit", "THybridEditNumber")   # editores de la fila activa
TOTAL_CLASS = "TFrmTotalOperacion"            # title='Total Operación'
PREVIEW_CLASS = "TfrxPreviewForm"             # comprobante (no debería aparecer en esta PC)
CONF_CLASS = "TFConfirmacion"                 # diálogo de confirmación SI/NO genérico

RUTA_VTA = r"H:\HybridLite\HybridEmpresa\HybridDataBase\TTransaccionvta.dat"
RUTA_DET = r"H:\HybridLite\HybridEmpresa\HybridDataBase\TDetalleVta.dat"

TIPO_PEDIDO = 10                              # THT_TIPO / TBT_TIPOOPERACION del pedido
TOL_CANT = 0.001                              # tolerancia de cantidad en la verificación
TOL_PRECIO = 0.01                             # tolerancia de precio (1 centavo exacto)

# UNIDADES DEL PRECIO (verificado 2026-07-28 contra el pedido doc 00004749):
# la celda Precio de la grilla —y TBT_PRECIODEVENTA— van en USD **CON IVA**, las
# MISMAS unidades que productos.precio_venta y que manda la app. NO se divide
# entre 1.16. Comprobación sobre ese documento:
#   TBT_PRECIODEVENTA/THT_FACTORREFERENCIAL == productos.precio_venta exacto
#     05126 -> 9.00 == 9.00 | 01418 -> 0.50 == 0.50 | TPH-12 -> 0.50 == 0.50
#   THT_TOTALNETO      = suma(precio con IVA * cantidad)      -> 8542.33 ✓
#   THT_TOTALIMPUESTO  = IVA CONTENIDO, no agregado encima    -> 1178.25 ✓
#     (11.50 - 11.50/1.16) * 742.8105 = 1178.25
# OJO: el comentario de scratch/compare_sales.py que dice "TBT_PRECIODEVENTA
# almacena el precio SIN IVA" es INCORRECTO; no guiarse por él.

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


def _confirmar_lo_que_pregunte(timeout=5, inmediato_si_no_hay=False):
    """Responde afirmativamente a CUALQUIER diálogo de confirmación/alerta
    (TFConfirmacion / TMessageForm). Cubre el 'Cancelar' de Pedidos (responder SÍ)
    y cualquier alerta que aparezca al Totalizar. Mismo criterio que compras.
    Si inmediato_si_no_hay=True y no hay diálogo en pantalla, retorna False de inmediato
    sin esperar el timeout."""
    t0 = time.time()
    respondido = False
    while time.time() - t0 < timeout:
        h = fp._find_hwnd(CONF_CLASS) or fp._find_hwnd("TMessageForm")
        if not h:
            if respondido or inmediato_si_no_hay:
                return respondido
            time.sleep(0.05)
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
                time.sleep(0.2)
                break
            except Exception:
                continue
        time.sleep(0.05)
    return respondido


def _esperar_foreground(hped, timeout=3.0):
    """Espera a que la ventana de Pedidos vuelva a ser la del frente.

    Una alerta de HybridLite roba el foreground; si se teclea antes de que
    vuelva, las teclas se pierden sin ningún error visible. Devuelve True si
    quedó al frente."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if win32gui.GetForegroundWindow() == hped:
                return True
        except Exception:
            pass
        _focus(hped)
        time.sleep(0.2)
    return False


def _drenar_alertas(hped, timeout=2.0, rondas=4):
    """Cierra las alertas pendientes hasta que no quede ninguna y devuelve el
    foco a Pedidos.

    Antes esto era un `if` con una sola pasada: si aparecía una segunda alerta
    (o una llegaba tarde), quedaba viva y se tragaba las teclas del ítem
    siguiente. Ese es el patrón que dejó el doc 00004751 con 24 de 25 ítems."""
    hubo = False
    for _ in range(rondas):
        if not (fp._find_hwnd(CONF_CLASS) or fp._find_hwnd("TMessageForm")):
            break
        _confirmar_lo_que_pregunte(timeout=timeout)
        hubo = True
        time.sleep(0.2)
    if hubo:
        _esperar_foreground(hped)
    return hubo


def _fila_activa(hped):
    """(top, campos) de la fila que se está EDITANDO en la grilla de Pedidos.

    Solo la fila activa expone editores vivos; la ya posteada deja de ser
    legible (mismo comportamiento que la grilla de Ajustes, ver
    flujo_stock_real._celdas). Los editores de una fila comparten 'top', así que
    se agrupan por esa coordenada (±3px) y se toma la banda con >=3 controles —
    eso descarta los edits sueltos de la ventana (buscador, panel de seriales)
    que también caen dentro del rectángulo de la grilla.

    Orden de columnas VERIFICADO el 2026-07-28 con
    diagnostico/diag_fila_en_curso_pedidos.py:
        THybridEdit       -> codigo | descripcion | unidad
        THybridEditNumber -> cantidad | precio | (6a columna)
    Se indexa por posición relativa, no por 'left' absoluto, para que no dependa
    de dónde esté la ventana.

    Devuelve (None, {}) si no se puede leer; el llamador decide qué hacer.
    """
    try:
        ped = fp._win(hped)
        grid = ped.child_window(class_name="TAdvStringGrid", found_index=0)
        gr = grid.rectangle()
        ctrls = []
        for c in ped.descendants():
            try:
                cls = c.class_name()
                r = c.rectangle()
            except Exception:
                continue
            if cls not in GRID_EDIT_CLASSES:
                continue
            if gr.left <= r.left < gr.right and gr.top <= r.top < gr.bottom:
                ctrls.append((r.top, r.left, cls, c))
    except Exception as e:
        log.debug("No pude inspeccionar la grilla de Pedidos: %r", e)
        return None, {}

    bandas = {}
    for top, left, cls, c in ctrls:
        clave = next((k for k in bandas if abs(k - top) <= 3), top)
        bandas.setdefault(clave, []).append((left, cls, c))

    candidatas = {k: v for k, v in bandas.items() if len(v) >= 3}
    if not candidatas:
        return None, {}

    top = max(candidatas)
    fila = sorted(candidatas[top], key=lambda x: x[0])

    def txt(c):
        try:
            return (c.window_text() or "").strip()
        except Exception:
            return ""

    edits = [c for _, cls, c in fila if cls == "THybridEdit"]
    nums = [c for _, cls, c in fila if cls == "THybridEditNumber"]

    campos = {
        "codigo":      txt(edits[0]) if len(edits) >= 1 else "",
        "descripcion": txt(edits[1]) if len(edits) >= 2 else "",
        "cantidad":    txt(nums[0]) if len(nums) >= 1 else "",
        "precio":      txt(nums[1]) if len(nums) >= 2 else "",
    }
    return top, campos


def _verificar_producto_cargado(hped, codigo, clave_busqueda=None):
    """Confirma EN PANTALLA que el código llegó a la grilla y que HybridLite
    resolvió el producto, antes de seguir tecleando cantidad y precio.
    Acepta que la celda contenga o bien el código original o la clave de búsqueda
    (referencia/código de barras) tecleada para evitar colisiones.

    Este es el chequeo que faltaba el 2026-07-28: una alerta asíncrona ('llegó
    al mínimo' del ítem anterior) robó el foco, las teclas del código 05133 se
    perdieron, y cargar_item lo dio por cargado igual -> el doc 00004751 quedó
    con 24 de 25 ítems y recién se detectó tras Totalizar, con el documento ya
    permanente.

    Si la fila no se puede leer se avisa y se sigue: una lectura fallida no debe
    tumbar un flujo que ya funcionaba (la verificación contra DBISAM sigue de
    red final)."""
    _, campos = _fila_activa(hped)
    if not campos:
        log.warning("No pude leer la fila en curso del ítem %s: queda sin verificar "
                    "en pantalla.", codigo)
        return

    leido = campos.get("codigo", "").strip().upper()
    esperados = {str(codigo).strip().upper()}
    if clave_busqueda:
        esperados.add(str(clave_busqueda).strip().upper())
    if leido not in esperados:
        raise PedidoError(
            f"El código {codigo} no llegó a la grilla (la celda quedó en {leido!r}). "
            f"Casi seguro una alerta de HybridLite robó el foco y se comió las teclas."
        )
    if not campos.get("descripcion"):
        raise PedidoError(
            f"El ítem {codigo} quedó sin descripción en la grilla: HybridLite no "
            f"resolvió el producto. No sigo tecleando a ciegas."
        )


def _verificar_fila_posteada(hped, codigo, top_antes):
    """Confirma que la fila entró al documento.

    La fila posteada no se puede leer, pero la fila ACTIVA baja una posición
    cuando el ítem entra (40px medidos el 2026-07-28 con
    diagnostico/diag_fila_activa_pedidos.py: 321 -> 361 -> 401). Si no bajó, el
    ítem no está en el documento.

    Se compara con '>' y no contra los 40px exactos para no atarse a la
    resolución ni al tema de la ventana."""
    top_ahora, _ = _fila_activa(hped)

    if top_ahora is None:
        log.warning("No pude leer la fila activa tras postear %s: queda sin verificar "
                    "en pantalla.", codigo)
        return
    if top_antes is None:
        return   # sin referencia previa; que exista banda ya indica fila viva
    if top_ahora <= top_antes:
        raise PedidoError(
            f"El ítem {codigo} no se posteó: la fila activa siguió en y={top_ahora}. "
            f"Se cancela el documento completo para no dejarlo a medias."
        )


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
    time.sleep(0.1)

    btn = None
    try:
        cand = main.child_window(title="Pédidos de clientes", class_name="TAdvGlassButton")
        if cand.exists(timeout=0) and cand.is_visible():
            btn = cand
    except Exception:
        pass

    if btn is None:
        # Menú lateral Pedidos
        L, T, _, _ = win32gui.GetWindowRect(hmain)
        ri.click(L + MENU_PEDIDOS_GRUPO_REL[0], T + MENU_PEDIDOS_GRUPO_REL[1])
        t0 = time.time()
        while time.time() - t0 < 2.0:
            try:
                cand = main.child_window(title="Pédidos de clientes", class_name="TAdvGlassButton")
                if cand.exists(timeout=0) and cand.is_visible():
                    btn = cand
                    break
            except Exception:
                pass
            time.sleep(0.04)
        if btn is None:
            btn = main.child_window(title="Pédidos de clientes", class_name="TAdvGlassButton")
            btn.wait("exists visible", timeout=1.5)

    r = btn.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)

    t0 = time.time()
    while time.time() - t0 < 10:
        ha = fp._find_hwnd(PEDIDOS_CLASS)
        if ha:
            time.sleep(0.1)
            return ha
        time.sleep(0.04)
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
    fpr._esperar_desocupada(hbusq, que="la lista de clientes")
    _focus(hbusq)

    ed = busq.child_window(class_name="THybridEdit", found_index=0)
    r = ed.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    time.sleep(0.05)
    ri.clear_field()
    ri.type_text(str(cliente_codigo))
    time.sleep(0.04)
    ri.press("ENTER")                                    # ejecuta la búsqueda

    fpr._esperar_desocupada(hbusq, que="el filtro de clientes")
    filtrada = fpr._esperar_lista_filtrada(busq, timeout=60.0)
    log.info("Busqueda De Clientes filtrada para %s: %s (scrollbar)", cliente_codigo, filtrada)

    if fp._find_hwnd(fp.BUSQ_CLASS):
        _focus(hbusq)
        grid = busq.child_window(class_name="TDBGrid")
        gr = grid.rectangle()
        ri.click(gr.left + 100, gr.top + 26, double=True)  # fila 1 = el resultado
        time.sleep(0.05)

    if fp._find_hwnd(fp.BUSQ_CLASS):
        # fallback: ENTER por teclado si el doble-clic no cerró la búsqueda
        _focus(hbusq)
        ri.press("ENTER")
        time.sleep(0.3)

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
def cargar_item(codigo, cantidad, precio=None, es_primero=False, clave_busqueda=None):
    """Teclea un ítem en la grilla de Pedidos:
        (solo el 1er ítem) clic en la celda Código de la grilla TAdvStringGrid
        código -> ENTER (carga) -> cantidad -> ENTER -> [precio] -> ENTER (postea)

    `precio` (USD CON IVA, como lo manda la app) es OPCIONAL:
      * None  -> no se teclea nada: el 2º ENTER acepta lo que Hybrid ya puso en la
                 celda, o sea el PRECIO MAESTRO. Es el comportamiento histórico y
                 la ruta por defecto.
      * valor -> se teclea TAL CUAL (USD con IVA, sin convertir) con el sufijo
                 '$', igual que el costo en compras, donde el '$' le indica a
                 HybridLite que el número va en dólares
                 (ver flujo_compra_real.cargar_item: type_number + press_shift('4')).

    `clave_busqueda`: si el código está interceptado en el catálogo por la referencia
    de otro producto, se teclea su referencia propia única para esquivar la colisión.

    Lanza PedidoError ante cualquier diálogo de error; el llamador cancela TODO
    el documento.

    CONFIRMADO EN VIVO (grabación 2026-07-28, grabar_flujo_20260728_165901.log):
    el dueño hizo código -> ENTER -> ENTER (cantidad por defecto) -> '2' +
    Shift+4 ('$') -> ENTER. O sea el campo que sigue a Cantidad ES el Precio y
    acepta el sufijo '$'. Coincide con esta secuencia.

    # CALIBRAR: el ENTER final (posteo) se tomó de la grabación; si en vivo la
    # fila no postea o pide algo más, ajustar aquí. Los ítems siguientes NO
    # re-clickean la grilla (el cursor baja solo tras postear, igual que en
    # compras). La verificación contra DBISAM (_verificar_pedido_db) compara el
    # precio y aborta si no cuadra."""
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
        time.sleep(0.15)

    # drenar TODA alerta colgada antes de teclear, y esperar a que Pedidos vuelva
    # al frente: teclear con una alerta viva es exactamente lo que perdió el ítem
    # 05133 del doc 00004751 (2026-07-28). Solo interviene si hay alerta.
    if fp._find_hwnd(CONF_CLASS) or fp._find_hwnd("TMessageForm"):
        _drenar_alertas(hped)
        _esperar_foreground(hped)

    # referencia para comprobar después que la fila realmente se posteó
    top_antes, _ = _fila_activa(hped)

    a_teclear = clave_busqueda or codigo
    if a_teclear != codigo:
        log.info("Ítem %s: se teclea %r para esquivar colisión código/referencia.",
                 codigo, a_teclear)

    ri.type_code(str(a_teclear))
    time.sleep(0.15)
    ri.press("ENTER")                    # carga el producto; el cursor salta a Cantidad
    time.sleep(0.5)

    # un diálogo de error acá = código inexistente / producto no válido
    if fp._find_hwnd("TMessageForm"):
        raise PedidoError(f"Error al cargar el ítem {codigo} (¿código inexistente?).")

    # el código llegó y HybridLite resolvió el producto (si no, no seguimos a ciegas)
    _verificar_producto_cargado(hped, codigo, clave_busqueda=a_teclear)

    ri.type_number(f"{float(cantidad):g}")
    time.sleep(0.1)
    ri.press("ENTER")                    # confirma la cantidad
    time.sleep(0.2)

    # Precio manual: tras confirmar la cantidad el cursor queda en la celda
    # Precio con el maestro puesto (CONFIRMADO en la grabación 2026-07-28
    # grabar_flujo_20260728_165901.log: código->ENTER->ENTER->'2'+Shift+4->ENTER).
    # Se sobreescribe con el valor en USD CON IVA + '$'. Sin precio no se teclea
    # nada y el ENTER de abajo acepta el maestro.
    if precio is not None:
        if not (float(precio) > 0):
            raise PedidoError(f"Precio inválido para el ítem {codigo}: {precio!r}.")
        ri.type_number(f"{float(precio):.2f}")
        time.sleep(0.08)
        ri.press_shift("4")              # '$' (layout latam): marca el valor como USD
        time.sleep(0.08)

    # Telemetría del precio manual: la celda es legible mientras la fila sigue
    # activa. No se valida acá (el '$' puede reformatear el valor y un falso
    # negativo cancelaría el documento); la validación dura es contra la DBISAM.
    if precio is not None:
        _, campos_previos = _fila_activa(hped)
        if campos_previos:
            log.info("Ítem %s: celda Precio antes de postear = %r (tecleado %.2f).",
                     codigo, campos_previos.get("precio"), float(precio))

    ri.press("ENTER")                    # postea la fila / baja a la siguiente  # CALIBRAR
    time.sleep(0.3)

    # un diálogo acá con precio manual suele ser "precio bajo el costo" o un
    # permiso que el usuario de Hybrid no tiene: se drena igual que el resto
    if fp._find_hwnd("TMessageForm") and precio is not None:
        raise PedidoError(
            f"HybridLite rechazó el precio manual del ítem {codigo} "
            f"(${float(precio):.2f} con IVA). ¿El usuario tiene permiso para cambiar precio?"
        )

    # drenar una alerta tardía (p.ej. 'llegó al mínimo') solo si existe (sin dormir si no hay)
    if fp._find_hwnd(CONF_CLASS) or fp._find_hwnd("TMessageForm"):
        _drenar_alertas(hped, timeout=1.0)

    # la fila entró de verdad al documento (si no, se cancela todo)
    _verificar_fila_posteada(hped, codigo, top_antes)

    if precio is None:
        log.info("Ítem %s cargado (cant=%s, precio maestro).", codigo, cantidad)
    else:
        log.info("Ítem %s cargado (cant=%s, precio manual $%.2f con IVA).",
                 codigo, cantidad, float(precio))


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
            time.sleep(0.3)
            break
        except Exception:
            continue
    if cancelado:
        _confirmar_lo_que_pregunte(timeout=3, inmediato_si_no_hay=False)
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
            time.sleep(0.3)
            break
        except Exception:
            continue
    else:
        L, T, _, _ = win32gui.GetWindowRect(hped)
        ri.click(L + SALIR_REL[0], T + SALIR_REL[1])
        time.sleep(0.3)
    _confirmar_lo_que_pregunte(timeout=1.5, inmediato_si_no_hay=True)
    for _ in range(10):
        h = fp._find_hwnd(PEDIDOS_CLASS)
        if not h:
            return
        try:
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass
        time.sleep(0.04)


def _totalizar_pedido(hped):
    """'&Totalizar' -> TFrmTotalOperacion -> 'T&otalizar' (SIN número de documento,
    SIN comprobante). Reintenta el clic a Totalizar (la ventana puede no estar al
    frente cuando cae el clic real). Devuelve True si el flujo llegó al final."""
    htot = None
    for intento in range(1, 4):
        _focus(hped)
        time.sleep(0.2)
        ped = fp._win(hped)
        try:
            b = ped.child_window(title="&Totalizar", class_name="TFlatButton")
            r = b.rectangle()
            ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
        except Exception:
            L, T, _, _ = win32gui.GetWindowRect(hped)
            ri.click(L + TOTALIZAR_REL[0], T + TOTALIZAR_REL[1])
        _confirmar_lo_que_pregunte(timeout=1.5, inmediato_si_no_hay=False)
        t0 = time.time()
        while time.time() - t0 < 5:
            htot = fp._find_hwnd(TOTAL_CLASS)
            if htot:
                break
            time.sleep(0.05)
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
    time.sleep(0.4)

    # esta PC no tiene impresora fiscal -> no debería abrir Vista Previa; por si
    # acaso, se cierra igual que en compras.
    for _ in range(3):
        h = fp._find_hwnd(PREVIEW_CLASS)
        if not h:
            break
        try:
            win32gui.SetForegroundWindow(h)
            time.sleep(0.1)
            ri.press("ESC")
            time.sleep(0.1)
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass
        time.sleep(0.1)

    _confirmar_lo_que_pregunte(timeout=1.5, inmediato_si_no_hay=False)
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


def _evaluar_pedido_db(header, detalle, cliente_codigo, items, cliente_nombre=None):
    """Evalúa si header y detalle de DBISAM corresponden al pedido registrado."""
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

    # ítems: mapa codigo -> (cantidad, precio) en el detalle
    en_db = {}
    precio_db = {}
    for d in detalle:
        c = str(d.get("TBT_CODIGO") or "").strip()
        en_db[c] = en_db.get(c, 0.0) + float(d.get("TBT_CANTIDAD") or 0)
        precio_db[c] = float(d.get("TBT_PRECIODEVENTA") or 0)

    # TBT_PRECIODEVENTA está en Bs CON IVA; el factor del propio documento lo
    # lleva a USD, quedando en las mismas unidades que manda la app (ver el
    # bloque UNIDADES DEL PRECIO arriba, verificado contra doc 00004749).
    tasa = float(header.get("THT_FACTORREFERENCIAL") or 0)

    for it in items:
        c = str(it["codigo"]).strip()
        if c not in en_db:
            fallos.append(f"el ítem {c} no aparece en el detalle del pedido")
            continue
        if abs(en_db[c] - float(it["cantidad"])) > TOL_CANT:
            fallos.append(f"ítem {c}: cantidad en DB={en_db[c]}, esperaba {it['cantidad']}")

        # Solo se verifica el precio de los ítems que traían uno manual: los
        # demás quedaron con el maestro, que no conocemos desde acá.
        esperado = it.get("precio")
        if esperado is None:
            continue
        if tasa <= 0:
            fallos.append(f"ítem {c}: no pude verificar el precio manual "
                          f"(THT_FACTORREFERENCIAL={tasa!r} en el documento)")
            continue
        usd = precio_db[c] / tasa
        if abs(usd - float(esperado)) > TOL_PRECIO:
            fallos.append(
                f"ítem {c}: precio en DB=${usd:.2f}, esperaba ${float(esperado):.2f} "
                f"(ambos USD con IVA)"
            )

    if fallos:
        return False, f"pedido doc={doc}: " + "; ".join(fallos), doc
    return True, (f"pedido doc={doc} VERIFICADO en DB (cliente={persona!r}, "
                  f"{len(items)} ítem(s), status={header.get('THT_STATUS')})."), doc


def _verificar_pedido_db(cliente_codigo, items, cliente_nombre=None, max_intentos=3):
    """Confirma que el último pedido Tipo 10 en DBISAM corresponde a lo pedido:
    cliente (rif/nombre) + un ítem por código con la cantidad correcta.
    Implementa reintentos con pausa para absorber posibles retrasos de flush SMB en red H:.
    Devuelve (ok: bool, detalle: str, documento: str|None)."""
    ultimo_error = (False, "no hay ningún documento Tipo 10 en la base tras totalizar.", None)
    for intento in range(1, max_intentos + 1):
        try:
            header, detalle = _ultimo_pedido_db()
            if header is not None:
                ok, msg, doc = _evaluar_pedido_db(header, detalle, cliente_codigo, items, cliente_nombre)
                if ok:
                    return True, msg, doc
                ultimo_error = (ok, msg, doc)
            else:
                ultimo_error = (False, "no hay ningún documento Tipo 10 en la base tras totalizar.", None)
        except Exception as e:
            log.warning("Intento %s/%s: error leyendo DBISAM de pedidos (%s)", intento, max_intentos, e)
            ultimo_error = (False, f"Error leyendo DBISAM: {e}", None)

        if intento < max_intentos:
            time.sleep(0.5)

    return ultimo_error


# ── orquestador ──────────────────────────────────────────────────────────────
def registrar_pedido(cliente_codigo, items, commit=False, cliente_nombre=None):
    """items: list[dict] {"codigo": str, "cantidad": float, "precio": float|None}.
    "precio" es opcional (USD CON IVA): si falta o es None se usa el precio
    maestro de Hybrid, que es el comportamiento histórico.
    Return: {"ok": bool, "etapa": str, "detalle": str}.
    etapas éxito: "commit" | "preview"
    etapas fallo PRE-commit (reintentables, documento cancelado completo):
      "abrir_hybrid" | "navegacion" (abrir/cliente) | "carga_item"
    etapas fallo AMBIGUAS (NO reintentar solo): "totalizar" | "verificacion_db"
    REGLA DE ORO: cualquier fallo antes de Totalizar -> Cancelar + Salir + etapa
    pre-commit. El pedido es TODO-O-NADA (un documento)."""
    if not items:
        return {"ok": False, "etapa": "navegacion", "detalle": "La lista de items está vacía."}

    # 1. Resolver alias de proveedores/códigos para cada ítem
    items_procesados = []
    for it in items:
        cod_orig = str(it["codigo"]).strip()
        cod_resuelto = am.resolver_alias(cod_orig)
        it_copia = dict(it)
        it_copia["codigo"] = cod_resuelto
        if cod_resuelto != cod_orig:
            log.info("Ítem con alias resuelto: %s -> %s", cod_orig, cod_resuelto)
        items_procesados.append(it_copia)

    # 2. Validar códigos duplicados sobre los códigos ya resueltos
    codigos_norm = [str(it["codigo"]).strip().lower() for it in items_procesados]
    vistos, dups = set(), set()
    for c in codigos_norm:
        (dups if c in vistos else vistos).add(c)
    if dups:
        return {"ok": False, "etapa": "navegacion",
                "detalle": f"Códigos duplicados en el pedido: {sorted(dups)}. Nada se tocó."}

    # 3. Pre-vuelo de colisiones código vs referencia (ver colisiones.py).
    # Se evalúa ANTES de abrir la UI de Pedidos. Si algún producto está interceptado
    # y carece de clave segura, aborta limpio sin tocar la grilla.
    codigos_a_revisar = [it["codigo"] for it in items_procesados]
    try:
        claves_busqueda, problemas = colisiones.revisar_lote(codigos_a_revisar)
    except colisiones.CatalogoIlegible as e:
        return {"ok": False, "etapa": "navegacion",
                "detalle": f"No pude verificar colisiones código/referencia: {e}. "
                           f"Nada se tocó (fail-closed)."}
    if problemas:
        detalle = " | ".join(f"{c}: {m}" for c, m in problemas.items())
        log.error("Pedido ABORTADO por colisión sin salida: %s", detalle)
        return {"ok": False, "etapa": "navegacion",
                "detalle": f"Pedido CANCELADO antes de tocar nada: "
                           f"{len(problemas)} ítem(s) sin clave de búsqueda segura. "
                           f"{detalle}"}
    for codigo, clave in claves_busqueda.items():
        if clave != codigo:
            log.warning("Ítem %s se tecleará como %r (colisión evitada).", codigo, clave)

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
    for it in items_procesados:
        cod = it["codigo"]
        clave = claves_busqueda.get(str(cod).strip(), cod)
        try:
            cargar_item(cod, it["cantidad"], precio=it.get("precio"), es_primero=primero, clave_busqueda=clave)
            primero = False
        except PedidoError as e:
            _cancelar_pedido(fp._find_hwnd(PEDIDOS_CLASS))
            _salir_pedidos()
            return {"ok": False, "etapa": "carga_item",
                    "detalle": f"Pedido CANCELADO completo (todo-o-nada), fallo en "
                               f"{cod}: {e}"}

    if not commit:
        _cancelar_pedido(fp._find_hwnd(PEDIDOS_CLASS))
        _salir_pedidos()
        return {"ok": True, "etapa": "preview",
                "detalle": f"Preview de {len(items_procesados)} ítem(s) armado en pantalla y "
                           f"DESCARTADO (sin --commit; documento cancelado)."}

    # COMMIT: Totalizar (etapa AMBIGUA si falla)
    hped = fp._find_hwnd(PEDIDOS_CLASS)
    try:
        _totalizar_pedido(hped)
    except (PedidoError, fp.FlujoError) as e:
        return {"ok": False, "etapa": "totalizar",
                "detalle": f"No pude confirmar la totalización del pedido: {e}"}

    _salir_pedidos()
    time.sleep(0.4)

    try:
        ok_db, detalle_db, documento = _verificar_pedido_db(cliente_codigo, items_procesados, cliente_nombre)
    except Exception as e:
        return {"ok": False, "etapa": "verificacion_db",
                "detalle": f"Pedido totalizado pero no pude verificar en DB: {e}"}

    if ok_db:
        return {"ok": True, "etapa": "commit", "detalle": detalle_db, "documento": documento}
    return {"ok": False, "etapa": "verificacion_db",
            "detalle": f"¡ALERTA! {detalle_db}", "documento": documento}


# ── CLI ──────────────────────────────────────────────────────────────────────
def _parse_items(spec):
    """'COD:cant[:precio],COD2:cant2[:precio2]' -> list[dict].
    El precio es opcional y va en USD CON IVA (como lo manda la app); sin él, el
    ítem usa el precio maestro de Hybrid."""
    items = []
    for par in spec.split(","):
        partes = par.split(":")
        if len(partes) not in (2, 3):
            raise ValueError(f"Ítem inválido: {par!r} (formato codigo:cantidad[:precio])")
        codigo = partes[0].strip()
        if not codigo:
            raise ValueError(f"Ítem inválido: {par!r} (código vacío)")
        precio = float(partes[2]) if len(partes) == 3 and partes[2].strip() else None
        items.append({"codigo": codigo, "cantidad": float(partes[1]), "precio": precio})
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
              '--items "COD:cant[:precioUSDconIVA],..." [--commit]')
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
