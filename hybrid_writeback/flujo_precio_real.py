"""
flujo_precio_real.py — Cambio de precio en HybridLiteOS con INPUT REAL de hardware.

Replica EXACTAMENTE la secuencia que el dueño hace a mano (grabada 2026-07-07,
ver FLUJO-PRECIO-CAPTURADO.log). El input sintético de pywinauto es rechazado por
la app ("Database name is missing"); el input real (SendInput) funciona igual que
un humano. Localizamos ventanas/controles con win32/pywinauto (solo lectura) y
ejecutamos clics/teclas con realinput.

Secuencia:
  1. Items de Inventario -> Ficha (TTConfigForm)
  2. Modificar (barra, owner-drawn) -> Busqueda (TForm_BusquedaConfDb)
  3. Ed_Buscar: teclear codigo -> ENTER (ejecuta busqueda) -> doble-clic 1a fila
  4. Costos y Precios (TFlatButton) -> dialogo (TFHCostosPrecios)
  5. Campo USD con impuesto: teclear precio -> ENTER ; verificar en pantalla
  6a. preview (default): 'Salir' (descarta, NO guarda)
  6b. --commit: 'Aceptar' -> Guardar (barra) -> Confirm '&Yes' -> verificar en DB

SEGURIDAD: preview por defecto; un cambio por corrida; verificacion read-back en
pantalla y (en commit) contra DBISAM. Test en 00-002-024 con restauracion.

USO:
    python flujo_precio_real.py 00-002-024 13.50            # preview (no guarda)
    python flujo_precio_real.py 00-002-024 13.50 --commit   # aplica y verifica
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


def set_precio(codigo, target, iva=IVA_DEF, commit=False):
    target = float(target)

    # asegurar que Hybrid esté abierto y logueado (lo lanza si está cerrado)
    import abrir_hybrid
    ok, msg = abrir_hybrid.asegurar_hybrid()
    if not ok:
        return {"ok": False, "etapa": "abrir_hybrid", "detalle": msg}

    db_antes = hpw._db_precio_usd(codigo)
    log.info("Precio USD (con IVA) en DB ANTES: %s", db_antes)

    _cerrar_residuales()
    cargar_producto(codigo)
    abrir_costos_precios()

    try:
        preview = escribir_precio(target, iva)
    except PrecioError as e:
        _click_boton_dialogo("Salir")   # descartar
        return {"ok": False, "etapa": "escritura", "detalle": str(e), "db_antes": db_antes}

    if not commit:
        _click_boton_dialogo("Salir")   # descartar sin guardar
        return {"ok": True, "etapa": "preview",
                "detalle": "Valor verificado en pantalla y DESCARTADO (sin --commit).",
                "preview": preview, "db_antes": db_antes}

    # COMMIT — secuencia confirmada por el dueño: Aceptar -> Salir -> Guardar -> Sí
    if not _click_boton_dialogo("Aceptar"):
        return {"ok": False, "etapa": "aceptar", "detalle": "No pude pulsar 'Aceptar'.",
                "db_antes": db_antes}
    if fp._find_hwnd(fp.PRECIOS_CLASS):
        _click_boton_dialogo("Salir")     # cierra el diálogo conservando el valor aceptado
    _guardar_ficha()                      # persiste en la Ficha (Guardar + Confirm Sí)
    time.sleep(1.2)
    db_despues = hpw._db_precio_usd(codigo)
    log.info("Precio USD en DB DESPUÉS: %s", db_despues)
    if db_despues is not None and abs(db_despues - target) <= TOL:
        return {"ok": True, "etapa": "commit",
                "detalle": f"Precio aplicado y VERIFICADO en DB: {db_despues}",
                "db_antes": db_antes, "db_despues": db_despues}
    return {"ok": False, "etapa": "verificacion_db",
            "detalle": f"¡ALERTA! DB quedó en {db_despues}, no en {target}. Revisar.",
            "db_antes": db_antes, "db_despues": db_despues}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print("Uso: python flujo_precio_real.py <codigo> <precio_usd> [--commit] [--iva 0.16]")
        sys.exit(1)
    codigo = args[0]
    target = float(args[1])
    iva = IVA_DEF
    if "--iva" in sys.argv:
        iva = float(sys.argv[sys.argv.index("--iva") + 1])
    res = set_precio(codigo, target, iva=iva, commit="--commit" in sys.argv)
    print("\n=== RESULTADO ===")
    for k, v in res.items():
        print(f"  {k}: {v}")
