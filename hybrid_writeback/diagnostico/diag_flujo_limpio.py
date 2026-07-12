"""
diag_flujo_limpio.py — Flujo natural desde el menú, con capturas (NO guarda).

  1. Cierra búsqueda/errores/ficha si quedaron abiertos.
  2. Desde el módulo principal: clic en 'Items de Inventario' (abre Ficha fresca).
  3. Captura la Ficha recién abierta.
  4. Prueba cargar el producto escribiendo el código en el campo 'Código' + Enter.
  5. Captura el resultado y reporta qué quedó cargado y si saltó algún diálogo.
"""
import sys, os, json, time
import win32gui
from PIL import ImageGrab
from pywinauto import Application
import flujo_precio as fp

CODIGO = sys.argv[1] if len(sys.argv) > 1 else "00-002-024"
DIR = os.path.dirname(os.path.abspath(__file__))
puntos = json.load(open(os.path.join(DIR, "calib_puntos.json"), encoding="utf-8"))


def shot(hwnd, name):
    fp._win(hwnd).set_focus(); time.sleep(0.3)
    L, T, R, B = win32gui.GetWindowRect(hwnd)
    ImageGrab.grab(bbox=(L, T, R, B)).save(os.path.join(DIR, name))
    print(f"   [shot] {name} ({R-L}x{B-T})")


def cerrar_todo():
    for _ in range(4):
        h = fp._find_hwnd("TMessageForm")
        if h:
            try:
                fp._win(h).type_keys("{ENTER}")
            except Exception:
                pass
            time.sleep(0.4)
    h = fp._find_hwnd(fp.BUSQ_CLASS)
    if h:
        try:
            fp._win(h).child_window(title="&Salir", class_name="TFlatButton").click_input()
            time.sleep(0.6)
        except Exception:
            pass
    h = fp._find_hwnd(fp.FICHA_CLASS)
    if h:
        try:
            # botón Salir de la ficha (icono derecha) via calib no lo tenemos; usa Esc
            fp._win(h).type_keys("{ESC}")
            time.sleep(0.6)
        except Exception:
            pass


def ficha_edits(fi):
    out = []
    for cls in ("THybridEdit", "TEdit"):
        for c in fi.descendants(class_name=cls):
            t = (c.window_text() or "").strip()
            if t:
                out.append(t)
    return out[:10]


print("[1] cerrando ventanas residuales...")
cerrar_todo()

print("[2] abriendo Ficha desde 'Items de Inventario'...")
hmain = fp._find_hwnd(fp.MAIN_CLASS)
main = fp._win(hmain)
main.set_focus(); time.sleep(0.3)
try:
    btn = main.child_window(title="Items de Inventario", class_name="TAdvGlassButton")
    btn.wait("exists visible", timeout=2)
except Exception:
    fp._click_punto(puntos, "menu_inventario", fp.MAIN_CLASS)
    time.sleep(0.6)
    btn = main.child_window(title="Items de Inventario", class_name="TAdvGlassButton")
    btn.wait("exists visible", timeout=8)
btn.click_input()
hf = fp._wait_for(fp.FICHA_CLASS, desc="Ficha")
time.sleep(0.6)
print("   Ficha abierta.")
shot(hf, "flujo_1_ficha_fresca.png")

# ¿se abrió una búsqueda automáticamente?
hb = fp._find_hwnd(fp.BUSQ_CLASS)
print(f"[3] ¿búsqueda auto-abierta al abrir ficha? {bool(hb)}")
if hb:
    shot(hb, "flujo_2_busqueda_auto.png")

print("[4] escribiendo código directo en el campo 'Código'...")
fi = fp._win(hf)
fi.set_focus()
edits = [(c.rectangle().top, c.rectangle().left, c) for c in fi.descendants(class_name="THybridEdit")]
edits.sort(key=lambda t: (t[0], t[1]))
cf = edits[0][2]
print(f"   campo código en L{edits[0][1]} T{edits[0][0]}")
cf.click_input(); time.sleep(0.3)
cf.type_keys("^a{DELETE}", set_foreground=False)
cf.type_keys(CODIGO, with_spaces=False, set_foreground=False, pause=0.06)
time.sleep(0.4)
cf.type_keys("{ENTER}", set_foreground=False)
time.sleep(1.5)

err = fp._find_hwnd("TMessageForm")
if err:
    shot(err, "flujo_3_error.png")
    try:
        print(f"   ERROR dialog textos: {fp._win(err).texts()}")
    except Exception:
        pass

hf = fp._find_hwnd(fp.FICHA_CLASS)
if hf:
    fi = fp._win(hf)
    e = ficha_edits(fi)
    ok = any(CODIGO.lower() == x.lower() or CODIGO.lower() in x.lower() for x in e)
    print(f"[5] ficha después: {e}")
    print(f"    ¿cargó {CODIGO}? {'SÍ' if ok else 'NO'}")
    shot(hf, "flujo_4_resultado.png")
else:
    print("[5] la ficha ya no está abierta.")
