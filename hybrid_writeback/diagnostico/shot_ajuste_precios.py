"""shot_ajuste_precios.py — Abre 'Ajustes de precios' desde el menú y captura (no guarda)."""
import os, time
import win32gui
from PIL import ImageGrab
from pywinauto import Desktop
import flujo_precio as fp

DIR = os.path.dirname(os.path.abspath(__file__))

# cerrar ficha/busqueda/errores residuales
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
    try: fp._win(h).type_keys("{ESC}"); time.sleep(0.5)
    except Exception: pass

hmain = fp._find_hwnd(fp.MAIN_CLASS)
main = fp._win(hmain)
main.set_focus(); time.sleep(0.3)

# 'Ajustes de precios' aparece como Pane (UIA) / TAdvGlassButton (win32). Intento por título.
clicked = False
try:
    b = main.child_window(title="Ajustes de precios", class_name="TAdvGlassButton")
    b.wait("exists visible", timeout=2)
    b.click_input(); clicked = True
    print("clic 'Ajustes de precios' (win32).")
except Exception as e:
    print("no por win32:", e)

if not clicked:
    # vía UIA por si es owner-drawn
    win = Desktop(backend="uia").window(handle=hmain)
    try:
        pane = win.child_window(title="Ajustes de precios", control_type="Pane")
        r = pane.rectangle()
        from pywinauto.mouse import click
        click(button="left", coords=((r.left+r.right)//2, (r.top+r.bottom)//2))
        clicked = True
        print("clic 'Ajustes de precios' (UIA centro).")
    except Exception as e:
        print("no por UIA:", e)

time.sleep(2.0)

# capturar cualquier ventana nueva top-level del proceso Hybrid
def enum_top():
    import win32process
    out = []
    def cb(h, _):
        if not win32gui.IsWindowVisible(h): return
        cls = win32gui.GetClassName(h) or ""
        txt = win32gui.GetWindowText(h) or ""
        try:
            _, pid = win32process.GetWindowThreadProcessId(h)
        except Exception:
            return
        out.append((h, cls, txt, pid))
    win32gui.EnumWindows(cb, None)
    return out

for h, cls, txt, pid in enum_top():
    if cls not in (fp.MAIN_CLASS,) and (txt or cls.startswith("TF") or "juste" in txt.lower()):
        if cls in ("TApplication", "TitleBar"): continue
        print(f"ventana: cls={cls!r} title={txt!r}")

# captura de pantalla completa (la ventana de ajuste puede ser hija embebida)
ImageGrab.grab().save(os.path.join(DIR, "shot_ajuste_precios.png"))
print("guardado shot_ajuste_precios.png (pantalla completa)")
