"""diag_insertar_item.py — En la ventana de Ajustes, pulsa 'Insertar ítems' para ver
cómo se agrega un producto. NO guarda; cierra lo que abra y sale con 'Salir' (descarta)."""
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
AJU_CLASS = "TFormHTransaccion_Ajustes"


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


ha = fp._find_hwnd(AJU_CLASS)
if not ha:
    raise SystemExit("La ventana de Ajustes de inventario no está abierta.")
_focus(ha)
aj = fp._win(ha)

# volcar botones y campos del encabezado
print("=== botones (TBitBtn/TButton/TFlatButton) ===")
for cls in ("TBitBtn", "TButton", "TFlatButton"):
    for b in aj.descendants(class_name=cls):
        t = (b.window_text() or "").strip()
        if t:
            r = b.rectangle()
            print(f"  {cls} '{t}' rect=({r.left},{r.top},{r.right},{r.bottom})")

print("\n=== clic 'Insertar ítems' ===")
try:
    b = aj.child_window(title="Insertar ítems", class_name="TBitBtn")
    r = b.rectangle()
    ri.click((r.left+r.right)//2, (r.top+r.bottom)//2)
except Exception as e:
    # probar por texto sin acento / otras clases
    done = False
    for cls in ("TBitBtn", "TButton", "TFlatButton"):
        for b in aj.descendants(class_name=cls):
            if "nsertar" in (b.window_text() or ""):
                r = b.rectangle(); ri.click((r.left+r.right)//2,(r.top+r.bottom)//2); done = True; break
        if done: break
    print("via fallback:", done, e)
time.sleep(2.0)

print("VCL tras Insertar:", [(c, t[:40]) for _, c, t in vcl_windows() if c not in (AJU_CLASS, fp.MAIN_CLASS)])
ImageGrab.grab().save(os.path.join(DIR, "insertar_item.png"))
print("[shot] insertar_item.png")
