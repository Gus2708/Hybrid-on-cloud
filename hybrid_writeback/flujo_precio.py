"""
flujo_precio.py — Flujo COMPLETO de cambio de precio en HybridLiteOS (pywinauto).

Encadena la navegación mapeada en la calibración del 2026-07-04:

    Módulo principal (TF_MainHybridCashMG)
      └─ [menú lateral 'INVENTARIO']            ← punto hover 'menu_inventario'
      └─ botón 'Items de Inventario'            (TAdvGlassButton, por título)
          └─ Ficha de Inventario (TTConfigForm)
              └─ [botón BUSCAR]                 ← punto hover 'ficha_buscar'
              │    └─ Búsqueda (TForm_BusquedaConfDb): combo 'Codigo' + edit + TDBGrid
              └─ botón 'Costos &y Precios'      (TFlatButton, por título)
              │    └─ diálogo Costos y Precios (TFHCostosPrecios)
              │        └─ escribe/verifica USD con impuesto (hybrid_price_writer)
              │        └─ 'Aceptar' (TButton)
              └─ [botón GUARDAR]                ← punto hover 'ficha_guardar'
      └─ verificación final contra DBISAM (pydbisam, TIPO=1 PVPCONIMPUESTO1)

Los tres puntos entre corchetes son botones de icono/imagen que Windows no expone:
sus coordenadas RELATIVAS a su ventana viven en calib_puntos.json (se llenan con
calibrar_hover.py). Sin ese archivo el flujo NO hace clics a ciegas: aborta.

SEGURIDAD:
  * Por defecto commit=False → recorre todo, previsualiza y NO guarda.
  * --commit aplica de verdad (Aceptar + Guardar) y verifica contra la base.
  * Un solo cambio por invocación; pensado para el listener, no cargas masivas.

USO:
    python flujo_precio.py 00-002-024 13.50            # preview (no guarda)
    python flujo_precio.py 00-002-024 13.50 --commit   # aplica y verifica
"""
import os
import sys
import json
import time
import logging

import win32gui
import win32process
from pywinauto import Application, Desktop
from pywinauto.mouse import click as mouse_click, double_click

import hybrid_price_writer as hpw

log = logging.getLogger("flujo_precio")

DIR = os.path.dirname(os.path.abspath(__file__))
PUNTOS_JSON = os.path.join(DIR, "calib_puntos.json")

MAIN_CLASS = "TF_MainHybridCashMG"
FICHA_CLASS = "TTConfigForm"          # title='Ficha de Inventario'
BUSQ_CLASS = "TForm_BusquedaConfDb"   # title='Busqueda De :Ficha de Inventario'
PRECIOS_CLASS = "TFHCostosPrecios"    # title='Costos y Precios'

T_WAIT = 10          # s de espera de aparición de ventanas
POLL = 0.25


class FlujoError(Exception):
    pass


# ─── utilidades de ventanas ──────────────────────────────────────────────────
def _find_hwnd(cls_name, visible=True):
    """hwnd de la primera ventana top-level de esa clase (o None)."""
    out = []

    def _cb(h, _):
        if visible and not win32gui.IsWindowVisible(h):
            return
        if win32gui.GetClassName(h) == cls_name:
            out.append(h)

    win32gui.EnumWindows(_cb, None)
    return out[0] if out else None


def _wait_for(cls_name, timeout=T_WAIT, desc=""):
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = _find_hwnd(cls_name)
        if h:
            return h
        time.sleep(POLL)
    raise FlujoError(f"No apareció la ventana {cls_name} ({desc}) en {timeout}s.")


def _wait_gone(hwnd, timeout=T_WAIT):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
            return True
        time.sleep(POLL)
    return False


def _win(hwnd):
    """Wrapper pywinauto (win32) de un hwnd concreto."""
    pid = win32process.GetWindowThreadProcessId(hwnd)[1]
    app = Application(backend="win32").connect(process=pid, timeout=5)
    return app.window(handle=hwnd)


# ─── puntos calibrados (hover) ───────────────────────────────────────────────
def _load_puntos():
    if not os.path.exists(PUNTOS_JSON):
        raise FlujoError(
            f"Falta {os.path.basename(PUNTOS_JSON)}. Ejecuta calibrar_hover.py "
            "(hover sobre: menú INVENTARIO, Ficha:BUSCAR, Ficha:GUARDAR) y pásame "
            "el calib_hover_*.txt para llenarlo. NO hago clics a ciegas."
        )
    with open(PUNTOS_JSON, encoding="utf-8") as f:
        return json.load(f)


def _click_punto(puntos, nombre, expect_class):
    """Clic en un punto calibrado, relativo a su ventana (verifica la clase)."""
    if nombre not in puntos:
        raise FlujoError(f"Punto '{nombre}' no está en calib_puntos.json.")
    p = puntos[nombre]
    if p.get("window_class") != expect_class:
        raise FlujoError(f"Punto '{nombre}' calibrado para {p.get('window_class')}, "
                         f"esperaba {expect_class}.")
    hwnd = _find_hwnd(expect_class)
    if not hwnd:
        raise FlujoError(f"Ventana {expect_class} no está abierta para '{nombre}'.")
    L, T, _, _ = win32gui.GetWindowRect(hwnd)
    x, y = L + p["rel"][0], T + p["rel"][1]
    _win(hwnd).set_focus()
    time.sleep(0.2)
    mouse_click(button="left", coords=(x, y))
    log.info("clic '%s' en (%d,%d) de %s", nombre, x, y, expect_class)
    time.sleep(0.4)


# ─── pasos del flujo ─────────────────────────────────────────────────────────
def abrir_ficha(puntos):
    """Garantiza que la Ficha de Inventario esté abierta. Devuelve su hwnd."""
    h = _find_hwnd(FICHA_CLASS)
    if h and "Ficha de Inventario" in (win32gui.GetWindowText(h) or ""):
        log.info("Ficha de Inventario ya abierta.")
        return h

    hmain = _find_hwnd(MAIN_CLASS)
    if not hmain:
        raise FlujoError("HybridLiteOS no está abierto (no veo el módulo principal).")
    main = _win(hmain)
    main.set_focus()
    time.sleep(0.3)

    # ¿El grupo INVENTARIO ya está visible? (busca el botón 'Items de Inventario')
    try:
        btn = main.child_window(title="Items de Inventario",
                                class_name="TAdvGlassButton")
        btn.wait("exists visible", timeout=1.5)
    except Exception:
        _click_punto(puntos, "menu_inventario", MAIN_CLASS)
        btn = main.child_window(title="Items de Inventario",
                                class_name="TAdvGlassButton")
        btn.wait("exists visible", timeout=T_WAIT)

    btn.click_input()
    return _wait_for(FICHA_CLASS, desc="Ficha de Inventario")


def cargar_producto(puntos, codigo):
    """Abre la búsqueda desde la Ficha y carga el producto por código."""
    _click_punto(puntos, "ficha_buscar", FICHA_CLASS)
    hbusq = _wait_for(BUSQ_CLASS, desc="Búsqueda de Ficha de Inventario")
    busq = _win(hbusq)

    combo = busq.child_window(class_name="TComboBox")
    try:
        if "codigo" not in (combo.window_text() or "").lower():
            combo.select("Codigo")
            time.sleep(0.3)
    except Exception:
        pass  # si ya está en 'Codigo' seguimos

    edit = busq.child_window(class_name="THybridEdit")
    edit.click_input()
    time.sleep(0.2)
    edit.type_keys("^a{DELETE}", set_foreground=False)
    edit.type_keys(codigo, with_spaces=False, set_foreground=False, pause=0.06)
    time.sleep(1.5)               # deja filtrar la grilla

    # Seleccionar con DOBLE-CLIC en la primera fila de datos de la grilla.
    # (El ENTER sobre el edit selecciona la fila resaltada previa, no la filtrada.)
    grid = busq.child_window(class_name="TDBGrid")
    r = grid.rectangle()
    double_click(button="left", coords=(r.left + 60, r.top + 34))
    time.sleep(1.0)

    # Cerrar la búsqueda si quedó abierta (el doble-clic carga pero no siempre cierra).
    if _find_hwnd(BUSQ_CLASS):
        try:
            _win(_find_hwnd(BUSQ_CLASS)).child_window(
                title="&Salir", class_name="TFlatButton").click_input()
            time.sleep(0.6)
        except Exception:
            pass
    time.sleep(0.4)
    _verificar_producto_cargado(codigo)


def _verificar_producto_cargado(codigo):
    """Confirma que la Ficha muestra el código pedido en alguno de sus edits.
    Evita editar el producto equivocado si la búsqueda seleccionó otra fila."""
    hficha = _find_hwnd(FICHA_CLASS)
    ficha = _win(hficha)
    textos = []
    for cls in ("THybridEdit", "TEdit", "THybridEditNumber"):
        for c in ficha.descendants(class_name=cls):
            t = (c.window_text() or "").strip()
            if t:
                textos.append(t)
    objetivo = codigo.strip().lower()
    if not any(objetivo == t.lower() or objetivo in t.lower() for t in textos):
        raise FlujoError(
            f"La Ficha NO muestra el código {codigo} tras la búsqueda "
            f"(textos visibles: {textos[:12]}). Abortando para no tocar otro producto."
        )
    log.info("Producto %s confirmado en la Ficha.", codigo)


def abrir_costos_precios():
    """Desde la Ficha, abre el diálogo Costos y Precios."""
    hficha = _find_hwnd(FICHA_CLASS)
    ficha = _win(hficha)
    ficha.set_focus()
    btn = ficha.child_window(title="Costos &y Precios", class_name="TFlatButton")
    btn.wait("exists visible", timeout=T_WAIT)
    btn.click_input()
    return _wait_for(PRECIOS_CLASS, desc="Costos y Precios")


def set_precio(codigo, precio_usd, iva=0.16, commit=False):
    """Flujo completo. Devuelve dict con el resultado."""
    precio_usd = float(precio_usd)
    puntos = _load_puntos()

    db_antes = hpw._db_precio_usd(codigo)
    log.info("Precio USD (con IVA) en DB ANTES: %s", db_antes)

    abrir_ficha(puntos)
    cargar_producto(puntos, codigo)
    abrir_costos_precios()

    # escribir + verificar en pantalla (reutiliza el writer probado)
    app, dlg = hpw._find_dialog()
    try:
        preview = hpw._write_with_verify(dlg, precio_usd, iva)
    except hpw.PriceWriteError as e:
        hpw._abort(dlg)
        return {"ok": False, "etapa": "escritura", "detalle": str(e),
                "db_antes": db_antes}

    if not commit:
        hpw._abort(dlg)   # salir sin guardar
        return {"ok": True, "etapa": "preview",
                "detalle": "Valor verificado en pantalla y descartado (sin --commit).",
                "preview": preview, "db_antes": db_antes}

    # COMMIT: Aceptar en el diálogo + Guardar en la ficha
    dlg.set_focus()
    dlg.child_window(title="Aceptar", class_name="TButton").click_input()
    time.sleep(0.8)
    _click_punto(puntos, "ficha_guardar", FICHA_CLASS)
    time.sleep(1.2)

    # posible confirmación (mensaje VCL): responde 'Sí'/'Yes'/'OK' si aparece
    t0 = time.time()
    while time.time() - t0 < 4:
        h = _find_hwnd("TMessageForm")
        if h:
            m = _win(h)
            for btxt in ("&Yes", "&Sí", "Sí", "Yes", "OK", "Aceptar"):
                try:
                    m.child_window(title=btxt).click_input()
                    log.info("Confirmación respondida con '%s'.", btxt)
                    time.sleep(0.6)
                    break
                except Exception:
                    continue
        time.sleep(0.4)

    time.sleep(1.0)
    db_despues = hpw._db_precio_usd(codigo)
    log.info("Precio USD en DB DESPUÉS: %s", db_despues)
    if db_despues is not None and abs(db_despues - precio_usd) <= hpw.TOL:
        return {"ok": True, "etapa": "commit",
                "detalle": f"Precio aplicado y VERIFICADO en la base: {db_despues}",
                "db_antes": db_antes, "db_despues": db_despues}
    return {"ok": False, "etapa": "verificacion_db",
            "detalle": f"¡ALERTA! DB quedó en {db_despues}, no en {precio_usd}. Revisar.",
            "db_antes": db_antes, "db_despues": db_despues}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    res = set_precio(args[0], args[1], commit="--commit" in sys.argv)
    print("\n=== RESULTADO ===")
    for k, v in res.items():
        print(f"  {k}: {v}")
