"""shot_busqueda.py — Abre búsqueda, filtra por código y captura la ventana a PNG."""
import sys, os, json, time
import win32gui
from PIL import ImageGrab
import flujo_precio as fp

CODIGO = sys.argv[1] if len(sys.argv) > 1 else "00-002-024"
DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(DIR, "shot_busqueda.png")
puntos = json.load(open(os.path.join(DIR, "calib_puntos.json"), encoding="utf-8"))

# cerrar cualquier búsqueda previa
h = fp._find_hwnd(fp.BUSQ_CLASS)
if h:
    try:
        fp._win(h).child_window(title="&Salir", class_name="TFlatButton").click_input()
        time.sleep(0.6)
    except Exception:
        pass

fp._click_punto(puntos, "ficha_buscar", fp.FICHA_CLASS)
hbusq = fp._wait_for(fp.BUSQ_CLASS, desc="búsqueda")
busq = fp._win(hbusq)
busq.set_focus()

combo = busq.child_window(class_name="TComboBox")
print("combo:", combo.window_text())

edit = busq.child_window(class_name="THybridEdit")
edit.click_input()
time.sleep(0.25)
edit.type_keys("^a{DELETE}", set_foreground=False)
edit.type_keys(CODIGO, with_spaces=False, set_foreground=False, pause=0.06)
time.sleep(1.8)

busq.set_focus()
time.sleep(0.3)
L, T, R, B = win32gui.GetWindowRect(hbusq)
img = ImageGrab.grab(bbox=(L, T, R, B))
img.save(OUT)
print(f"guardado: {OUT}  ({R-L}x{B-T})")
print(f"edit dice: {edit.window_text()!r}")
