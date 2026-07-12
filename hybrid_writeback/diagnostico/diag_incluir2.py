"""diag_incluir2.py — En Ajustes de Precios: código en 'Producto a Incluir' + ENTER,
y si no, botón 'Iniciar'. Ve si el producto entra a la grilla. NO guarda."""
import sys, os, time
import win32gui, win32process
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


def grid_texts(dlg):
    for cls in ("TDBGrid", "THybridGrid", "TStringGrid", "TAdvStringGrid", "TDrawGrid"):
        for g in dlg.descendants(class_name=cls):
            try:
                return cls, [t for t in g.texts() if t][:20]
            except Exception:
                return cls, ["(no legible)"]
    return None, []


h = find_hwnd(CLS)
if not h:
    raise SystemExit("Módulo no abierto.")
pid = win32process.GetWindowThreadProcessId(h)[1]
dlg = Application(backend="win32").connect(process=pid, timeout=5).window(handle=h)
dlg.set_focus()

incluir = None
for c in dlg.descendants(class_name="THybridEdit"):
    r = c.rectangle()
    if 200 < r.top < 260 and r.left < 400:
        incluir = c; break
print(f"campo incluir: {incluir.rectangle() if incluir else None}")

incluir.click_input(); time.sleep(0.3)
incluir.type_keys("^a{DELETE}", set_foreground=False)
incluir.type_keys(CODIGO, with_spaces=False, set_foreground=False, pause=0.06)
time.sleep(0.3)
incluir.type_keys("{ENTER}", set_foreground=False)
time.sleep(1.2)

cls, txts = grid_texts(dlg)
print(f"[tras ENTER] grid {cls}: {txts}")

if not any(CODIGO in t for t in txts):
    # probar botón Iniciar
    try:
        dlg.child_window(title="Iniciar", class_name="TBitBtn").click_input()
    except Exception:
        try:
            dlg.child_window(title="Iniciar").click_input()
        except Exception as e:
            print("no pude 'Iniciar':", e)
    print("clic 'Iniciar'")
    time.sleep(2.0)
    cls, txts = grid_texts(dlg)
    print(f"[tras Iniciar] grid {cls}: {txts}")

err = find_hwnd("TMessageForm")
print(f"error TMessageForm: {bool(err)}")
dlg.set_focus(); time.sleep(0.3)
L, T, R, B = win32gui.GetWindowRect(h)
ImageGrab.grab(bbox=(L, T, R, B)).save(os.path.join(DIR, "shot_incluir2.png"))
print("guardado shot_incluir2.png")
