"""diag_con2.py — Enfoca con-impuesto, BORRA duro y teclea por el numérico. Verifica
que quede el valor correcto (con decimal). Descarta con 'Salir' (NO guarda)."""
import os, sys, time
import win32gui
from PIL import ImageGrab
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import flujo_precio as fp
import realinput as ri

DIR = os.path.dirname(os.path.abspath(__file__))
VALOR = sys.argv[1] if len(sys.argv) > 1 else "13.50"


def _focus_win(hwnd):
    try: fp._win(hwnd).set_focus()
    except Exception: pass
    try: win32gui.SetForegroundWindow(hwnd)
    except Exception: pass
    time.sleep(0.3)


def om_fields(dlg):
    panel = dlg.child_window(title="POtrasMonedas", class_name="TPanel")
    out = []
    for c in panel.descendants(class_name="THybridEditNumber"):
        r = c.rectangle()
        if r.left < 900:
            out.append((r.top, c))
    out.sort(key=lambda t: t[0])
    return out[0][1], out[-1][1]


hd = fp._find_hwnd(fp.PRECIOS_CLASS)
if not hd:
    hf = fp._find_hwnd(fp.FICHA_CLASS)
    if not hf:
        raise SystemExit("Abre Costos y Precios con un producto cargado.")
    _focus_win(hf)
    b = fp._win(hf).child_window(title="Costos &y Precios", class_name="TFlatButton")
    r = b.rectangle(); ri.click((r.left+r.right)//2,(r.top+r.bottom)//2)
    hd = fp._wait_for(fp.PRECIOS_CLASS, desc="Costos y Precios"); time.sleep(0.6)

_focus_win(hd)
dlg = fp._win(hd)
sin_f, con_f = om_fields(dlg)
print(f"ANTES: sin={sin_f.window_text()!r}  con={con_f.window_text()!r}")

# enfocar con: clic real bajo dentro del campo + set_focus de respaldo
r = con_f.rectangle()
cx = (r.left + r.right) // 2
ri.click(cx, r.bottom - 4); time.sleep(0.2)
try: con_f.set_focus()
except Exception: pass
time.sleep(0.2)

ri.clear_hard()
print(f"tras borrar: con={con_f.window_text()!r}")
ri.type_number(VALOR)
time.sleep(0.2)
print(f"tras teclear {VALOR!r} (numérico): sin={sin_f.window_text()!r}  con={con_f.window_text()!r}")
ri.press("ENTER"); time.sleep(0.6)
print(f"tras ENTER: sin={sin_f.window_text()!r}  con={con_f.window_text()!r}")

_focus_win(hd)
L, T, R, B = win32gui.GetWindowRect(hd)
ImageGrab.grab(bbox=(L, T, R, B)).save(os.path.join(DIR, "con2_despues.png"))
print("[shot] con2_despues.png")

try:
    dlg.child_window(title="Salir", class_name="TButton").click_input()
    print("Descartado con 'Salir' (no se guardó).")
except Exception as e:
    print("No pude Salir:", e)
