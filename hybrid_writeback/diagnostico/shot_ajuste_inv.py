"""shot_ajuste_inv.py — Abre 'Ajustes de inventario' desde el menú y lo inspecciona.
NO guarda nada. Vuelca ventanas VCL nuevas + screenshot de pantalla completa."""
import os, sys, time
import win32gui, win32process
from PIL import ImageGrab
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import flujo_precio as fp
import realinput as ri

DIR = os.path.dirname(os.path.abspath(__file__))


def _focus(hwnd):
    try: fp._win(hwnd).set_focus()
    except Exception: pass
    try: win32gui.SetForegroundWindow(hwnd)
    except Exception: pass
    time.sleep(0.25)


def vcl_windows():
    out = []
    def cb(h, _):
        if not win32gui.IsWindowVisible(h): return
        cls = win32gui.GetClassName(h) or ""
        txt = win32gui.GetWindowText(h) or ""
        if cls.startswith(("TF", "TT", "TForm")):
            out.append((h, cls, txt))
    win32gui.EnumWindows(cb, None)
    return out

# cerrar ficha/busqueda/errores
for _ in range(4):
    h = fp._find_hwnd("TMessageForm")
    if h:
        try: fp._win(h).type_keys("{ENTER}")
        except Exception: pass
        time.sleep(0.3)
h = fp._find_hwnd(fp.BUSQ_CLASS)
if h:
    try: fp._win(h).child_window(title="&Salir", class_name="TFlatButton").click_input(); time.sleep(0.5)
    except Exception: pass
h = fp._find_hwnd(fp.FICHA_CLASS)
if h:
    try:
        # botón Salir de la ficha (owner-drawn, ~rel 365,60); mejor ESC
        fp._win(h).type_keys("{ESC}"); time.sleep(0.5)
    except Exception: pass

print("VCL antes:", [(c, t[:30]) for _, c, t in vcl_windows()])

hmain = fp._find_hwnd(fp.MAIN_CLASS)
main = fp._win(hmain); _focus(hmain)
try:
    b = main.child_window(title="Ajustes de inventario", class_name="TAdvGlassButton")
    b.wait("exists visible", timeout=3)
    r = b.rectangle()
    ri.click((r.left+r.right)//2, (r.top+r.bottom)//2)
    print("clic 'Ajustes de inventario'")
except Exception as e:
    print("no encontré el botón por win32:", e)

time.sleep(2.5)
print("VCL después:", [(c, t[:40]) for _, c, t in vcl_windows()])
ImageGrab.grab().save(os.path.join(DIR, "ajuste_inv.png"))
print("[shot] ajuste_inv.png")
