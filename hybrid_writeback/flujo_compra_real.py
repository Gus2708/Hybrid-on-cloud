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
     Estas lecturas van contra la unidad de red H:, que se cae de a ratos: si no
     responde se reintenta (ver _leer_item_db) y, si aun así no hay forma, se
     devuelve la etapa "verificacion_indisponible" — la compra YA está
     registrada, solo no se pudo confirmar. NO es lo mismo que un fallo.

ALTA DE PRODUCTO NUEVO (crear_producto): cuando un ítem de la compra trae
es_nuevo=True, ANTES de cargarlo en la grilla de Compras hay que darlo de alta
en la Ficha de Inventario (TTConfigForm) — Hybrid no permite comprar un código
que no existe en el maestro. Secuencia (ver FLUJO-NUEVO-PRODUCTO-CAPTURADO-v2.log,
esqueleto con ruido, y los datos de inspección en vivo del 2026-07-11 que son la
fuente de verdad real):
  1. abrir_ficha() (reutilizado de flujo_precio_real).
  2. Botón 'Incluir' (owner-drawn, IZQUIERDA de Modificar) -> nuevo registro vacío.
  3. Header de la Ficha en modo alta: 3 THybridEdit (código/referencia/descripción),
     localizados por franja de posición relativa con _campos_ficha() (mismo patrón
     que _leer_header_compras). Se escriben con clic real + type_code/type_text y
     se VERIFICAN leyendo window_text().
  4. Costos y Precios (fpr.abrir_costos_precios) -> escribir COSTO primero
     (_escribir_costo_alta, localización POR POSICIÓN porque no hay costo previo
     en DBISAM para localizar por valor como hace fpr.escribir_costo) y luego
     PRECIO (fpr.escribir_precio, campo con-impuesto) -- mismo orden costo->precio
     que set_precio_costo, por el acople documentado en flujo_precio_real.
  5. preview: Salir de Costos y Precios + Cancelar/descartar la Ficha SIN guardar
     (nada queda creado). commit: Aceptar+Salir de Costos y Precios + Guardar de
     la Ficha (fpr._guardar_ficha) + verificación contra DBISAM.
  ASIMETRÍA preview/commit en registrar_compra: en preview el alta NO se guarda,
  así que el código creado no existe todavía para cargar_item -- los ítems
  es_nuevo se SALTAN de la carga a la grilla en preview (solo se valida el alta
  en pantalla); en commit sí se crean de verdad y LUEGO se compran normalmente.

SEGURIDAD: preview por defecto (llena y verifica en pantalla, NO guarda nada);
--commit aplica de verdad y verifica contra la base. Todo-o-nada: la compra es
UN documento, no una serie de cambios independientes -- ante cualquier fallo
PRE-Totalizar se cancela el documento completo (incluye fallos en el alta de
productos nuevos, que corre ANTES de tocar la grilla de Compras).

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
import colisiones                             # clave de búsqueda segura (código vs referencia)
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
ITEM_GRID_REL = (72, 325)          # celda Código de la grilla (TAdvStringGrid), 1er ítem
GRID_EDIT_CLASSES = ("THybridEdit", "THybridEditNumber")   # editores de la fila activa

# ── ALTA DE PRODUCTO NUEVO (crear_producto) ─────────────────────────────────
# Barra superior de la Ficha de Inventario (owner-drawn, sin título): botones
# Incluir · Modificar · Cancelar · Guardar · Borrar · Salir. Coordenadas de los
# CENTROS confirmadas por captura de pantalla en vivo (2026-07-12); el clic va
# sobre el texto/icono (y≈62). Referencias conocidas: fpr.MODIFICAR_REL=(122,62),
# fpr.GUARDAR_REL=(240,60).
INCLUIR_REL = (42, 62)     # 1er botón (nuevo registro)
CANCELAR_REL = (175, 62)   # 3er botón (descarta el alta sin guardar)

TOL_ALTA = 0.02   # misma tolerancia que TOL_COSTO_PRECIO, usada en la verificación de alta

# Reintentos de LECTURA de la DBISAM en la verificación post-Totalizar. La
# unidad H: es un share de red que se cae de a ratos y vuelve sola en menos de
# un minuto (visto el 2026-08-13 con la compra 35: se cayó a mitad del bucle y
# volvió 10 min después). Reintentar acá evita reportar como fallo una compra
# que sí se registró.
REINTENTOS_LECTURA_DB = 3
ESPERA_LECTURA_DB = 20    # segundos entre reintentos


class CompraError(Exception):
    pass


class VerificacionIndisponible(Exception):
    """La DBISAM no se pudo LEER para verificar (típicamente la unidad H: caída).

    No es un fallo de la compra: cuando esto salta después de Totalizar, el
    documento YA está registrado en HybridLite y lo único que falta es
    confirmarlo. Se distingue del resto de errores justamente para que el
    listener no lo trate como "pudo quedar a medias" ni lo reencole."""


def _leer_item_db(codigo):
    """(existencia, costo, precio) de un ítem en la DBISAM, con reintentos.

    Las tres lecturas abren archivos en la unidad de red H:. Si el share se cae
    a mitad del bucle de verificación, pydbisam levanta OSError
    (FileNotFoundError) — un error de LECTURA, no de la compra. Se reintenta un
    par de veces (la unidad suele volver sola) y, si aun así no hay forma, se
    traduce a VerificacionIndisponible para que el llamador pueda decir "la
    compra sí quedó, no la reencoles" en vez de propagar un error crudo
    indistinguible de un fallo real."""
    for intento in range(1, REINTENTOS_LECTURA_DB + 1):
        try:
            existencia, _ = dbex.existencia(codigo)
            return existencia, hpw._db_costo_usd(codigo), hpw._db_precio_usd(codigo)
        except OSError as e:
            if intento == REINTENTOS_LECTURA_DB:
                raise VerificacionIndisponible(
                    f"la DBISAM no responde tras {REINTENTOS_LECTURA_DB} intentos ({e!r}); "
                    f"probablemente se cayó la unidad H:") from e
            log.warning("Lectura DB de %s falló (%r); reintento %s/%s en %ss.",
                        codigo, e, intento + 1, REINTENTOS_LECTURA_DB, ESPERA_LECTURA_DB)
            time.sleep(ESPERA_LECTURA_DB)


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
    """Responde afirmativamente a CUALQUIER diálogo de confirmación/alerta que
    aparezca (TFConfirmacion o TMessageForm), probando una lista amplia de
    títulos de botón. Cubre dos casos del flujo de compra:
      - 'Cancelar' en Compras pregunta si se desea cancelar -> responder SÍ (a
        diferencia de flujo_stock_real._cancelar, que responde NO).
      - Alerta 'el producto llegó al mínimo' al Totalizar/agregar un producto
        (típico de productos con existencia baja/nueva): solo hay que darle
        OK/Aceptar y CONTINUAR (confirmado por el dueño 2026-07-12). Por eso se
        incluyen 'Aceptar'/'OK'/'Continuar' en la lista."""
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
        # ORDEN IMPORTANTE: '&Ok' PRIMERO. La alerta 'producto llegó al mínimo'
        # (TFConfirmacion, confirmada en vivo 2026-07-12) tiene 3 botones
        # &Ok/&NO/&SI y el que continúa el flujo es '&Ok' (k minúscula, título
        # exacto). Los diálogos de cancelar/confirmar totalizar solo tienen
        # &SI/&NO (sin &Ok), así que ahí se cae a '&SI'.
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


# ── ALTA DE PRODUCTO NUEVO (crear_producto) ─────────────────────────────────
def _campos_ficha(hf):
    """Localiza los 3 THybridEdit del header de la Ficha en modo alta (código /
    referencia / descripción) por franja de posición relativa a la ventana,
    igual patrón que _leer_header_compras. Datos de inspección en vivo
    (2026-07-11, confirmados por el orquestador):
        CÓDIGO:      rel_top≈150, rel_left≈44,  ancho≈121 (fila superior izq.)
        REFERENCIA:  rel_top≈150, rel_left≈200, ancho≈270 (fila superior der.)
        DESCRIPCIÓN: rel_top≈190, rel_left≈44,  ancho≈426 (fila de abajo, ancha)
    Devuelve dict {"codigo": ctrl|None, "referencia": ctrl|None, "descripcion": ctrl|None}
    (el control pywinauto, no su texto -- el llamador clickea/teclea/lee cada uno)."""
    res = {"codigo": None, "referencia": None, "descripcion": None}
    if not hf:
        return res
    fi = fp._win(hf)
    L, T, _, _ = win32gui.GetWindowRect(hf)
    for c in fi.descendants(class_name="THybridEdit"):
        r = c.rectangle()
        rel_top = r.top - T
        rel_left = r.left - L
        if 130 <= rel_top < 170:
            if rel_left < 170:
                res["codigo"] = c
            else:
                res["referencia"] = c
        elif 170 <= rel_top < 210:
            res["descripcion"] = c
    return res


def _escribir_campo_ficha(campo, valor, lento=False):
    """Clic real en el centro del campo + borrado duro + teclear (type_code si
    `lento`, igual que la grilla de Compras; type_text en caso contrario).
    Devuelve el texto leído tras teclear (window_text), para que el llamador
    verifique."""
    r = campo.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    time.sleep(0.1)
    try:
        campo.set_focus()
    except Exception:
        pass
    time.sleep(0.08)
    ri.clear_hard()
    if lento:
        ri.type_code(valor)
    else:
        ri.type_text(valor)
    time.sleep(0.15)
    return (campo.window_text() or "").strip()


def _escribir_costo_alta(nuevo_costo):
    """Teclea el COSTO USD del diálogo TFHCostosPrecios para un producto NUEVO
    (sin costo previo en DBISAM -- a diferencia de fpr.escribir_costo, que
    localiza el campo por VALOR contra el costo actual leído de la base, acá
    eso no existe: el producto todavía no tiene fila en la DBISAM).

    # CALIBRAR EN VIVO: el campo de costo USD del groupbox 'Costos en moneda
    # referencial'. Primer intento: localizar el TGroupBox por título
    # ('Costos en moneda referencial', confirmado en los dumps de calibración
    # calib_TFHCostosPrecios_*.txt) y tomar su único THybridEditNumber hijo
    # directo con MAYOR `top` (el campo 'Costo Actual' bajo el caption owner-
    # drawn 'Costos Moneda Referencial' -- el groupbox también contiene otros
    # campos del panel, de ahí "mayor top" como heurística de POSICIÓN, no de
    # valor). TODO: el orquestador debe confirmar en vivo cuál control es
    # exactamente (podría haber más de un candidato); si hay ambigüedad, esta
    # función debe fallar (PrecioError) en vez de arriesgar escribir en el
    # campo equivocado (mismo criterio de seguridad que fpr.escribir_costo)."""
    hd = fp._find_hwnd(fp.PRECIOS_CLASS)
    if not hd:
        raise fpr.PrecioError("El diálogo Costos y Precios no está abierto para escribir el costo de alta.")
    fpr._focus(hd)
    dlg = fp._win(hd)

    try:
        grupo = dlg.child_window(title="Costos en moneda referencial", class_name="TGroupBox")
        candidatos = sorted(
            grupo.descendants(class_name="THybridEditNumber"),
            key=lambda c: c.rectangle().top,
        )
    except Exception as e:
        raise fpr.PrecioError(
            f"No pude localizar el groupbox 'Costos en moneda referencial' "
            f"para el costo de alta: {e}. NO se escribe nada.")

    if not candidatos:
        raise fpr.PrecioError(
            "El groupbox 'Costos en moneda referencial' no tiene ningún "
            "THybridEditNumber hijo (calibración pendiente). NO se escribe nada.")
    # heurística POR POSICIÓN (# CALIBRAR EN VIVO): el de mayor `top` es el
    # candidato a 'Costo Actual' bajo 'Costos Moneda Referencial'.
    campo = candidatos[-1]
    log.info("Campo de costo de ALTA localizado por posición (mayor top del "
             "groupbox 'Costos en moneda referencial'): %s", campo.rectangle())

    r = campo.rectangle()
    ri.click((r.left + r.right) // 2, r.bottom - 4)
    time.sleep(0.2)
    try:
        campo.set_focus()
    except Exception:
        pass
    time.sleep(0.2)
    ri.clear_hard()
    if (campo.window_text() or "").strip() not in ("", "0", "0.00", "0,00"):
        ri.clear_hard()
    ri.type_number(f"{float(nuevo_costo):.2f}")
    time.sleep(0.2)
    ri.press("ENTER")
    time.sleep(0.6)

    leido = hpw._num(campo.window_text())
    log.info("Costo de ALTA en pantalla tras teclear: %s (target=%s)", leido, nuevo_costo)
    if leido is None or abs(leido - float(nuevo_costo)) > TOL_ALTA:
        raise fpr.PrecioError(f"El costo de alta en pantalla no cuadra (quedó {leido}, "
                              f"esperado {nuevo_costo}). NO se compromete nada.")
    return {"costo": leido}


def _cancelar_ficha_alta(hf):
    """Descarta el alta de producto SIN guardar nada (preview, o fallo antes de
    Guardar): botón 'Cancelar' de la barra de la Ficha por coordenada (owner-
    drawn, sin grabación de referencia -- ver CANCELAR_REL). Responde 'No' si
    pregunta si desea guardar (a diferencia de _cancelar_compra, que responde
    SÍ -- acá cancelar un alta NUEVA no debe guardar nada, mismo criterio que
    flujo_stock_real._cancelar)."""
    hf = hf or fp._find_hwnd(fp.FICHA_CLASS)
    if not hf:
        return
    fpr._focus(hf)
    L, T, _, _ = win32gui.GetWindowRect(hf)
    ri.click(L + CANCELAR_REL[0], T + CANCELAR_REL[1])
    time.sleep(0.6)
    # responder 'No' si pregunta (no queremos guardar el alta descartada)
    t0 = time.time()
    while time.time() - t0 < 3:
        h = fp._find_hwnd(CONF_CLASS) or fp._find_hwnd("TMessageForm")
        if not h:
            break
        m = fp._win(h)
        for titulo in ("&NO", "No", "&No"):
            try:
                b = m.child_window(title=titulo)
                r = b.rectangle()
                ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                break
            except Exception:
                continue
        time.sleep(0.4)


def _guardar_ficha_alta():
    """Guarda la Ficha en modo ALTA (nuevo producto) y cancela el registro vacío sobrante.

    En HybridLite, al dar de alta un producto nuevo ('Incluir' -> llenar campos -> 'Guardar'):
    1. 'Guardar' persiste el nuevo producto en DBISAM de inmediato sin diálogo de confirmación.
       Reintentar el clic a ciegas (como hace _guardar_ficha de modificación) vuelve a pulsar
       'Guardar' sobre un registro nuevo en blanco, disparando el modal:
       'Information: Existen campos obligatorios no procesados'.
    2. Por tanto, se pulsa Guardar EXACTAMENTE UNA VEZ.
    3. Si aparece algún diálogo de confirmación o aviso de Hybrid, se responde afirmativamente.
    4. Tras guardar, HybridLite permanece en 'Modo Inserción' con campos vacíos.
       Para dejar la Ficha limpia y salir de 'Modo Inserción', se pulsa 'Cancelar' (CANCELAR_REL),
       descartando el registro en blanco sin afectar al producto ya guardado en DBISAM.
    5. Finalmente se cierra la Ficha de Inventario con fsr._cerrar_ficha_si_abierta().
    """
    hf = fp._find_hwnd(fp.FICHA_CLASS)
    if not hf:
        raise CompraError("No encontré la Ficha de Inventario para guardar el alta.")
    fpr._focus(hf)
    L, T, _, _ = win32gui.GetWindowRect(hf)

    # 1. Pulsar Guardar EXACTAMENTE UNA VEZ
    ri.click(L + fpr.GUARDAR_REL[0], T + fpr.GUARDAR_REL[1])
    time.sleep(0.4)

    # 2. Si aparece algún diálogo de confirmación o aviso de Hybrid, responder
    t0 = time.time()
    while time.time() - t0 < 1.2:
        h = fp._find_hwnd("TMessageForm") or fp._find_hwnd(CONF_CLASS)
        if not h:
            break
        fpr._focus(h)
        for titulo in ("&Yes", "&Sí", "Sí", "Yes", "Aceptar", "&Aceptar", "OK", "&OK", "Ok", "&Ok", "Continuar"):
            try:
                b = fp._win(h).child_window(title=titulo)
                r = b.rectangle()
                ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                log.info("Diálogo post-guardar '%s' pulsado.", titulo)
                time.sleep(0.15)
                break
            except Exception:
                continue
        time.sleep(0.05)

    # 3. Cancelar el registro vacío sobrante para salir de 'Modo Inserción'
    ri.click(L + CANCELAR_REL[0], T + CANCELAR_REL[1])
    time.sleep(0.4)
    t0 = time.time()
    while time.time() - t0 < 1.0:
        h = fp._find_hwnd(CONF_CLASS) or fp._find_hwnd("TMessageForm")
        if not h:
            break
        m = fp._win(h)
        for titulo in ("&NO", "No", "&No", "&SI", "SI", "&Sí", "Sí", "OK", "&OK"):
            try:
                b = m.child_window(title=titulo)
                r = b.rectangle()
                ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                time.sleep(0.15)
                break
            except Exception:
                continue
        time.sleep(0.05)

    # 4. Cerrar la Ficha de Inventario para dejar el escritorio libre
    fsr._cerrar_ficha_si_abierta()


def crear_producto(codigo, descripcion, referencia, costo, precio, commit=False):
    """Da de alta un producto NUEVO en la Ficha de Inventario, para ítems de
    compra con es_nuevo=True. Return: {"ok": bool, "etapa": str, "detalle": str}.

    Etapas de fallo:
      "abrir_ficha"  -- no se pudo abrir/localizar la Ficha (reintentable, nada tocado)
      "campos"       -- código/descripción no quedaron en pantalla (reintentable,
                        nada guardado -- se cancela el alta antes de salir)
      "costos_precios" -- fallo escribiendo costo/precio (reintentable, se
                        descarta con 'Salir' antes de salir, nada guardado)
      "guardar" | "verificacion_db" -- AMBIGUAS: el Guardar pudo haberse
                        aplicado ya en HybridLite aunque la verificación falle.

    Etapas de éxito: "preview" (verificado en pantalla, NO guardado) | "commit"
    (guardado y VERIFICADO contra DBISAM)."""
    codigo = (codigo or "").strip()
    descripcion = (descripcion or "").strip()
    referencia = (referencia or "").strip() if referencia else ""
    if not codigo or not descripcion:
        return {"ok": False, "etapa": "campos",
                "detalle": "código y descripción son obligatorios para el alta (nada se tocó)."}

    try:
        hf = fpr.abrir_ficha()
    except (fpr.PrecioError, fp.FlujoError) as e:
        return {"ok": False, "etapa": "abrir_ficha",
                "detalle": f"No pude abrir la Ficha de Inventario para el alta de {codigo}: {e}"}

    # botón 'Incluir' (nuevo registro, owner-drawn, IZQUIERDA de Modificar)
    fpr._focus(hf)
    L, T, _, _ = win32gui.GetWindowRect(hf)
    ri.click(L + INCLUIR_REL[0], T + INCLUIR_REL[1])
    time.sleep(0.5)

    # localizar y llenar los 3 campos del header en modo alta
    campos = _campos_ficha(fp._find_hwnd(fp.FICHA_CLASS))
    if campos["codigo"] is None or campos["descripcion"] is None:
        _cancelar_ficha_alta(fp._find_hwnd(fp.FICHA_CLASS))
        return {"ok": False, "etapa": "campos",
                "detalle": f"No pude localizar los campos código/descripción del alta de "
                           f"{codigo} (¿'Incluir' no abrió el modo alta? -- CALIBRAR "
                           f"INCLUIR_REL). Nada se tocó."}

    codigo_ui = _escribir_campo_ficha(campos["codigo"], codigo, lento=True)   # type_code, como la grilla
    if codigo_ui != codigo:
        _cancelar_ficha_alta(fp._find_hwnd(fp.FICHA_CLASS))
        return {"ok": False, "etapa": "campos",
                "detalle": f"El código quedó en pantalla como {codigo_ui!r}, no {codigo!r}. "
                           f"Nada se tocó."}

    if referencia and campos["referencia"] is not None:
        referencia_ui = _escribir_campo_ficha(campos["referencia"], referencia, lento=False)
        if referencia_ui != referencia:
            log.warning("La referencia quedó en pantalla como %r, no %r (no bloqueante).",
                        referencia_ui, referencia)

    descripcion_ui = _escribir_campo_ficha(campos["descripcion"], descripcion, lento=False)
    if descripcion_ui != descripcion:
        _cancelar_ficha_alta(fp._find_hwnd(fp.FICHA_CLASS))
        return {"ok": False, "etapa": "campos",
                "detalle": f"La descripción quedó en pantalla como {descripcion_ui!r}, no "
                           f"{descripcion!r}. Nada se tocó."}
    log.info("Campos del alta de %s VERIFICADOS en pantalla (descripcion=%r, referencia=%r).",
             codigo, descripcion_ui, referencia)

    # Costos y Precios: costo PRIMERO (acople costo->precio, ver flujo_precio_real), luego precio
    try:
        fpr.abrir_costos_precios()
    except fp.FlujoError as e:
        _cancelar_ficha_alta(fp._find_hwnd(fp.FICHA_CLASS))
        return {"ok": False, "etapa": "costos_precios",
                "detalle": f"No se abrió Costos y Precios para el alta de {codigo}: {e}"}

    try:
        _escribir_costo_alta(costo)
        fpr.escribir_precio(float(precio), fpr.iva_producto(codigo))
    except fpr.PrecioError as e:
        fpr._click_boton_dialogo("Salir")        # descarta el diálogo, nada guardado
        _cancelar_ficha_alta(fp._find_hwnd(fp.FICHA_CLASS))
        return {"ok": False, "etapa": "costos_precios",
                "detalle": f"Costo/precio del alta de {codigo} no cuadraron en pantalla: {e}"}

    if not commit:
        fpr._click_boton_dialogo("Salir")        # descarta Costos y Precios
        _cancelar_ficha_alta(fp._find_hwnd(fp.FICHA_CLASS))   # descarta la Ficha, SIN guardar
        fsr._cerrar_ficha_si_abierta()
        return {"ok": True, "etapa": "preview",
                "detalle": f"Alta de {codigo} ({descripcion}) verificada en pantalla "
                           f"(costo={costo}, precio={precio}) y DESCARTADA (sin --commit; "
                           f"el producto NO quedó creado, así que este ítem no se compra en preview)."}

    # COMMIT: Aceptar+Salir de Costos y Precios, Guardar la Ficha, verificar en DBISAM
    if not fpr._click_boton_dialogo("Aceptar"):
        return {"ok": False, "etapa": "costos_precios",
                "detalle": f"No pude pulsar 'Aceptar' en Costos y Precios para el alta de {codigo}."}
    if fp._find_hwnd(fp.PRECIOS_CLASS):
        fpr._click_boton_dialogo("Salir")

    _guardar_ficha_alta()
    time.sleep(0.5)

    try:
        existencia_db, costo_db, precio_db = _leer_item_db(codigo)
    except VerificacionIndisponible as e:
        return {"ok": False, "etapa": "verificacion_indisponible",
                "detalle": f"Alta de {codigo}: el Guardar ya se pulsó (el producto pudo quedar "
                           f"creado) pero no se pudo confirmar contra la DBISAM: {e}."}
    log.info("Verificación DB del alta de %s: existencia=%s costo=%s precio=%s",
             codigo, existencia_db, costo_db, precio_db)

    fallos = []
    if existencia_db is None:
        fallos.append("el producto no aparece en la DBISAM tras Guardar (¿no se creó?)")
    if costo_db is None or abs(costo_db - float(costo)) > TOL_ALTA:
        fallos.append(f"costo en DB quedó en {costo_db}, esperaba {costo}")
    if precio_db is None or abs(precio_db - float(precio)) > TOL_ALTA:
        fallos.append(f"precio en DB quedó en {precio_db}, esperaba {precio}")

    if fallos:
        return {"ok": False, "etapa": "verificacion_db",
                "detalle": f"¡ALERTA! Alta de {codigo}: " + "; ".join(fallos)}
    return {"ok": True, "etapa": "commit",
            "detalle": f"Producto {codigo} ({descripcion}) dado de alta y VERIFICADO en DB: "
                       f"existencia={existencia_db} costo={costo_db} precio={precio_db}."}


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
    time.sleep(0.05)

    btn = None
    try:
        cand = main.child_window(title="Compra de mercancías", class_name="TAdvGlassButton")
        if cand.exists(timeout=0) and cand.is_visible():
            btn = cand
    except Exception:
        pass

    if btn is None:
        # Menú lateral Compras
        L, T, _, _ = win32gui.GetWindowRect(hmain)
        ri.click(L + MENU_COMPRAS_REL[0], T + MENU_COMPRAS_REL[1])
        t0 = time.time()
        while time.time() - t0 < 2.0:
            try:
                cand = main.child_window(title="Compra de mercancías", class_name="TAdvGlassButton")
                if cand.exists(timeout=0) and cand.is_visible():
                    btn = cand
                    break
            except Exception:
                pass
            time.sleep(0.04)
        if btn is None:
            btn = main.child_window(title="Compra de mercancías", class_name="TAdvGlassButton")
            btn.wait("exists visible", timeout=1.5)

    r = btn.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)

    t0 = time.time()
    while time.time() - t0 < 10:
        ha = fp._find_hwnd(COMPRAS_CLASS)
        if ha:
            time.sleep(0.1)
            return ha
        time.sleep(0.04)
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
    time.sleep(0.4)

    if fp._find_hwnd(fp.BUSQ_CLASS) is not None:
        # fallback: doble-clic en la primera fila del grid (patrón cargar_producto)
        busq = fp._win(fp._find_hwnd(fp.BUSQ_CLASS))
        try:
            grid = busq.child_window(class_name="TDBGrid")
            gr = grid.rectangle()
            ri.click(gr.left + 60, gr.top + 34, double=True)
            time.sleep(0.5)
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
    fpr._esperar_desocupada(hbusq, que="la lista de proveedores")
    _focus(hbusq)

    ed = busq.child_window(class_name="THybridEdit", found_index=0)
    r = ed.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    time.sleep(0.05)
    ri.clear_field()
    ri.type_text(proveedor_codigo)
    time.sleep(0.04)
    ri.press("ENTER")                                    # ejecuta la búsqueda

    fpr._esperar_desocupada(hbusq, que="el filtro de proveedores")
    filtrada = fpr._esperar_lista_filtrada(busq, timeout=60.0)
    log.info("Busqueda De Proveedores filtrada para %s: %s (scrollbar)", proveedor_codigo, filtrada)

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
def _fila_activa(hcom):
    """Inspecciona los controles de edición de la fila activa en la grilla de Compras.
    Devuelve (top_px, {"codigo": str, "descripcion": str, "cantidad": str, "costo": str}).
    Si la fila no tiene editores visibles (no está en edición), devuelve (None, {})."""
    if not hcom:
        return None, {}
    try:
        com = fp._win(hcom)
        grid = com.child_window(class_name="TAdvStringGrid", found_index=0)
        gr = grid.rectangle()
        ctrls = []
        for c in com.descendants():
            cls = c.class_name()
            if cls not in GRID_EDIT_CLASSES:
                continue
            r = c.rectangle()
            if gr.left <= r.left < gr.right and gr.top <= r.top < gr.bottom:
                ctrls.append((r.top, r.left, cls, c))
    except Exception as e:
        log.debug("No pude inspeccionar la grilla de Compras: %r", e)
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
        "costo":       txt(nums[1]) if len(nums) >= 2 else "",
    }
    return top, campos


def _verificar_producto_cargado(hcom, codigo, clave_busqueda=None):
    """Confirma EN PANTALLA que el código llegó a la grilla de Compras y que
    HybridLite resolvió el producto correcto, antes de seguir tecleando cantidad y costo.
    Acepta el código original o la clave de búsqueda (referencia/código de barras)."""
    _, campos = _fila_activa(hcom)
    if not campos:
        log.warning("No pude leer la fila en curso del ítem %s: queda sin verificar en pantalla.", codigo)
        return

    leido = campos.get("codigo", "").strip().upper()
    esperados = {str(codigo).strip().upper()}
    if clave_busqueda:
        esperados.add(str(clave_busqueda).strip().upper())
    if leido not in esperados:
        raise CompraError(
            f"El código {codigo} no llegó a la grilla de Compras (la celda quedó en {leido!r}). "
            f"El foco no estaba en la grilla o se cargó un producto incorrecto."
        )
    if not campos.get("descripcion"):
        raise CompraError(
            f"El ítem {codigo} quedó sin descripción en la grilla: HybridLite no resolvió el producto."
        )


def cargar_item(codigo, cantidad, costo, precio, commit, es_primero=False,
                clave_busqueda=None):
    """Teclea un ítem completo en la grilla de Compras:
        (solo el 1er ítem) clic en la celda Código de la grilla TAdvStringGrid
        código -> ENTER (carga y verifica en pantalla)
        cantidad -> ENTER
        costo (numérico) + Shift+4 ('$') -> ENTER -> abre TFHCostosPrecios (o ítem at-min)
        precio (escribir_precio) -> Aceptar+Salir (commit) o solo Salir (preview)
    Lanza CompraError ante cualquier desviación; el llamador cancela TODO el
    documento (política todo-o-nada)."""
    a_teclear = clave_busqueda or codigo
    hcom = fp._find_hwnd(COMPRAS_CLASS)
    if es_primero:
        _focus(hcom)
        try:
            com = fp._win(hcom)
            grid = com.child_window(class_name="TAdvStringGrid", found_index=0)
            gr = grid.rectangle()
            ri.click(gr.left + 60, gr.top + 34)
        except Exception:
            L, T, _, _ = win32gui.GetWindowRect(hcom)
            ri.click(L + ITEM_GRID_REL[0], T + ITEM_GRID_REL[1])
        time.sleep(0.25)

    # Un ítem que quedó en/bajo su mínimo dispara una alerta 'llegó al mínimo'
    # de forma ASÍNCRONA/TARDÍA, que puede aparecer ya empezado el siguiente
    # ítem. Drenarla ANTES de teclear este código evita que la del ítem previo
    # se cuele en la bifurcación de éste (confirmado en vivo 2026-07-12). Solo
    # tras drenarla se re-enfoca (la alerta roba el foreground); si no hay
    # alerta, se respeta el cursor que dejó auto-posicionado el ítem anterior.
    if fp._find_hwnd(CONF_CLASS) or fp._find_hwnd("TMessageForm"):
        _confirmar_lo_que_pregunte(timeout=2)
        _focus(hcom)

    if a_teclear != codigo:
        log.info("Ítem %s: se teclea %r para esquivar la colisión código/referencia.",
                 codigo, a_teclear)
    ri.type_code(a_teclear)
    time.sleep(0.15)
    ri.press("ENTER")
    time.sleep(0.6)

    # VERIFICACIÓN EN PANTALLA: confirmar que el producto cargado es el pedido
    _verificar_producto_cargado(hcom, codigo, clave_busqueda=a_teclear)

    ri.type_number(f"{float(cantidad):g}")
    time.sleep(0.15)
    ri.press("ENTER")
    time.sleep(0.3)

    ri.type_number(f"{float(costo):.2f}")
    time.sleep(0.08)
    ri.press_shift("4")            # '$' (layout latam) que cierra la columna de costo
    time.sleep(0.08)
    ri.press("ENTER")
    time.sleep(0.3)

    # Tras confirmar el costo, HybridLite hace UNA de dos cosas (bifurcación,
    # confirmada por el dueño 2026-07-12):
    #   (a) el producto está EN/BAJO su mínimo -> alerta 'llegó al mínimo'
    #       (TFConfirmacion). Se le da Ok y el producto YA QUEDA agregado a la
    #       grilla con el costo tecleado; Costos y Precios NO se abre. El precio
    #       queda por acople al costo. Se pasa directo al siguiente ítem.
    #   (b) producto normal -> se abre Costos y Precios (TFHCostosPrecios) para
    #       teclear el precio.
    precios_h = None
    t0 = time.time()
    while time.time() - t0 < 2.5:
        precios_h = fp._find_hwnd(fp.PRECIOS_CLASS)
        if precios_h:
            break                                   # caso (b): abrió el diálogo
        if fp._find_hwnd(CONF_CLASS) or fp._find_hwnd("TMessageForm"):
            _confirmar_lo_que_pregunte(timeout=1.5, inmediato_si_no_hay=True)
            _focus(hcom)
        time.sleep(0.05)

    if not precios_h:
        # caso (a): nunca abrió Costos y Precios -> ítem at-min agregado directo.
        log.info("Ítem %s en el mínimo: agregado directo (costo=%s), Costos y "
                 "Precios NO abre; se continúa (commit=%s).",
                 codigo, costo, commit)
        return

    try:
        fpr.escribir_precio(float(precio), fpr.iva_producto(codigo))
    except fpr.PrecioError as e:
        fpr._click_boton_dialogo("Salir")   # descarta el ítem, nada queda a medias
        raise CompraError(f"El precio del ítem {codigo} no cuadró en pantalla: {e}")

    # OJO (regresión 2026-07-30): 'Aceptar' CONFIRMA el precio pero NO cierra el
    # diálogo — el que cierra es 'Salir'. Son dos pasos, no uno; por eso el
    # 'Aceptar' va sin esperar_cierre (si no, reintenta un cierre que nunca llega
    # y aborta la compra en el primer ítem).
    if commit and not fpr._click_boton_dialogo("Aceptar"):
        raise CompraError(f"No pude pulsar 'Aceptar' en Costos y Precios para {codigo}.")

    # cierre (y, en preview, descarte del ítem). esperar_cierre=True reintenta si
    # una ventana intrusa se robó el foco justo en el clic.
    if not fpr._click_boton_dialogo("Salir", esperar_cierre=True):
        raise CompraError(f"El diálogo Costos y Precios no se cerró para el ítem {codigo}.")

    # Drenar la alerta TARDÍA 'llegó al mínimo' que este ítem (si quedó at-min)
    # dispara tras agregarse, para que no se cuele en el siguiente ítem.
    _confirmar_lo_que_pregunte(timeout=1.2)

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
    # Pulsar '&Totalizar' con REINTENTO: tras cargar los ítems la ventana de
    # Compras puede no estar realmente al frente cuando cae el clic real y
    # Total Operación no abre (mismo patrón que abrir_costos_precios,
    # confirmado en vivo 2026-07-12). Re-enfoca y re-clickea hasta 3 veces.
    htot = None
    for intento in range(1, 4):
        _focus(hcom)
        time.sleep(0.4)
        com = fp._win(hcom)
        try:
            b = com.child_window(title="&Totalizar", class_name="TFlatButton")
            r = b.rectangle()
            ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
        except Exception:
            L, T, _, _ = win32gui.GetWindowRect(hcom)
            ri.click(L + TOTALIZAR_REL[0], T + TOTALIZAR_REL[1])
        # La alerta 'el producto llegó al mínimo' (u otra confirmación) puede
        # aparecer tras Totalizar y BLOQUEAR la apertura de Total Operación:
        # solo hay que darle OK/Aceptar para continuar (confirmado por el dueño).
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
        raise CompraError("No apareció Total Operación (TFrmTotalOperacion) tras 3 intentos de Totalizar.")
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
    time.sleep(0.5)

    # cerrar el comprobante (Vista Previa), patrón probado de _totalizar_y_guardar
    t0 = time.time()
    while time.time() - t0 < 10:
        h = fp._find_hwnd(PREVIEW_CLASS)
        if h:
            time.sleep(0.25)
            try:
                win32gui.SetForegroundWindow(h)
                time.sleep(0.3)
                ri.press("ESC")
                time.sleep(0.25)
                if fp._find_hwnd(PREVIEW_CLASS):
                    win32gui.PostMessage(h, win32con.WM_SYSCOMMAND, win32con.SC_CLOSE, 0)
                    time.sleep(0.5)
                if fp._find_hwnd(PREVIEW_CLASS):
                    win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
                log.info("Comprobante (Vista Previa) de la compra cerrado.")
            except Exception:
                pass
            time.sleep(0.4)
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
    """items: list[dict] {"codigo": str, "cantidad": float, "costo": float, "precio": float,
    "es_nuevo": bool (opcional), "referencia": str|None (opcional), "descripcion": str
    (opcional, solo requerida si es_nuevo)}.
    proveedor_nombre: opcional; si viene, se verifica contra el campo del header.
    doc_numero: str numérico para los dos campos de Total Operación (relleno).
    Return: {"ok": bool, "etapa": str, "detalle": str,
             "resultados": dict[str_codigo, {"ok","detalle"}],  # verificación por item (solo commit)
             ...}
    etapas éxito: "commit" | "preview"
    etapas fallo PRE-commit (reintentables, NADA quedó a medias porque se canceló todo):
      "abrir_hybrid" | "alta_producto:<etapa>" (ver crear_producto) | "navegacion"
      (clase/proveedor) | "carga_item" | "precio_item"
    etapas fallo AMBIGUAS: "totalizar" | "verificacion_db" | "alta_producto:guardar" |
      "alta_producto:verificacion_db"
    etapa fallo NO AMBIGUA pero tampoco reintentable: "verificacion_indisponible"
      -- la compra SÍ se totalizó y solo falló la LECTURA de la DBISAM para
      confirmarla (unidad H: caída). Reencolar duplicaría el documento; hay que
      revisar a mano. ("alta_producto:verificacion_indisponible" es su gemela en
      el alta: el Guardar ya se pulsó y no se pudo confirmar.)
    REGLA DE ORO: ante CUALQUIER fallo antes de pulsar Totalizar -> Cancelar la
    compra completa + Salir de la ventana + devolver etapa pre-commit. La compra
    es TODO-O-NADA (un documento). El alta de productos nuevos (es_nuevo) corre
    ANTES de abrir Compras -- un fallo ahí también cancela la compra completa
    (todavía no se tocó la grilla de Compras, así que no hay nada que cancelar
    ahí, pero cualquier alta ya confirmada en commit queda hecha: ver ASIMETRÍA
    preview/commit más abajo).

    ASIMETRÍA preview/commit para ítems es_nuevo (documentada en el módulo):
    en preview, crear_producto NO guarda el alta (la descarta en pantalla), así
    que el código NO existe todavía en HybridLite -- cargar_item de ese mismo
    código fallaría ("no existe"). Por eso, en preview, los ítems es_nuevo se
    SALTAN de la carga a la grilla (solo se valida el alta en pantalla) y se
    marcan aparte en 'resultados'. En commit, el alta se guarda de verdad
    ANTES del loop de ítems, así que luego se compran con cargar_item como
    cualquier producto existente."""
    if not items:
        return {"ok": False, "etapa": "navegacion", "detalle": "La lista de items está vacía."}

    codigos_norm = [it["codigo"].strip().lower() for it in items]
    vistos, dups = set(), set()
    for c in codigos_norm:
        (dups if c in vistos else vistos).add(c)
    if dups:
        return {"ok": False, "etapa": "navegacion",
                "detalle": f"Códigos duplicados en la compra: {sorted(dups)}. Nada se tocó."}

    for it in items:
        if it.get("es_nuevo") and not (it.get("descripcion") or "").strip():
            return {"ok": False, "etapa": "navegacion",
                    "detalle": f"Ítem {it['codigo']} viene con es_nuevo=True pero sin "
                               f"descripción. Nada se tocó."}

    # asegurar que Hybrid esté abierto y logueado (lo lanza si está cerrado)
    import abrir_hybrid
    ok, msg = abrir_hybrid.asegurar_hybrid()
    if not ok:
        return {"ok": False, "etapa": "abrir_hybrid", "detalle": msg}

    # ALTA de productos nuevos: ANTES de tocar la grilla de Compras (usa la
    # Ficha de Inventario, ventana distinta a Compras). Cualquier fallo acá
    # cancela la compra completa -- todavía no se escribió nada en Compras.
    altas_resultado = {}
    for it in items:
        if not it.get("es_nuevo"):
            continue
        codigo = it["codigo"]
        # ROBUSTEZ ante reintentos: si el producto YA existe en el maestro
        # (p.ej. una pasada anterior creó el alta pero falló al totalizar la
        # compra), NO re-crearlo (duplicaría/fallaría) -> se compra como
        # existente. Se detecta por _db_precio_usd (None = no existe).
        if hpw._db_precio_usd(codigo) is not None:
            log.info("Ítem %s viene es_nuevo pero YA existe en el maestro; se salta el "
                     "alta y se compra como existente.", codigo)
            it["es_nuevo"] = False
            continue
        res_alta = crear_producto(
            codigo, it.get("descripcion"), it.get("referencia"),
            it["costo"], it["precio"], commit=commit,
        )
        altas_resultado[codigo] = res_alta
        if not res_alta["ok"]:
            return {"ok": False, "etapa": f"alta_producto:{res_alta['etapa']}",
                    "detalle": f"Alta de producto nuevo {codigo} falló, compra CANCELADA "
                               f"(nada se tocó en Compras): {res_alta['detalle']}",
                    "resultados": altas_resultado}
        log.info("Alta de %s (es_nuevo): %s", codigo, res_alta["detalle"])

    # PRE-VUELO DE COLISIONES código<->referencia (ver colisiones.py). Va DESPUÉS
    # de las altas (un producto es_nuevo recién creado ya está en el catálogo y
    # también puede resultar interceptado) y ANTES de abrir Compras: si algún
    # ítem no tiene clave segura se aborta acá, con la grilla sin tocar y la
    # lista COMPLETA de lo que hay que corregir en el catálogo.
    # Sin esto, la compra #43 (2026-08-22) cargó 3 ítems en el producto
    # equivocado y lo descubrió recién tras Totalizar, cuando ya era permanente.
    # En preview los ítems es_nuevo NO se cargan en la grilla (el alta se
    # descartó, el producto no existe) -- se excluyen para que el pre-vuelo no
    # los reporte como "no encontrados" cuando la ausencia es esperada.
    codigos_a_revisar = [it["codigo"] for it in items
                         if commit or not it.get("es_nuevo")]
    try:
        claves_busqueda, problemas = colisiones.revisar_lote(codigos_a_revisar)
    except colisiones.CatalogoIlegible as e:
        return {"ok": False, "etapa": "navegacion",
                "detalle": f"No pude verificar colisiones código/referencia: {e}. "
                           f"Nada se tocó (fail-closed).",
                "resultados": altas_resultado}
    if problemas:
        detalle = " | ".join(f"{c}: {m}" for c, m in problemas.items())
        log.error("Compra ABORTADA por colisión sin salida: %s", detalle)
        return {"ok": False, "etapa": "navegacion",
                "detalle": f"Compra CANCELADA antes de tocar nada: "
                           f"{len(problemas)} ítem(s) sin clave de búsqueda segura. "
                           f"{detalle}",
                "resultados": altas_resultado}
    for codigo, clave in claves_busqueda.items():
        if clave != codigo:
            log.warning("Ítem %s se tecleará como %r (colisión evitada).", codigo, clave)

    # existencia ANTES de cada ítem (para la verificación post-commit). Para
    # ítems es_nuevo en preview el producto no existe todavía -> existencia
    # ANTES no es legible (None), esperado y no bloqueante.
    existencias_antes = {}
    for it in items:
        try:
            total_antes, _ = dbex.existencia(it["codigo"])
        except Exception:
            total_antes = None
        existencias_antes[it["codigo"]] = total_antes
        log.info("Existencia DB ANTES de %s: %s", it["codigo"], total_antes)

    # navegación PRE-escritura: abrir Compras + clasificación + proveedor.
    # Cualquier fallo aquí es 100% reintentable -- nada se ha escrito todavía
    # en Compras (las altas de productos nuevos, si commit=True, ya quedaron
    # hechas en la Ficha y NO se deshacen -- ver nota de ambigüedad arriba).
    try:
        hcom = abrir_compras()
        com = fp._win(hcom)
        fijar_clasificacion(com)
        seleccionar_proveedor(com, proveedor_codigo, proveedor_nombre)
    except (CompraError, fp.FlujoError) as e:
        _cancelar_compra(fp._find_hwnd(COMPRAS_CLASS))
        _salir_compras()
        return {"ok": False, "etapa": "navegacion",
                "detalle": f"No pude llegar a la carga de ítems (nada se tocó en Compras): {e}",
                "resultados": altas_resultado}

    # ítems: cualquier fallo cancela el DOCUMENTO COMPLETO (todo-o-nada).
    # ASIMETRÍA preview: los ítems es_nuevo se SALTAN de cargar_item en preview
    # (el alta no se guardó, el código no existe en HybridLite todavía).
    primero = True
    for it in items:
        if it.get("es_nuevo") and not commit:
            log.info("Ítem %s (es_nuevo, preview): alta ya validada en pantalla y "
                     "descartada -- SALTANDO carga a la grilla de Compras (el producto "
                     "no existe sin --commit).", it["codigo"])
            continue
        try:
            cargar_item(it["codigo"], it["cantidad"], it["costo"], it["precio"],
                        commit, es_primero=primero,
                        clave_busqueda=claves_busqueda.get(it["codigo"]))
            primero = False
        except CompraError as e:
            etapa = "precio_item" if "precio" in str(e).lower() else "carga_item"
            _cancelar_compra(fp._find_hwnd(COMPRAS_CLASS))
            _salir_compras()
            return {"ok": False, "etapa": etapa,
                    "detalle": f"Compra CANCELADA completa (todo-o-nada), fallo en {it['codigo']}: {e}",
                    "resultados": altas_resultado}

    if not commit:
        _cancelar_compra(fp._find_hwnd(COMPRAS_CLASS))
        _salir_compras()
        resultados = dict(altas_resultado)
        for it in items:
            if it.get("es_nuevo"):
                continue   # ya está en altas_resultado (etapa "preview")
            resultados[it["codigo"]] = {"ok": True, "detalle": "Verificado en pantalla y descartado."}
        return {"ok": True, "etapa": "preview",
                "detalle": f"Preview de {len(items)} ítem(s) verificado(s) en pantalla y "
                           f"DESCARTADO (sin --commit; documento cancelado completo). "
                           f"Los ítems es_nuevo NO se cargaron en la grilla (ver asimetría "
                           f"preview/commit en el docstring).",
                "resultados": resultados}

    # COMMIT: Totalizar (etapa AMBIGUA si falla -- no sabemos si el documento
    # quedó a medias en el motor de Hybrid, por eso NO se cancela ni reintenta solo)
    hcom = fp._find_hwnd(COMPRAS_CLASS)
    try:
        _totalizar_compra(hcom, doc_numero)
    except (CompraError, fp.FlujoError) as e:
        return {"ok": False, "etapa": "totalizar",
                "detalle": f"No pude confirmar la totalización de la compra: {e}",
                "resultados": altas_resultado}

    _salir_compras()
    time.sleep(0.8)

    # verificación DB por ítem
    resultados = {}
    todos_ok = True
    for it in items:
        codigo = it["codigo"]
        existencia_antes = existencias_antes.get(codigo)
        existencia_esperada = (existencia_antes + float(it["cantidad"])
                               if existencia_antes is not None else None)
        try:
            existencia_despues, costo_despues, precio_despues = _leer_item_db(codigo)
        except VerificacionIndisponible as e:
            detalle = (f"Compra TOTALIZADA (doc={doc_numero}) con {len(items)} ítem(s), pero la "
                       f"verificación quedó a medias en {codigo}: {e}. La compra YA ESTÁ "
                       f"REGISTRADA en HybridLite — NO reencolar (sería una compra doble); "
                       f"revisar existencias a mano y cerrar la solicitud.")
            log.error("Verificación incompleta de la compra doc=%s: %s", doc_numero, detalle)
            return {"ok": False, "etapa": "verificacion_indisponible",
                    "detalle": detalle, "resultados": resultados}

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

        prefijo_alta = "[alta_producto] " if codigo in altas_resultado else ""
        if fallos:
            todos_ok = False
            detalle = prefijo_alta + "¡ALERTA! " + "; ".join(fallos)
            log.error("Verificación %s: %s", codigo, detalle)
            resultados[codigo] = {"ok": False, "detalle": detalle}
        else:
            detalle = (f"{prefijo_alta}VERIFICADO en DB: existencia={existencia_despues} "
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

    try:
        res = registrar_compra(proveedor_codigo, items, doc_numero, commit="--commit" in _raw)
        print("\n=== RESULTADO ===")
        for k, v in res.items():
            if k == "resultados":
                print("  resultados:")
                for codigo, r in v.items():
                    print(f"    {codigo}: {r}")
            else:
                print(f"  {k}: {v}")
    finally:
        # Cierra la instancia AISLADA que ESTE proceso abrió, para no dejar
        # ventanas de Hybrid acumuladas en corridas standalone (llegaron a
        # verse 13 a la vez, y tantas ventanas de la misma clase desordenan el
        # targeting: el input real acaba en la ventana equivocada). El listener
        # (proceso largo que REUTILIZA una sola instancia entre pasadas) importa
        # registrar_compra directamente y NO pasa por este __main__, así que su
        # reuso no se rompe. Mismo patrón que flujo_pedido_real/_directorio_real.
        try:
            import abrir_hybrid
            abrir_hybrid.cerrar_aislada()
        except Exception as e:
            print(f"(aviso: no pude cerrar la instancia aislada de Hybrid: {e})")
