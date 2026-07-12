"""
flujo_compra_real.py — Registro de una COMPRA (documento de mercancías) en
HybridLiteOS con INPUT REAL de hardware.

Replica EXACTAMENTE la coreografía grabada del dueño el 2026-07-11 (ver
FLUJO-COMPRA-CAPTURADO.log en este mismo directorio, fuente de verdad). El
input sintético de pywinauto lo rechaza la app ("Database name is missing");
localizamos ventanas/controles con win32/pywinauto (solo lectura) y ejecutamos
clics/teclas con realinput (SendInput real), igual que flujo_precio_real.py y
flujo_stock_real.py.

Secuencia (registrar_compra, un solo documento de Compras):
  1. Menú Compras -> 'Compra de mercancías' (TAdvGlassButton) -> abre/reutiliza
     TFormHTransaccion_Compras 'Transacciones : : COMPRAS'.
  2. CLASIFICACIÓN: campo (THybridEdit) -> teclear CLASE_COMPRA="5" -> botón
     'F&1' -> Busqueda De Clases (TForm_BusquedaConfDb) -> ENTER selecciona la
     fila posicionada por el "5" tecleado (fallback: doble-clic 1a fila).
  3. PROVEEDOR: botón 'F1' -> Busqueda De Proveedores -> Ed_Buscar: código del
     proveedor -> ENTER (busca/posiciona) -> ENTER (selecciona). Mismo patrón
     EXACTO de cargar_producto() en flujo_precio_real.py (código -> ENTER ->
     espera de refresco -> ENTER).
  4. Por cada ítem (el foco ya queda en la celda Código de la grilla tras
     seleccionar proveedor, sin clic adicional -- así lo muestra la grabación):
       código -> ENTER (carga el producto)
       cantidad -> ENTER
       costo (columna con '$' al final: numérico + Shift+4 para el '$') -> ENTER
       -> se abre TFHCostosPrecios: escribir SOLO el precio (reutiliza
          escribir_precio de flujo_precio_real) -> Aceptar+Salir (commit) o
          solo Salir (preview, descarta el ítem).
  5. commit=True, tras el último ítem: '&Totalizar' -> TFrmTotalOperacion ->
     doc_numero -> ENTER -> doc_numero (sin 2º ENTER) -> 'T&otalizar' -> se
     abre TfrxPreviewForm 'Vista Previa', se cierra con el patrón probado de
     _totalizar_y_guardar (ESC + WM_SYSCOMMAND SC_CLOSE + WM_CLOSE) -> Salir
     de la ventana de Compras.
     commit=False (preview): NO se totaliza -- tras el último ítem se pulsa
     'Cancelar' (confirmando lo que pregunte) y luego 'Salir' de Compras. La
     compra es TODO-O-NADA: cualquier fallo antes de pulsar Totalizar cancela
     el documento completo (no queda nada a medias, 100% reintentable).
  6. Verificación (solo commit) contra DBISAM por ítem: existencia esperada =
     existencia_antes + cantidad (read_db_existencia), costo/precio esperados
     via hybrid_price_writer._db_costo_usd / _db_precio_usd, tolerancia 0.01/0.02.

SEGURIDAD: preview por defecto (llena y verifica en pantalla, NO guarda nada);
--commit aplica de verdad y verifica contra la base. Todo-o-nada: la compra es
UN documento, no una serie de cambios independientes -- ante cualquier fallo
PRE-Totalizar se cancela el documento completo.

USO:
    python flujo_compra_real.py 01404 --items "01404:10:0.50:1.00" --doc 123456
    python flujo_compra_real.py 01404 --items "01404:10:0.50:1.00,02233:5:2.00:3.50" \
        --doc 123456 --commit
"""
import os
import sys
import time
import logging

import win32gui
import win32con

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import flujo_precio as fp                    # helpers de ventanas + constantes de clase
import flujo_precio_real as fpr               # escribir_precio, _click_boton_dialogo, _focus...
import flujo_stock_real as fsr                # _cerrar_ficha_si_abierta (modelo de apertura)
import hybrid_price_writer as hpw             # _db_precio_usd, _db_costo_usd
import read_db_existencia as dbex             # existencia() de verificación
import realinput as ri

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("compra_real")

DIR = os.path.dirname(os.path.abspath(__file__))

COMPRAS_CLASS = "TFormHTransaccion_Compras"   # title='Transacciones : : COMPRAS'
TOTAL_CLASS = "TFrmTotalOperacion"            # title='Total Operación'
PREVIEW_CLASS = "TfrxPreviewForm"             # title='Vista Previa' (comprobante)
CONF_CLASS = "TFConfirmacion"                 # diálogo de confirmación SI/NO genérico

# CLASE_COMPRA: clasificación "5" = NOTAS DE ENTREGA, confirmada en la grabación
# (2026-07-11) y en TGeneralClases. SIEMPRE 5 para compra de mercancías -- no
# es parametrizable, es un valor fijo del catálogo de clasificaciones de Hybrid.
CLASE_COMPRA = "5"

TOL_COSTO_PRECIO = 0.02   # misma tolerancia que flujo_precio_real (TOL)
TOL_EXISTENCIA = 0.01     # misma tolerancia que flujo_stock_real

# Botón lateral del menú Compras (owner-drawn, sin título): fallback si el
# botón 'Compra de mercancías' no aparece directo (grupo de menú aún no
# desplegado). Coordenadas relativas a TF_MainHybridCashMG, de la grabación.
MENU_COMPRAS_REL = (179, 191)

# Coordenadas relativas (fallbacks por posición) tomadas de la grabación
# 2026-07-11, usadas SOLO si la localización por título/clase no encuentra el
# control (ver cada función para el intento primario).
CLASIFICACION_REL = (257, 122)     # campo Clasificación (fila 2 del header)
CLASIFICACION_F1_REL = (292, 119)  # botón 'F&1' junto al campo Clasificación
PROVEEDOR_F1_REL = (296, 146)      # botón 'F1' de la fila Proveedor
TOTALIZAR_REL = (644, 691)         # botón '&Totalizar' (barra inferior de Compras)
TOTAL_OPERAR_REL = (584, 660)      # botón 'T&otalizar' de TFrmTotalOperacion


class CompraError(Exception):
    pass


# ── utilidades compartidas (mismo patrón que flujo_precio_real/flujo_stock_real) ──
def _focus(hwnd):
    """Fuerza que la ventana esté al frente antes de disparar input real."""
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
    """Responde afirmativamente a CUALQUIER diálogo de confirmación que
    aparezca (TFConfirmacion o TMessageForm), probando una lista amplia de
    títulos de botón. Usado por _cancelar_compra: 'Cancelar' en Compras
    probablemente pregunta si se desea cancelar -> hay que responder SÍ (a
    diferencia de flujo_stock_real._cancelar, que responde NO porque ahí
    'Cancelar' descarta un documento nuevo vacío sin más preguntas)."""
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
        for titulo in ("&SI", "SI", "Sí", "&Sí", "&Yes", "Yes", "Aceptar"):
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


# ── lectura/verificación del header de Compras ───────────────────────────────
def _leer_header_compras(hcom):
    """Lee los campos de la columna izquierda del header de Compras (Depósito /
    Clasificación / Proveedor) para VERIFICAR que la selección quedó bien: la
    búsqueda (clases/proveedores) puede cerrarse SIN haber seleccionado lo
    correcto, y el 'posicionada: False' de _esperar_refresco no siempre es
    fiable. Identifica cada campo por su franja de `top` relativa (confirmado
    en vivo 2026-07-11: depósito ~74, clase ~106, proveedor ~138). Devuelve
    dict {deposito, clase, proveedor} con '' donde no haya valor."""
    res = {"deposito": "", "clase": "", "proveedor": ""}
    if not hcom:
        return res
    com = fp._win(hcom)
    L, T, _, _ = win32gui.GetWindowRect(hcom)
    for c in com.descendants(class_name="THybridEdit"):
        r = c.rectangle()
        rel_top = r.top - T
        rel_left = r.left - L
        txt = (c.window_text() or "").strip()
        if rel_left >= 25 or not txt:
            continue
        if 60 <= rel_top < 95:
            res["deposito"] = txt
        elif 95 <= rel_top < 125:
            res["clase"] = txt
        elif 125 <= rel_top < 160:
            res["proveedor"] = txt
    return res


# ── apertura de la ventana de Compras ────────────────────────────────────────
def abrir_compras():
    """Garantiza que TFormHTransaccion_Compras esté abierta. Reutiliza si ya
    está abierta; si no, cierra la Ficha residual (mismo riesgo que documenta
    flujo_stock_real._cerrar_ficha_si_abierta: con la Ficha delante, el clic
    al menú lateral no llega) y navega Menú Compras -> 'Compra de mercancías'.
    Devuelve su hwnd."""
    ha = fp._find_hwnd(COMPRAS_CLASS)
    if ha:
        log.info("Ventana de Compras ya abierta, reutilizando.")
        return ha

    fsr._cerrar_ficha_si_abierta()

    hmain = fp._find_hwnd(fp.MAIN_CLASS)
    if not hmain:
        raise CompraError("HybridLiteOS no está abierto (no veo el módulo principal).")
    main = fp._win(hmain)
    _focus(hmain)
    time.sleep(0.2)

    try:
        btn = main.child_window(title="Compra de mercancías", class_name="TAdvGlassButton")
        btn.wait("exists visible", timeout=1.5)
    except Exception:
        # el grupo de menú Compras aún no está desplegado -> abrirlo por el
        # panel lateral (fallback de coordenadas, calcado de abrir_ajustes())
        L, T, _, _ = win32gui.GetWindowRect(hmain)
        ri.click(L + MENU_COMPRAS_REL[0], T + MENU_COMPRAS_REL[1])
        time.sleep(0.8)
        btn = main.child_window(title="Compra de mercancías", class_name="TAdvGlassButton")
        btn.wait("exists visible", timeout=8)

    r = btn.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)

    t0 = time.time()
    while time.time() - t0 < 15:
        ha = fp._find_hwnd(COMPRAS_CLASS)
        if ha:
            time.sleep(1.0)
            return ha
        time.sleep(0.3)
    raise CompraError("No abrió la ventana de Compras (TFormHTransaccion_Compras).")


# ── clasificación ─────────────────────────────────────────────────────────────
def fijar_clasificacion(com):
    """Teclea CLASE_COMPRA en el campo Clasificación y lo confirma en el
    diálogo Busqueda De Clases. El '5' tecleado ya filtra/posiciona la fila
    (igual que el código en Ed_Buscar de cargar_producto), así que ENTER
    selecciona directo; fallback doble-clic en la 1a fila si el diálogo
    sigue abierto.

    El campo de Clasificación se localiza POR COORDENADA (rel. a la ventana,
    tal cual la grabación), no por título/found_index: el control real que
    quedó registrado ahí es un THybridEdit con nombre 'DEPOSITO1' (owner
    naming interno de Hybrid, no describe su función en pantalla), y la fila
    del header tiene más de un THybridEdit -- un found_index=0 arriesgaría
    clickear el campo equivocado. No hay título fiable para buscarlo."""
    hcom = fp._find_hwnd(COMPRAS_CLASS)
    _focus(hcom)

    L, T, _, _ = win32gui.GetWindowRect(hcom)
    ri.click(L + CLASIFICACION_REL[0], T + CLASIFICACION_REL[1])
    time.sleep(0.3)
    ri.type_code(CLASE_COMPRA)
    time.sleep(0.3)

    try:
        boton = com.child_window(title="F&1", class_name="TFlatButton")
        r = boton.rectangle()
        ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    except Exception:
        L, T, _, _ = win32gui.GetWindowRect(hcom)
        ri.click(L + CLASIFICACION_F1_REL[0], T + CLASIFICACION_F1_REL[1])

    hbusq = fp._wait_for(fp.BUSQ_CLASS, desc="Busqueda De Clases")
    _focus(hbusq)
    time.sleep(0.3)
    ri.press("ENTER")            # selecciona la fila ya posicionada por el "5"
    time.sleep(0.8)

    if fp._find_hwnd(fp.BUSQ_CLASS) is not None:
        # fallback: doble-clic en la primera fila del grid (patrón cargar_producto)
        busq = fp._win(fp._find_hwnd(fp.BUSQ_CLASS))
        try:
            grid = busq.child_window(class_name="TDBGrid")
            gr = grid.rectangle()
            ri.click(gr.left + 60, gr.top + 34, double=True)
            time.sleep(1.0)
        except Exception:
            pass

    if fp._find_hwnd(fp.BUSQ_CLASS) is not None:
        raise CompraError("La Busqueda De Clases no se cerró tras seleccionar "
                          f"CLASE_COMPRA={CLASE_COMPRA}.")

    # VERIFICAR en pantalla que quedó la clase correcta (la búsqueda pudo
    # cerrarse sobre otra fila). El campo muestra "5-NOTAS DE ENTREGA".
    header = _leer_header_compras(fp._find_hwnd(COMPRAS_CLASS))
    clase_ui = header["clase"]
    if "NOTAS DE ENTREGA" not in clase_ui.upper() and not clase_ui.startswith(CLASE_COMPRA + "-"):
        raise CompraError(f"La clasificación quedó como {clase_ui!r}, no la clase "
                          f"{CLASE_COMPRA} (NOTAS DE ENTREGA). Abortando la compra.")
    log.info("Clasificación fijada y VERIFICADA en pantalla: %r", clase_ui)


# ── proveedor ─────────────────────────────────────────────────────────────────
def seleccionar_proveedor(com, proveedor_codigo, proveedor_nombre=None):
    """Botón F1 de la fila Proveedor -> Busqueda De Proveedores -> Ed_Buscar:
    código -> ENTER (posiciona) -> ENTER (selecciona). Patrón EXACTO de
    cargar_producto() en flujo_precio_real.py, incluida la espera de refresco.

    `proveedor_nombre` (opcional): si se pasa, se verifica que el campo
    Proveedor del header lo contenga (defensa extra contra seleccionar el
    proveedor equivocado). Sin él, solo se verifica que el campo no quede
    vacío."""
    hcom = fp._find_hwnd(COMPRAS_CLASS)
    _focus(hcom)

    try:
        boton = com.child_window(title="F1", class_name="TFlatButton")
        r = boton.rectangle()
        ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    except Exception:
        L, T, _, _ = win32gui.GetWindowRect(hcom)
        ri.click(L + PROVEEDOR_F1_REL[0], T + PROVEEDOR_F1_REL[1])

    hbusq = fp._wait_for(fp.BUSQ_CLASS, desc="Busqueda De Proveedores")
    busq = fp._win(hbusq)
    time.sleep(0.5)
    _focus(hbusq)

    ed = busq.child_window(class_name="THybridEdit", found_index=0)
    r = ed.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    time.sleep(0.3)
    ri.clear_field()
    ri.type_text(proveedor_codigo)
    time.sleep(0.4)
    ri.press("ENTER")                                    # ejecuta la búsqueda

    posicionado = fpr._esperar_refresco(busq, proveedor_codigo, timeout=6.0)
    log.info("Busqueda De Proveedores posicionada en %s: %s", proveedor_codigo, posicionado)

    if fp._find_hwnd(fp.BUSQ_CLASS):
        _focus(hbusq)
        ri.press("ENTER")                                # selecciona la fila posicionada
        time.sleep(1.2)

    if fp._find_hwnd(fp.BUSQ_CLASS):
        # fallback: doble-clic en la fila posicionada (arriba del grid)
        grid = busq.child_window(class_name="TDBGrid")
        gr = grid.rectangle()
        ri.click(gr.left + 100, gr.top + 26, double=True)
        time.sleep(1.2)

    if fp._find_hwnd("TMessageForm"):
        raise CompraError(f"Apareció un diálogo de error buscando el proveedor {proveedor_codigo}.")
    if fp._find_hwnd(fp.BUSQ_CLASS):
        raise CompraError(f"La Busqueda De Proveedores no se cerró tras seleccionar {proveedor_codigo}.")

    # VERIFICAR en pantalla que el proveedor quedó seleccionado (no vacío) y,
    # si se conoce el nombre esperado, que coincide.
    header = _leer_header_compras(fp._find_hwnd(COMPRAS_CLASS))
    prov_ui = header["proveedor"]
    if not prov_ui:
        raise CompraError(f"El proveedor quedó VACÍO tras seleccionar {proveedor_codigo}. "
                          "Abortando la compra.")
    if proveedor_nombre and proveedor_nombre.strip().upper() not in prov_ui.upper():
        raise CompraError(f"El proveedor quedó como {prov_ui!r}, no coincide con el esperado "
                          f"{proveedor_nombre!r} (código {proveedor_codigo}). Abortando la compra.")
    log.info("Proveedor %s seleccionado y VERIFICADO en pantalla: %r", proveedor_codigo, prov_ui)


# ── ítems de la grilla ──────────────────────────────────────────────────────
def _abrir_costos_precios_item(hcom):
    """Espera a que TFHCostosPrecios aparezca tras teclear costo+ENTER en la
    grilla (se abre SOLO, sin clic -- así lo muestra la grabación)."""
    return fp._wait_for(fp.PRECIOS_CLASS, timeout=10, desc="Costos y Precios (ítem de compra)")


def cargar_item(codigo, cantidad, costo, precio, commit):
    """Teclea un ítem completo en la grilla de Compras (el foco ya está en la
    celda Código, sin clic previo, replicando la grabación):
        código -> ENTER (carga)
        cantidad -> ENTER
        costo (numérico) + Shift+4 ('$') -> ENTER  -> abre TFHCostosPrecios
        precio (escribir_precio, reutilizado de flujo_precio_real) -> Aceptar+Salir
        (commit) o solo Salir (preview, descarta el ítem)
    Lanza CompraError ante cualquier desviación; el llamador cancela TODO el
    documento (política todo-o-nada)."""
    hcom = fp._find_hwnd(COMPRAS_CLASS)
    _focus(hcom)

    ri.type_code(codigo)
    time.sleep(0.3)
    ri.press("ENTER")
    time.sleep(1.2)

    ri.type_number(f"{float(cantidad):g}")
    time.sleep(0.2)
    ri.press("ENTER")
    time.sleep(0.6)

    ri.type_number(f"{float(costo):.2f}")
    time.sleep(0.15)
    ri.press_shift("4")            # '$' (layout latam) que cierra la columna de costo
    time.sleep(0.15)
    ri.press("ENTER")
    time.sleep(0.6)

    try:
        _abrir_costos_precios_item(hcom)
    except fp.FlujoError as e:
        raise CompraError(f"No se abrió Costos y Precios para el ítem {codigo}: {e}")

    try:
        fpr.escribir_precio(float(precio), fpr.IVA_DEF)
    except fpr.PrecioError as e:
        fpr._click_boton_dialogo("Salir")   # descarta el ítem, nada queda a medias
        raise CompraError(f"El precio del ítem {codigo} no cuadró en pantalla: {e}")

    if commit:
        if not fpr._click_boton_dialogo("Aceptar"):
            raise CompraError(f"No pude pulsar 'Aceptar' en Costos y Precios para {codigo}.")
        if fp._find_hwnd(fp.PRECIOS_CLASS):
            fpr._click_boton_dialogo("Salir")
    else:
        fpr._click_boton_dialogo("Salir")   # preview: descarta el ítem individual

    if fp._find_hwnd(fp.PRECIOS_CLASS):
        raise CompraError(f"El diálogo Costos y Precios no se cerró para el ítem {codigo}.")
    log.info("Ítem %s cargado (cant=%s costo=%s precio=%s, commit=%s).",
             codigo, cantidad, costo, precio, commit)


# ── cierre del documento ─────────────────────────────────────────────────────
def _cancelar_compra(hcom):
    """Descarta el documento completo (preview o fallo pre-commit): botón
    'Cancelar' + responder SÍ a lo que pregunte (a diferencia del Cancelar de
    Ajustes, que responde NO -- ver _confirmar_lo_que_pregunte)."""
    hcom = hcom or fp._find_hwnd(COMPRAS_CLASS)
    if not hcom:
        return
    _focus(hcom)
    com = fp._win(hcom)
    for titulo in ("C&ancelar", "Cancelar", "&Cancelar"):
        try:
            com.child_window(title=titulo, class_name="TFlatButton").click_input()
            time.sleep(0.8)
            break
        except Exception:
            continue
    _confirmar_lo_que_pregunte(timeout=5)


def _salir_compras():
    """Cierra la ventana de Compras (patrón _salir_ajustes adaptado): intenta
    el botón '&Salir'/'Salir', responde cualquier confirmación, y si sigue
    abierta fuerza WM_CLOSE. Se llama SIEMPRE al final (tras cancelar o tras
    totalizar), cuando el documento ya no tiene cambios pendientes."""
    hcom = fp._find_hwnd(COMPRAS_CLASS)
    if not hcom:
        return
    _focus(hcom)
    com = fp._win(hcom)
    for titulo in ("&Salir", "Salir"):
        try:
            b = com.child_window(title=titulo, class_name="TFlatButton")
            r = b.rectangle()
            ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
            time.sleep(0.8)
            break
        except Exception:
            continue
    _confirmar_lo_que_pregunte(timeout=3)
    for _ in range(3):
        h = fp._find_hwnd(COMPRAS_CLASS)
        if not h:
            return
        try:
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass
        time.sleep(0.4)


def _totalizar_compra(hcom, doc_numero):
    """'&Totalizar' -> TFrmTotalOperacion -> doc_numero -> ENTER -> doc_numero
    (sin 2º ENTER, según la grabación) -> 'T&otalizar' -> cierra el
    comprobante (TfrxPreviewForm) con el patrón probado de
    flujo_stock_real._totalizar_y_guardar (ESC + WM_SYSCOMMAND SC_CLOSE +
    WM_CLOSE). Devuelve True si el flujo de totalización llegó hasta el final
    (no implica verificación en DB, eso lo hace el llamador)."""
    _focus(hcom)
    com = fp._win(hcom)
    try:
        b = com.child_window(title="&Totalizar", class_name="TFlatButton")
        r = b.rectangle()
        ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    except Exception:
        L, T, _, _ = win32gui.GetWindowRect(hcom)
        ri.click(L + TOTALIZAR_REL[0], T + TOTALIZAR_REL[1])
    time.sleep(1.0)

    htot = fp._wait_for(TOTAL_CLASS, timeout=10, desc="Total Operación")
    _focus(htot)
    tot = fp._win(htot)

    solo_digitos = "".join(ch for ch in str(doc_numero) if ch.isdigit())
    if not solo_digitos:
        raise CompraError(f"doc_numero={doc_numero!r} no tiene dígitos.")

    ri.type_number(solo_digitos)
    time.sleep(0.3)
    ri.press("ENTER")
    time.sleep(0.3)
    ri.type_number(solo_digitos)     # 2º campo, SIN ENTER adicional (fiel a la grabación)
    time.sleep(0.3)

    try:
        b = tot.child_window(title="T&otalizar", class_name="TFlatButton")
        r = b.rectangle()
        ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    except Exception:
        L, T, _, _ = win32gui.GetWindowRect(htot)
        ri.click(L + TOTAL_OPERAR_REL[0], T + TOTAL_OPERAR_REL[1])
    time.sleep(1.0)

    # cerrar el comprobante (Vista Previa), patrón probado de _totalizar_y_guardar
    t0 = time.time()
    while time.time() - t0 < 10:
        h = fp._find_hwnd(PREVIEW_CLASS)
        if h:
            time.sleep(0.5)
            try:
                win32gui.SetForegroundWindow(h)
                time.sleep(0.3)
                ri.press("ESC")
                time.sleep(0.5)
                if fp._find_hwnd(PREVIEW_CLASS):
                    win32gui.PostMessage(h, win32con.WM_SYSCOMMAND, win32con.SC_CLOSE, 0)
                    time.sleep(0.5)
                if fp._find_hwnd(PREVIEW_CLASS):
                    win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
                log.info("Comprobante (Vista Previa) de la compra cerrado.")
            except Exception:
                pass
            time.sleep(0.8)
            break
        time.sleep(0.3)
    for _ in range(3):
        h = fp._find_hwnd(PREVIEW_CLASS)
        if not h:
            break
        try:
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass
        time.sleep(0.4)

    if fp._find_hwnd(TOTAL_CLASS):
        raise CompraError("La ventana Total Operación no se cerró tras totalizar.")
    return True


# ── orquestador ──────────────────────────────────────────────────────────────
def registrar_compra(proveedor_codigo, items, doc_numero, commit=False, proveedor_nombre=None):
    """items: list[dict] {"codigo": str, "cantidad": float, "costo": float, "precio": float}
    proveedor_nombre: opcional; si viene, se verifica contra el campo del header.
    doc_numero: str numérico para los dos campos de Total Operación (relleno).
    Return: {"ok": bool, "etapa": str, "detalle": str,
             "resultados": dict[str_codigo, {"ok","detalle"}],  # verificación por item (solo commit)
             ...}
    etapas éxito: "commit" | "preview"
    etapas fallo PRE-commit (reintentables, NADA quedó a medias porque se canceló todo):
      "abrir_hybrid" | "navegacion" (clase/proveedor) | "carga_item" | "precio_item"
    etapas fallo AMBIGUAS: "totalizar" | "verificacion_db"
    REGLA DE ORO: ante CUALQUIER fallo antes de pulsar Totalizar -> Cancelar la
    compra completa + Salir de la ventana + devolver etapa pre-commit. La compra
    es TODO-O-NADA (un documento)."""
    if not items:
        return {"ok": False, "etapa": "navegacion", "detalle": "La lista de items está vacía."}

    codigos_norm = [it["codigo"].strip().lower() for it in items]
    vistos, dups = set(), set()
    for c in codigos_norm:
        (dups if c in vistos else vistos).add(c)
    if dups:
        return {"ok": False, "etapa": "navegacion",
                "detalle": f"Códigos duplicados en la compra: {sorted(dups)}. Nada se tocó."}

    # asegurar que Hybrid esté abierto y logueado (lo lanza si está cerrado)
    import abrir_hybrid
    ok, msg = abrir_hybrid.asegurar_hybrid()
    if not ok:
        return {"ok": False, "etapa": "abrir_hybrid", "detalle": msg}

    # existencia ANTES de cada ítem (para la verificación post-commit)
    existencias_antes = {}
    for it in items:
        try:
            total_antes, _ = dbex.existencia(it["codigo"])
        except Exception:
            total_antes = None
        existencias_antes[it["codigo"]] = total_antes
        log.info("Existencia DB ANTES de %s: %s", it["codigo"], total_antes)

    # navegación PRE-escritura: abrir Compras + clasificación + proveedor.
    # Cualquier fallo aquí es 100% reintentable -- nada se ha escrito todavía.
    try:
        hcom = abrir_compras()
        com = fp._win(hcom)
        fijar_clasificacion(com)
        seleccionar_proveedor(com, proveedor_codigo, proveedor_nombre)
    except (CompraError, fp.FlujoError) as e:
        _cancelar_compra(fp._find_hwnd(COMPRAS_CLASS))
        _salir_compras()
        return {"ok": False, "etapa": "navegacion",
                "detalle": f"No pude llegar a la carga de ítems (nada se tocó): {e}"}

    # ítems: cualquier fallo cancela el DOCUMENTO COMPLETO (todo-o-nada)
    for it in items:
        try:
            cargar_item(it["codigo"], it["cantidad"], it["costo"], it["precio"], commit)
        except CompraError as e:
            etapa = "precio_item" if "precio" in str(e).lower() else "carga_item"
            _cancelar_compra(fp._find_hwnd(COMPRAS_CLASS))
            _salir_compras()
            return {"ok": False, "etapa": etapa,
                    "detalle": f"Compra CANCELADA completa (todo-o-nada), fallo en {it['codigo']}: {e}"}

    if not commit:
        _cancelar_compra(fp._find_hwnd(COMPRAS_CLASS))
        _salir_compras()
        resultados = {it["codigo"]: {"ok": True, "detalle": "Verificado en pantalla y descartado."}
                      for it in items}
        return {"ok": True, "etapa": "preview",
                "detalle": f"Preview de {len(items)} ítem(s) verificado(s) en pantalla y "
                           f"DESCARTADO (sin --commit; documento cancelado completo).",
                "resultados": resultados}

    # COMMIT: Totalizar (etapa AMBIGUA si falla -- no sabemos si el documento
    # quedó a medias en el motor de Hybrid, por eso NO se cancela ni reintenta solo)
    hcom = fp._find_hwnd(COMPRAS_CLASS)
    try:
        _totalizar_compra(hcom, doc_numero)
    except (CompraError, fp.FlujoError) as e:
        return {"ok": False, "etapa": "totalizar",
                "detalle": f"No pude confirmar la totalización de la compra: {e}"}

    _salir_compras()
    time.sleep(1.5)

    # verificación DB por ítem
    resultados = {}
    todos_ok = True
    for it in items:
        codigo = it["codigo"]
        existencia_antes = existencias_antes.get(codigo)
        existencia_esperada = (existencia_antes + float(it["cantidad"])
                               if existencia_antes is not None else None)
        existencia_despues, _ = dbex.existencia(codigo)
        costo_despues = hpw._db_costo_usd(codigo)
        precio_despues = hpw._db_precio_usd(codigo)

        fallos = []
        if existencia_esperada is None:
            fallos.append("existencia ANTES no legible, no se pudo verificar el delta")
        elif abs(existencia_despues - existencia_esperada) > TOL_EXISTENCIA:
            fallos.append(f"existencia quedó en {existencia_despues}, esperaba {existencia_esperada}")

        if costo_despues is None:
            fallos.append("costo no legible en DB")
        elif abs(costo_despues - float(it["costo"])) > TOL_COSTO_PRECIO:
            fallos.append(f"costo quedó en {costo_despues}, esperaba {it['costo']}")

        if precio_despues is None:
            fallos.append("precio no legible en DB")
        elif abs(precio_despues - float(it["precio"])) > TOL_COSTO_PRECIO:
            fallos.append(f"precio quedó en {precio_despues}, esperaba {it['precio']}")

        if fallos:
            todos_ok = False
            detalle = "¡ALERTA! " + "; ".join(fallos)
            log.error("Verificación %s: %s", codigo, detalle)
            resultados[codigo] = {"ok": False, "detalle": detalle}
        else:
            detalle = (f"VERIFICADO en DB: existencia={existencia_despues} "
                      f"costo={costo_despues} precio={precio_despues}")
            log.info("Verificación %s: %s", codigo, detalle)
            resultados[codigo] = {"ok": True, "detalle": detalle}

    etapa = "commit" if todos_ok else "verificacion_db"
    detalle_global = (f"Compra totalizada (doc={doc_numero}) con {len(items)} ítem(s). "
                      f"{'Todos verificados en DB.' if todos_ok else 'ALERTA: hay ítems que no cuadran, revisar resultados.'}")
    return {"ok": todos_ok, "etapa": etapa, "detalle": detalle_global, "resultados": resultados}


# ── CLI ──────────────────────────────────────────────────────────────────────
def _parse_items(spec):
    """'COD:cant:costo:precio,COD2:...' -> list[dict]."""
    items = []
    for par in spec.split(","):
        partes = par.split(":")
        if len(partes) != 4:
            raise ValueError(f"Ítem inválido: {par!r} (formato codigo:cantidad:costo:precio)")
        codigo, cantidad, costo, precio = partes
        codigo = codigo.strip()
        if not codigo:
            raise ValueError(f"Ítem inválido: {par!r} (código vacío)")
        items.append({
            "codigo": codigo,
            "cantidad": float(cantidad),
            "costo": float(costo),
            "precio": float(precio),
        })
    return items


if __name__ == "__main__":
    _raw = sys.argv[1:]
    _flags_con_valor = ("--items", "--doc")
    args = []
    i = 0
    while i < len(_raw):
        tok = _raw[i]
        if tok in _flags_con_valor:
            i += 2
            continue
        if not tok.startswith("--"):
            args.append(tok)
        i += 1

    if len(args) < 1 or "--items" not in _raw or "--doc" not in _raw:
        print("Uso: python flujo_compra_real.py <proveedor_codigo> "
              "--items \"COD:cant:costo:precio,COD2:...\" --doc 123456 [--commit]")
        sys.exit(1)

    proveedor_codigo = args[0]
    items_spec = _raw[_raw.index("--items") + 1]
    doc_numero = _raw[_raw.index("--doc") + 1]

    try:
        items = _parse_items(items_spec)
    except ValueError as e:
        print(f"Error parseando --items: {e}")
        sys.exit(1)

    res = registrar_compra(proveedor_codigo, items, doc_numero, commit="--commit" in _raw)
    print("\n=== RESULTADO ===")
    for k, v in res.items():
        if k == "resultados":
            print("  resultados:")
            for codigo, r in v.items():
                print(f"    {codigo}: {r}")
        else:
            print(f"  {k}: {v}")
