"""
flujo_precio_real.py — Cambio de precio y/o costo en HybridLiteOS con INPUT REAL
de hardware.

Replica EXACTAMENTE la secuencia que el dueño hace a mano (grabada 2026-07-07,
ver FLUJO-PRECIO-CAPTURADO.log). El input sintético de pywinauto es rechazado por
la app ("Database name is missing"); el input real (SendInput) funciona igual que
un humano. Localizamos ventanas/controles con win32/pywinauto (solo lectura) y
ejecutamos clics/teclas con realinput.

Secuencia (set_precio_costo, una sola sesion de Ficha para precio y/o costo):
  1. Items de Inventario -> Ficha (TTConfigForm)
  2. Modificar (barra, owner-drawn) -> Busqueda (TForm_BusquedaConfDb)
  3. Ed_Buscar: teclear codigo -> ENTER (ejecuta busqueda) -> doble-clic 1a fila
  4. Costos y Precios (TFlatButton) -> dialogo (TFHCostosPrecios)
  5. Si viene nuevo_costo: escribirlo PRIMERO (ver escribir_costo).
  6. Si viene nuevo_precio: campo USD con impuesto: teclear -> ENTER ; verificar.
  7a. preview (default): 'Salir' (descarta, NO guarda)
  7b. --commit: 'Aceptar' -> Guardar (barra) -> Confirm '&Yes' -> verificar en DB

COSTO: el diálogo TFHCostosPrecios tiene DOS grupos de "Costo Actual" (ver
campos_precio.png): el groupbox izquierdo "Costos" (SIN etiqueta de moneda ->
Bs, moneda local) y el groupbox "Costos en moneda referencial" (etiqueta
"DOLARES", con un único campo "Costo Actual" bajo el botón/caption "Costos
Moneda Referencial"). Ese botón no aparece como control con título en ninguno
de los dumps de calibración (calib_TFHCostosPrecios_*.txt, dump_TFHCostosPrecios_
*.txt) -- es owner-drawn, igual que "Modificar"/"Guardar" en la Ficha. Por eso
escribir_costo() NO usa coordenadas: localiza el campo POR VALOR (el único
THybridEditNumber del diálogo cuyo texto coincide con el costo USD actual de
la DBISAM, excluyendo los campos de precio). db_costo_usd() lee
TPC_COSTOACTUAL (mismo registro TIPO=1 que el precio, confirmado por
odbc_test.py).

ACOPLE COSTO->PRECIO (confirmado en vivo, preview 2026-07-09): al cambiar el
costo, HybridLite RECALCULA el precio solo (mantiene el % de utilidad; p.ej.
costo 1.08->1.15 movió el precio 1.50->1.60). Por eso set_precio_costo escribe
SIEMPRE el precio después del costo: el nuevo si el usuario lo pidió, o el
precio actual de la DB como PIN si el cambio era solo de costo — así el precio
nunca cambia sin que el usuario lo haya pedido.

SEGURIDAD: preview por defecto; un cambio por corrida; verificacion read-back en
pantalla y (en commit) contra DBISAM. Test en 00-002-024 con restauracion.

USO:
    python flujo_precio_real.py 00-002-024 13.50            # preview (no guarda)
    python flujo_precio_real.py 00-002-024 13.50 --commit   # aplica y verifica
    python flujo_precio_real.py 00-002-024 --costo 6.10     # solo costo (preview)
    python flujo_precio_real.py 00-002-024 13.50 --costo 6.10 --commit
"""
import os
import sys
import time
import logging

import win32gui

# consola tolerante a UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import flujo_precio as fp          # helpers de ventanas + constantes de clase
import hybrid_price_writer as hpw  # lectura DBISAM + localizacion de campos USD
import realinput as ri

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("precio_real")

DIR = os.path.dirname(os.path.abspath(__file__))
TOL = 0.02
IVA_DEF = 0.16

# Botones owner-drawn de la barra de la Ficha (coords relativas, grabacion 2026-07-07)
MODIFICAR_REL = (122, 62)
GUARDAR_REL = (240, 60)


class PrecioError(Exception):
    pass


# ── helpers de lectura de la Ficha ───────────────────────────────────────────
def _ficha_edits():
    hf = fp._find_hwnd(fp.FICHA_CLASS)
    if not hf:
        return []
    fi = fp._win(hf)
    out = []
    for cls in ("THybridEdit", "TEdit"):
        for c in fi.descendants(class_name=cls):
            t = (c.window_text() or "").strip()
            if t:
                out.append(t)
    return out[:10]


def _ficha_muestra(codigo):
    c = codigo.strip().lower()
    return any(c == e.lower() or c in e.lower() for e in _ficha_edits())


def _cerrar_residuales():
    """Cierra busqueda/errores que hayan quedado (para partir limpio)."""
    for _ in range(3):
        h = fp._find_hwnd("TMessageForm")
        if not h:
            break
        try:
            fp._win(h).child_window(title="Aceptar").click_input()
        except Exception:
            try:
                fp._win(h).type_keys("{ENTER}")
            except Exception:
                pass
        time.sleep(0.4)
    h = fp._find_hwnd(fp.BUSQ_CLASS)
    if h:
        try:
            fp._win(h).child_window(title="&Salir", class_name="TFlatButton").click_input()
            time.sleep(0.5)
        except Exception:
            pass


def _focus(hwnd):
    """Fuerza que la ventana Hybrid esté al frente ANTES de disparar input real.
    Sin esto, las teclas/clic reales pueden irse a otra ventana (bug de foco)."""
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


def _grid_primera_fila_codigo(busq):
    """Intenta leer el código de la 1a fila visible del TDBGrid (para saber si la
    lista ya se posicionó en el producto buscado). Devuelve str o None."""
    try:
        grid = busq.child_window(class_name="TDBGrid")
        txts = [t for t in grid.texts() if t]
        # el primer token con forma de código (dígitos/guiones) suele ser la celda
        for t in txts:
            s = t.strip()
            if s and all(ch.isdigit() or ch == "-" for ch in s):
                return s
    except Exception:
        pass
    return None


def _esperar_refresco(busq, codigo, timeout=6.0):
    """Espera a que la lista de la búsqueda se posicione en el código pedido.
    Si no puede leer la grilla, espera un tiempo prudencial fijo."""
    t0 = time.time()
    leible = False
    while time.time() - t0 < timeout:
        prim = _grid_primera_fila_codigo(busq)
        if prim is not None:
            leible = True
            if prim.strip() == codigo.strip():
                return True
        time.sleep(0.3)
    if not leible:
        time.sleep(2.5)   # no pude leer la grilla: espera fija generosa
    return False


# ── pasos ────────────────────────────────────────────────────────────────────
def abrir_ficha():
    import json
    hf = fp._find_hwnd(fp.FICHA_CLASS)
    if hf:
        return hf
    hmain = fp._find_hwnd(fp.MAIN_CLASS)
    if not hmain:
        raise PrecioError("HybridLiteOS no está abierto (no veo el módulo principal).")
    main = fp._win(hmain)
    _focus(hmain); time.sleep(0.2)
    # el botón 'Items de Inventario' solo aparece tras abrir el submenú Inventario
    try:
        btn = main.child_window(title="Items de Inventario", class_name="TAdvGlassButton")
        btn.wait("exists visible", timeout=1.5)
    except Exception:
        puntos = json.load(open(os.path.join(DIR, "calib_puntos.json"), encoding="utf-8"))
        rel = puntos["menu_inventario"]["rel"]
        L, T, _, _ = win32gui.GetWindowRect(hmain)
        ri.click(L + rel[0], T + rel[1])       # menú lateral Inventario
        time.sleep(0.8)
        btn = main.child_window(title="Items de Inventario", class_name="TAdvGlassButton")
        btn.wait("exists visible", timeout=8)
    r = btn.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    return fp._wait_for(fp.FICHA_CLASS, desc="Ficha")


def cargar_producto(codigo):
    """Modificar -> Ed_Buscar -> teclear -> ENTER -> (esperar refresco) -> ENTER
    selecciona la fila posicionada en el código. (INPUT REAL)"""
    hf = abrir_ficha()
    _focus(hf); time.sleep(0.2)

    if _ficha_muestra(codigo):
        log.info("La Ficha ya muestra %s.", codigo)
        return

    L, T, _, _ = win32gui.GetWindowRect(hf)
    ri.click(L + MODIFICAR_REL[0], T + MODIFICAR_REL[1])          # Modificar
    hbusq = fp._wait_for(fp.BUSQ_CLASS, desc="Busqueda")
    busq = fp._win(hbusq)
    time.sleep(0.5)

    _focus(hbusq)
    ed = busq.child_window(class_name="THybridEdit", found_index=0)
    r = ed.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)    # Ed_Buscar
    time.sleep(0.3)
    ri.clear_field()
    ri.type_text(codigo)
    time.sleep(0.4)
    ri.press("ENTER")                                            # ejecuta la búsqueda

    # ESPERAR a que la lista se posicione en el código (el usuario avisó de esto)
    posicionado = _esperar_refresco(busq, codigo, timeout=6.0)
    log.info("Lista posicionada en %s: %s", codigo, posicionado)

    # Seleccionar la fila actual (la que quedó posicionada = el match). Enter la carga.
    if fp._find_hwnd(fp.BUSQ_CLASS):
        _focus(hbusq)
        ri.press("ENTER")
        time.sleep(1.2)

    # Fallback: si sigue abierta, doble-clic en la fila posicionada (arriba del grid)
    if fp._find_hwnd(fp.BUSQ_CLASS):
        grid = busq.child_window(class_name="TDBGrid")
        gr = grid.rectangle()
        ri.click(gr.left + 100, gr.top + 26, double=True)
        time.sleep(1.2)

    if fp._find_hwnd("TMessageForm"):
        _cerrar_residuales()
        raise PrecioError("Apareció un diálogo de error al buscar (revisar).")
    if fp._find_hwnd(fp.BUSQ_CLASS):
        _cerrar_residuales()

    if not _ficha_muestra(codigo):
        raise PrecioError(f"La Ficha NO cargó {codigo} (edits={_ficha_edits()}).")
    log.info("Producto %s cargado en la Ficha.", codigo)


def abrir_costos_precios():
    hf = fp._find_hwnd(fp.FICHA_CLASS)
    _focus(hf); time.sleep(0.2)
    fi = fp._win(hf)
    btn = fi.child_window(title="Costos &y Precios", class_name="TFlatButton")
    btn.wait("exists visible", timeout=fp.T_WAIT)
    r = btn.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    return fp._wait_for(fp.PRECIOS_CLASS, desc="Costos y Precios")


def escribir_precio(target, iva):
    """Teclea el precio USD-CON-impuesto (INPUT REAL, teclado numérico) y verifica
    en pantalla. Devuelve dict {con, sin}. Lanza si no cuadra.

    Claves aprendidas de la grabación:
      * el campo a editar es 'Precio con impuesto' (el de MAYOR top en POtrasMonedas)
      * hay que ENFOCARLO (clic real bajo dentro del campo + set_focus de respaldo)
      * BORRAR duro (END + backspaces) — el select-all a veces no reemplaza
      * teclear por el NUMÉRICO (la coma/punto como texto la ignora la app)
    """
    hd = fp._find_hwnd(fp.PRECIOS_CLASS)
    _focus(hd)                                    # diálogo al frente (evita bug de foco)
    dlg = fp._win(hd)
    sin_field, con_field = hpw._usd_fields(dlg)   # (sin, con) del panel POtrasMonedas
    log.info("Campo con-impuesto actual=%r ; sin-impuesto actual=%r",
             con_field.window_text(), sin_field.window_text())

    # enfocar el campo con-impuesto: clic real en la parte baja del campo + set_focus
    r = con_field.rectangle()
    cx = (r.left + r.right) // 2
    ri.click(cx, r.bottom - 4)
    time.sleep(0.2)
    try:
        con_field.set_focus()
    except Exception:
        pass
    time.sleep(0.2)

    ri.clear_hard()                       # borra el valor anterior de verdad
    if (con_field.window_text() or "").strip() not in ("", "0", "0.00", "0,00"):
        # segundo intento de borrado si quedó algo
        ri.clear_hard()
    ri.type_number(f"{target:.2f}")       # teclea por el numérico (respeta el decimal)
    time.sleep(0.2)
    ri.press("ENTER")                     # commit + recalcula el sin-impuesto y el Bs
    time.sleep(0.6)

    con_val = hpw._num(con_field.window_text())
    sin_val = hpw._num(sin_field.window_text())
    esperado_sin = target / (1.0 + iva)
    log.info("En pantalla: con=%.4f sin=%.4f (esperado_sin=%.4f)",
             con_val if con_val is not None else -1,
             sin_val if sin_val is not None else -1, esperado_sin)

    con_ok = con_val is not None and abs(con_val - target) <= TOL
    sin_ok = sin_val is not None and abs(sin_val - esperado_sin) <= max(TOL, esperado_sin * 0.02)
    if not (con_ok and sin_ok):
        raise PrecioError(f"El precio en pantalla no cuadra (con={con_val}, sin={sin_val}, "
                          f"esperado_sin={esperado_sin:.4f}). NO se compromete nada.")
    return {"con": con_val, "sin": sin_val}


def escribir_costo(nuevo_costo, costo_actual_db):
    """Teclea el costo USD (sin IVA) en el campo 'Costo Actual' del groupbox
    'Costos en moneda referencial' de TFHCostosPrecios. INPUT REAL.

    LOCALIZACIÓN AUTO-VERIFICADA POR VALOR (no por coordenadas): el diálogo
    tiene DOS 'Costo Actual' (uno en Bs en el groupbox 'Costos' y uno USD bajo
    'Costos Moneda Referencial', ver campos_precio.png) y el caption USD es
    owner-drawn (no sale en los dumps de calibración). Como no existe grabación
    humana de un cambio de costo (a diferencia del precio, ver
    FLUJO-PRECIO-CAPTURADO.log), NO confiamos en posiciones: se toma el ÚNICO
    THybridEditNumber del diálogo cuyo valor coincide con el costo USD actual
    leído de la DBISAM (`costo_actual_db`), excluyendo los dos campos de precio
    de _usd_fields. Cero o más de un candidato -> PrecioError (el llamador
    descarta con 'Salir' y NADA se escribe) — así es imposible escribir un
    valor USD en el campo Bs por accidente.

    Tras teclear verifica: (a) el campo quedó en `nuevo_costo` (± TOL), y
    (b) los campos de PRECIO no cambiaron (sin efecto colateral). Devuelve
    {"costo": leido}. Lanza PrecioError ante cualquier desviación."""
    if costo_actual_db is None:
        raise PrecioError("Costo USD actual no legible de DBISAM: no puedo "
                          "localizar el campo de costo con seguridad. NO se escribe nada.")
    hd = fp._find_hwnd(fp.PRECIOS_CLASS)
    _focus(hd)
    dlg = fp._win(hd)

    # campos de precio: se excluyen de la búsqueda y se verifican intactos al final
    try:
        sin_field, con_field = hpw._usd_fields(dlg)
        rects_precio = {str(sin_field.rectangle()), str(con_field.rectangle())}
        precio_antes = (sin_field.window_text(), con_field.window_text())
    except Exception:
        sin_field = con_field = None
        rects_precio = set()
        precio_antes = None

    candidatos = []
    for c in dlg.descendants(class_name="THybridEditNumber"):
        if str(c.rectangle()) in rects_precio:
            continue
        v = hpw._num(c.window_text())
        if v is not None and abs(v - float(costo_actual_db)) <= 0.005:
            candidatos.append(c)
    if len(candidatos) != 1:
        raise PrecioError(
            f"No pude localizar el campo de costo USD sin ambigüedad: "
            f"{len(candidatos)} candidato(s) con valor {costo_actual_db} en "
            f"TFHCostosPrecios. NO se escribe nada.")
    campo = candidatos[0]
    log.info("Campo de costo localizado por valor=%s en %s",
             costo_actual_db, campo.rectangle())

    # mismo patrón probado de escribir_precio: clic bajo + set_focus + borrado duro
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
    log.info("Costo en pantalla tras teclear: %s (target=%s)", leido, nuevo_costo)
    if leido is None or abs(leido - float(nuevo_costo)) > TOL:
        raise PrecioError(f"El costo en pantalla no cuadra (quedó {leido}, "
                          f"esperado {nuevo_costo}). NO se compromete nada.")
    # COMPORTAMIENTO CONFIRMADO EN VIVO (preview 2026-07-09): HybridLite
    # RECALCULA el precio al cambiar el costo (mantiene el % de utilidad:
    # p.ej. costo 1.08->1.15 movió el precio 1.50->1.60 solo). NO es un
    # campo equivocado — es el acople costo->precio propio del POS. Por eso
    # el llamador (set_precio_costo) SIEMPRE escribe el precio DESPUÉS del
    # costo (el pedido explícito o el precio previo como pin), y acá solo se
    # deja registro informativo del recálculo observado.
    precio_recalculado = None
    if precio_antes is not None:
        precio_ahora = (sin_field.window_text(), con_field.window_text())
        if precio_ahora != precio_antes:
            log.info("Recálculo costo->precio observado: %s -> %s (se corrige "
                     "escribiendo el precio a continuación).", precio_antes, precio_ahora)
            precio_recalculado = {"antes": precio_antes, "ahora": precio_ahora}
    return {"costo": leido, "precio_recalculado": precio_recalculado}


def db_costo_usd(codigo):
    """Lee el COSTO actual (USD sin IVA, TPC_COSTOACTUAL) desde la DBISAM, sin
    tocar la UI. Delegado a hybrid_price_writer._db_costo_usd (mismo patrón que
    _db_precio_usd). Devuelve float o None si no se puede leer/identificar."""
    return hpw._db_costo_usd(codigo)


def _click_boton_dialogo(titulo):
    """Clic REAL en un botón del diálogo Costos y Precios (Aceptar/Salir)."""
    hd = fp._find_hwnd(fp.PRECIOS_CLASS)
    if not hd:
        return False
    _focus(hd)
    try:
        b = fp._win(hd).child_window(title=titulo, class_name="TButton")
        r = b.rectangle()
        ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
        time.sleep(0.6)
        return True
    except Exception:
        return False


def _confirmar_si():
    """Responde 'Sí' al diálogo Confirm de Guardar (si aparece)."""
    t0 = time.time()
    while time.time() - t0 < 5:
        h = fp._find_hwnd("TMessageForm")
        if h:
            _focus(h)
            for titulo in ("&Yes", "&Sí", "Sí", "Yes"):
                try:
                    b = fp._win(h).child_window(title=titulo)
                    r = b.rectangle()
                    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                    log.info("Confirmación '%s' pulsada.", titulo)
                    time.sleep(0.8)
                    return True
                except Exception:
                    continue
        time.sleep(0.3)
    return False


def _guardar_ficha():
    """Guardar (barra de la Ficha, owner-drawn) -> Confirm 'Sí'. INPUT REAL."""
    hf = fp._find_hwnd(fp.FICHA_CLASS)
    _focus(hf)
    L, T, _, _ = win32gui.GetWindowRect(hf)
    ri.click(L + GUARDAR_REL[0], T + GUARDAR_REL[1])
    time.sleep(1.0)
    _confirmar_si()
    return True


def set_precio_costo(codigo, nuevo_precio=None, nuevo_costo=None, iva=IVA_DEF, commit=False):
    """Cambia precio y/o costo de un producto en UNA sola sesión de Ficha.

    Al menos uno de nuevo_precio/nuevo_costo debe venir. Si vienen ambos: se
    escribe el COSTO PRIMERO y el precio después (requerimiento del dueño). Un
    solo Aceptar/Guardar al final cubre ambos.

    El campo de costo se localiza por VALOR contra el costo USD actual de la
    DBISAM (ver escribir_costo); si ese costo no es legible, se falla ANTES de
    abrir la UI (etapa='escritura', nada se toca).

    Return: {"ok": bool, "etapa": str, "detalle": str, ...}
      etapa éxito:   "commit" (con commit=True) | "preview" (sin commit)
      etapa fallo:   "abrir_hybrid" | "escritura" | "aceptar" | "verificacion_db"
    ("escritura" cubre cualquier fallo escribiendo/verificando en pantalla
    ANTES de Aceptar — en ese caso se pulsa 'Salir' para descartar y NADA
    queda a medias)."""
    if nuevo_precio is None and nuevo_costo is None:
        return {"ok": False, "etapa": "escritura",
                "detalle": "Debe venir al menos uno de nuevo_precio/nuevo_costo."}

    target = float(nuevo_precio) if nuevo_precio is not None else None
    costo_target = float(nuevo_costo) if nuevo_costo is not None else None

    # asegurar que Hybrid esté abierto y logueado (lo lanza si está cerrado)
    import abrir_hybrid
    ok, msg = abrir_hybrid.asegurar_hybrid()
    if not ok:
        return {"ok": False, "etapa": "abrir_hybrid", "detalle": msg}

    # el precio DB se lee SIEMPRE: si hay cambio de costo sin cambio de precio,
    # hace falta como PIN (HybridLite recalcula el precio al cambiar el costo
    # — confirmado en vivo 2026-07-09 — y hay que reescribirlo para que el
    # precio NO cambie sin que el usuario lo haya pedido)
    db_precio_antes = hpw._db_precio_usd(codigo)
    db_costo_antes = hpw._db_costo_usd(codigo) if costo_target is not None else None
    log.info("Precio USD en DB ANTES: %s ; Costo USD en DB ANTES: %s",
             db_precio_antes, db_costo_antes)

    # guard temprano: sin costo DB legible no hay forma segura de localizar el
    # campo de costo -> fallar acá, ANTES de abrir la UI (no gastar viaje de Ficha)
    if costo_target is not None and db_costo_antes is None:
        return {"ok": False, "etapa": "escritura",
                "detalle": "Costo USD actual no legible de DBISAM: no puedo "
                           "localizar el campo de costo con seguridad. Nada se tocó.",
                "db_precio_antes": db_precio_antes, "db_costo_antes": None}

    # precio que quedará escrito: el pedido explícito, o (solo-costo) el pin
    # del precio actual para compensar el recálculo costo->precio del POS
    precio_pin = None
    if costo_target is not None and target is None:
        if db_precio_antes is None:
            return {"ok": False, "etapa": "escritura",
                    "detalle": "Cambio de costo sin precio nuevo y el precio actual no es "
                               "legible de DBISAM: no puedo fijar el precio tras el recálculo "
                               "costo->precio del POS. Nada se tocó.",
                    "db_precio_antes": None, "db_costo_antes": db_costo_antes}
        precio_pin = db_precio_antes
    precio_a_escribir = target if target is not None else precio_pin

    _cerrar_residuales()
    cargar_producto(codigo)
    abrir_costos_precios()

    preview_costo = None
    preview_precio = None
    try:
        if costo_target is not None:
            preview_costo = escribir_costo(costo_target, db_costo_antes)  # PRIMERO el costo
        if precio_a_escribir is not None:
            if precio_pin is not None:
                log.info("Fijando el precio en %.2f (pin: sin cambio de precio pedido, "
                         "compensa el recálculo costo->precio).", precio_pin)
            preview_precio = escribir_precio(precio_a_escribir, iva)
    except PrecioError as e:
        _click_boton_dialogo("Salir")   # descartar, nada queda a medias
        return {"ok": False, "etapa": "escritura", "detalle": str(e),
                "db_precio_antes": db_precio_antes, "db_costo_antes": db_costo_antes}

    if not commit:
        _click_boton_dialogo("Salir")   # descartar sin guardar
        return {"ok": True, "etapa": "preview",
                "detalle": "Valor(es) verificado(s) en pantalla y DESCARTADO(s) (sin --commit).",
                "preview_precio": preview_precio, "preview_costo": preview_costo,
                "db_precio_antes": db_precio_antes, "db_costo_antes": db_costo_antes}

    # COMMIT — secuencia confirmada por el dueño: Aceptar -> Salir -> Guardar -> Sí
    if not _click_boton_dialogo("Aceptar"):
        return {"ok": False, "etapa": "aceptar", "detalle": "No pude pulsar 'Aceptar'.",
                "db_precio_antes": db_precio_antes, "db_costo_antes": db_costo_antes}
    if fp._find_hwnd(fp.PRECIOS_CLASS):
        _click_boton_dialogo("Salir")     # cierra el diálogo conservando el valor aceptado
    _guardar_ficha()                      # persiste en la Ficha (Guardar + Confirm Sí)
    time.sleep(1.2)

    detalles = []
    ok_total = True
    db_precio_despues = None
    db_costo_despues = None

    if precio_a_escribir is not None:
        db_precio_despues = hpw._db_precio_usd(codigo)
        log.info("Precio USD en DB DESPUÉS: %s", db_precio_despues)
        etiqueta = "Precio aplicado" if target is not None else "Precio fijado (pin, sin cambio pedido)"
        if db_precio_despues is not None and abs(db_precio_despues - precio_a_escribir) <= TOL:
            detalles.append(f"{etiqueta} y VERIFICADO en DB: {db_precio_despues}")
        else:
            ok_total = False
            detalles.append(f"¡ALERTA! Precio en DB quedó en {db_precio_despues}, "
                            f"no en {precio_a_escribir}.")

    if costo_target is not None:
        db_costo_despues = hpw._db_costo_usd(codigo)
        log.info("Costo USD en DB DESPUÉS: %s", db_costo_despues)
        if db_costo_despues is None:
            detalles.append("Costo: no verificable por DB (TPC_COSTOACTUAL no legible), "
                             "pero se verificó en pantalla.")
        elif abs(db_costo_despues - costo_target) <= TOL:
            detalles.append(f"Costo aplicado y VERIFICADO en DB: {db_costo_despues}")
        else:
            ok_total = False
            detalles.append(f"¡ALERTA! Costo en DB quedó en {db_costo_despues}, no en {costo_target}.")

    etapa = "commit" if ok_total else "verificacion_db"
    return {"ok": ok_total, "etapa": etapa, "detalle": " | ".join(detalles),
            "db_precio_antes": db_precio_antes, "db_precio_despues": db_precio_despues,
            "db_costo_antes": db_costo_antes, "db_costo_despues": db_costo_despues}


def set_precio(codigo, target, iva=IVA_DEF, commit=False):
    """Wrapper delgado sobre set_precio_costo (compatibilidad: comportamiento
    externo sin cambios, el listener actual lo sigue llamando igual)."""
    return set_precio_costo(codigo, nuevo_precio=target, iva=iva, commit=commit)


if __name__ == "__main__":
    _raw = sys.argv[1:]
    _flags_con_valor = ("--costo", "--iva")
    args = []           # solo posicionales: <codigo> [<precio_usd>]
    i = 0
    while i < len(_raw):
        tok = _raw[i]
        if tok in _flags_con_valor:
            i += 2      # saltar la bandera Y su valor
            continue
        if not tok.startswith("--"):
            args.append(tok)
        i += 1

    if len(args) < 1:
        print("Uso: python flujo_precio_real.py <codigo> [<precio_usd>] [--costo <costo_usd>] "
              "[--commit] [--iva 0.16]")
        sys.exit(1)
    codigo = args[0]
    target = float(args[1]) if len(args) >= 2 else None
    costo = None
    if "--costo" in _raw:
        costo = float(_raw[_raw.index("--costo") + 1])
    if target is None and costo is None:
        print("Debe indicar <precio_usd> y/o --costo <costo_usd>.")
        sys.exit(1)
    iva = IVA_DEF
    if "--iva" in _raw:
        iva = float(_raw[_raw.index("--iva") + 1])
    res = set_precio_costo(codigo, nuevo_precio=target, nuevo_costo=costo,
                            iva=iva, commit="--commit" in _raw)
    print("\n=== RESULTADO ===")
    for k, v in res.items():
        print(f"  {k}: {v}")
