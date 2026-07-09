"""shot_busqueda2.py — Filtra, EJECUTA la búsqueda (Enter) y captura la grilla."""
import sys, os, json, time
import win32gui
from PIL import ImageGrab
import flujo_precio as fp

CODIGO = sys.argv[1] if len(sys.argv) > 1 else "00-002-024"
DIR = os.path.dirname(os.path.abspath(__file__))
puntos = json.load(open(os.path.join(DIR, "calib_puntos.json"), encoding="utf-8"))

hbusq = fp._find_hwnd(fp.BUSQ_CLASS)
if not hbusq:
    fp._click_punto(puntos, "ficha_buscar", fp.FICHA_CLASS)
    hbusq = fp._wait_for(fp.BUSQ_CLASS, desc="búsqueda")
busq = fp._win(hbusq)
busq.set_focus()

edit = busq.child_window(class_name="THybridEdit")
edit.click_input()
time.sleep(0.25)
edit.type_keys("^a{DELETE}", set_foreground=False)
edit.type_keys(CODIGO, with_spaces=False, set_foreground=False, pause=0.06)
time.sleep(0.6)

# EJECUTAR la búsqueda con Enter (sin tocar la grilla)
edit.type_keys("{ENTER}", set_foreground=False)
time.sleep(1.8)

still = fp._find_hwnd(fp.BUSQ_CLASS)
print(f"búsqueda sigue abierta tras Enter: {bool(still)}")
if still:
    busq = fp._win(still)
    busq.set_focus()
    time.sleep(0.3)
    L, T, R, B = win32gui.GetWindowRect(still)
    ImageGrab.grab(bbox=(L, T, R, B)).save(os.path.join(DIR, "shot_busqueda2.png"))
    print("guardado shot_busqueda2.png")
    for sb in busq.descendants(class_name="TStatusBar"):
        print("statusbar:", sb.texts())
else:
    # se cerró: reportar qué cargó en la ficha
    hf = fp._find_hwnd(fp.FICHA_CLASS)
    fi = fp._win(hf)
    txt = []
    for cls in ("THybridEdit", "TEdit"):
        for c in fi.descendants(class_name=cls):
            t = (c.window_text() or "").strip()
            if t:
                txt.append(t)
    print("ficha tras cerrar:", txt[:8])
