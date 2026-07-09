"""_inspeccionar_login.py — Vuelca los controles de la ventana de login (SOLO LECTURA)."""
import time
import win32gui
from PIL import ImageGrab
import flujo_precio as fp

LOGIN = "TFUserPassMainForm"
h = fp._find_hwnd(LOGIN)
if not h:
    raise SystemExit("Login no visible.")
w = fp._win(h)
L, T, R, B = win32gui.GetWindowRect(h)
print(f"login rect=({L},{T},{R},{B})")

print("\n=== edits (usuario/clave) ===")
for cls in ("THybridEdit", "TEdit", "TMaskEdit", "TcxTextEdit", "TDBEdit"):
    for c in w.descendants(class_name=cls):
        r = c.rectangle()
        pw = ""
        try:
            style = win32gui.GetWindowLong(c.handle, win32gui.GWL_STYLE)
            pw = " [PASSWORD]" if (style & 0x0020) else ""   # ES_PASSWORD
        except Exception:
            pass
        print(f"  {cls} text={c.window_text()!r} rect=({r.left},{r.top}) size=({r.right-r.left}x{r.bottom-r.top}){pw}")

print("\n=== botones ===")
for cls in ("TFlatButton", "TBitBtn", "TButton", "TAdvGlassButton", "TSpeedButton"):
    for b in w.descendants(class_name=cls):
        t = (b.window_text() or "").strip()
        r = b.rectangle()
        if t or cls in ("TBitBtn", "TSpeedButton"):
            print(f"  {cls} {t!r} rect=({r.left},{r.top})")

print("\n=== combos (por si el usuario es un desplegable) ===")
for cls in ("TComboBox", "TISComboBox", "TcxComboBox"):
    for c in w.descendants(class_name=cls):
        r = c.rectangle()
        print(f"  {cls} text={c.window_text()!r} rect=({r.left},{r.top})")

ImageGrab.grab(bbox=(L, T, R, B)).save("login.png")
print("\n[shot] login.png")
