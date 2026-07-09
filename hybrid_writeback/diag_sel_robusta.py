"""
diag_sel_robusta.py — Encuentra una estrategia de selección FIABLE (sin guardar).
Reintenta hasta cargar el código pedido en la Ficha y reporta qué método funcionó.
"""
import sys, os, json, time
import win32gui
import flujo_precio as fp
from pywinauto.mouse import double_click, click

CODIGO = sys.argv[1] if len(sys.argv) > 1 else "00-002-024"
DIR = os.path.dirname(os.path.abspath(__file__))
puntos = json.load(open(os.path.join(DIR, "calib_puntos.json"), encoding="utf-8"))


def ficha_codigo_presente(codigo):
    hf = fp._find_hwnd(fp.FICHA_CLASS)
    if not hf:
        return False, []
    fi = fp._win(hf)
    txt = []
    for cls in ("THybridEdit", "TEdit"):
        for c in fi.descendants(class_name=cls):
            t = (c.window_text() or "").strip()
            if t:
                txt.append(t)
    ok = any(codigo.lower() == t.lower() or codigo.lower() in t.lower() for t in txt)
    return ok, txt[:8]


def abrir_busqueda_y_filtrar(codigo):
    fp._click_punto(puntos, "ficha_buscar", fp.FICHA_CLASS)
    hbusq = fp._wait_for(fp.BUSQ_CLASS, desc="búsqueda")
    busq = fp._win(hbusq)
    busq.set_focus()
    edit = busq.child_window(class_name="THybridEdit")
    edit.click_input()
    time.sleep(0.25)
    edit.type_keys("^a{DELETE}", set_foreground=False)
    edit.type_keys(codigo, with_spaces=False, set_foreground=False, pause=0.06)
    time.sleep(1.6)
    return hbusq, busq


def cerrar_busqueda():
    h = fp._find_hwnd(fp.BUSQ_CLASS)
    if h:
        try:
            fp._win(h).child_window(title="&Salir", class_name="TFlatButton").click_input()
            time.sleep(0.6)
        except Exception:
            pass


metodos = ["click+doubleclick", "click+enter", "doubleclick_solo"]
for intento, metodo in enumerate(metodos, 1):
    print(f"\n===== intento {intento}: método '{metodo}' =====")
    hbusq, busq = abrir_busqueda_y_filtrar(CODIGO)
    grid = busq.child_window(class_name="TDBGrid")
    r = grid.rectangle()
    x, y = r.left + 60, r.top + 34
    busq.set_focus()
    time.sleep(0.2)

    if metodo == "click+doubleclick":
        click(button="left", coords=(x, y)); time.sleep(0.3)
        double_click(button="left", coords=(x, y))
    elif metodo == "click+enter":
        click(button="left", coords=(x, y)); time.sleep(0.3)
        busq.type_keys("{ENTER}", set_foreground=False)
    else:
        double_click(button="left", coords=(x, y))
    time.sleep(1.2)

    cerrar_busqueda()
    time.sleep(0.5)
    ok, txt = ficha_codigo_presente(CODIGO)
    print(f"   resultado: {'CARGÓ ' + CODIGO if ok else 'NO cargó'} | ficha={txt}")
    if ok:
        print(f"\n>>> MÉTODO FIABLE: {metodo}")
        break
