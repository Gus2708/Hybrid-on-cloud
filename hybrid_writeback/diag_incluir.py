"""diag_incluir.py — Prueba el campo 'Producto a Incluir' del módulo Ajustes de Precios.
Escribe un código, dispara (F1/Enter) y ve si el producto entra a la grilla. NO guarda."""
import sys, os, time
import win32gui
from PIL import ImageGrab
from pywinauto import Application

CODIGO = sys.argv[1] if len(sys.argv) > 1 else "00-002-024"
DIR = os.path.dirname(os.path.abspath(__file__))
CLS = "TFormAjustePrecioCosto"


def find_hwnd(cls):
    out = []
    win32gui.EnumWindows(lambda h, _: out.append(h) if win32gui.IsWindowVisible(h)
                         and win32gui.GetClassName(h) == cls else None, None)
    return out[0] if out else None


h = find_hwnd(CLS)
if not h:
    raise SystemExit("El módulo 'Ajustes de Precios' no está abierto.")
import win32process
pid = win32process.GetWindowThreadProcessId(h)[1]
app = Application(backend="win32").connect(process=pid, timeout=5)
dlg = app.window(handle=h)
dlg.set_focus()

# volcar edits para ubicar 'Producto a Incluir' (por posición: y~230, x izq)
print("=== edits del módulo ===")
edits = []
for cls in ("THybridEdit", "TEdit", "TDBEdit"):
    for c in dlg.descendants(class_name=cls):
        r = c.rectangle()
        edits.append((r.top, r.left, r.right, c, cls))
        print(f"  {cls} L{r.left} T{r.top} R{r.right} texto={c.window_text()!r}")

# 'Producto a Incluir' es el edit ancho a la izquierda, ~y230 (bajo la etiqueta)
cand = [e for e in edits if 200 < e[0] < 260 and e[1] < 400]
if not cand:
    cand = sorted(edits, key=lambda e: abs(e[0]-230))[:1]
incluir = cand[0][3]
r = incluir.rectangle()
print(f"\n'Producto a Incluir' -> L{r.left} T{r.top}")

incluir.click_input(); time.sleep(0.3)
incluir.type_keys("^a{DELETE}", set_foreground=False)
incluir.type_keys(CODIGO, with_spaces=False, set_foreground=False, pause=0.06)
time.sleep(0.4)
print(f"escrito: {incluir.window_text()!r}")

# probar F1 (hay un botón 'F1') y si no, Enter
before = ImageGrab.grab()
try:
    dlg.child_window(title="F1", class_name="TButton").click_input()
    print("clic botón F1")
except Exception:
    incluir.type_keys("{F1}", set_foreground=False)
    print("tecla F1")
time.sleep(1.2)

# ¿apareció diálogo de error?
err = find_hwnd("TMessageForm")
print(f"error TMessageForm: {bool(err)}")

dlg.set_focus(); time.sleep(0.3)
L, T, R, B = win32gui.GetWindowRect(h)
ImageGrab.grab(bbox=(L, T, R, B)).save(os.path.join(DIR, "shot_incluir.png"))
print("guardado shot_incluir.png")
