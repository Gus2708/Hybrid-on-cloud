"""
diag_visual_precio.py — Diagnóstico VISUAL del campo con-impuesto (NO guarda).
Trae el diálogo al frente, captura ANTES, teclea el valor con el separador indicado,
captura DESPUÉS, lee ambos campos, y descarta con 'Salir'.

Uso:
    python diag_visual_precio.py 13,50     # coma (como el numérico venezolano)
    python diag_visual_precio.py 13.50     # punto
"""
import os, sys, time
import win32gui
from PIL import ImageGrab
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import flujo_precio as fp
import hybrid_price_writer as hpw
import realinput as ri

DIR = os.path.dirname(os.path.abspath(__file__))
VALOR = sys.argv[1] if len(sys.argv) > 1 else "13,50"


def _focus(hwnd):
    try: fp._win(hwnd).set_focus()
    except Exception: pass
    try: win32gui.SetForegroundWindow(hwnd)
    except Exception: pass
    time.sleep(0.3)


def shot(hwnd, name):
    _focus(hwnd)
    L, T, R, B = win32gui.GetWindowRect(hwnd)
    ImageGrab.grab(bbox=(L, T, R, B)).save(os.path.join(DIR, name))
    print(f"  [shot] {name}")


def om_fields(dlg):
    panel = dlg.child_window(title="POtrasMonedas", class_name="TPanel")
    out = []
    for c in panel.descendants(class_name="THybridEditNumber"):
        r = c.rectangle()
        if r.left < 900:
            out.append((r.top, c))
    out.sort(key=lambda t: t[0])
    return out[0][1], out[-1][1]   # (sin, con)


hd = fp._find_hwnd(fp.PRECIOS_CLASS)
if not hd:
    # abrir desde la ficha
    hf = fp._find_hwnd(fp.FICHA_CLASS)
    if not hf:
        raise SystemExit("Carga un producto y abre Costos y Precios primero.")
    _focus(hf)
    fi = fp._win(hf)
    b = fi.child_window(title="Costos &y Precios", class_name="TFlatButton")
    r = b.rectangle(); ri.click((r.left+r.right)//2,(r.top+r.bottom)//2)
    hd = fp._wait_for(fp.PRECIOS_CLASS, desc="Costos y Precios"); time.sleep(0.6)

dlg = fp._win(hd)
sin_f, con_f = om_fields(dlg)
print(f"ANTES: sin={sin_f.window_text()!r}  con={con_f.window_text()!r}")
shot(hd, "vprecio_antes.png")

_focus(hd)
r = con_f.rectangle()
cx, cy = (r.left+r.right)//2, (r.top+r.bottom)//2
print(f"click campo CON-impuesto en ({cx},{cy}) y teclear {VALOR!r}...")
ri.click(cx, cy); time.sleep(0.3)
ri.select_all_field()
ri.type_text(VALOR)
time.sleep(0.3)
print(f"  (antes de Enter) sin={sin_f.window_text()!r}  con={con_f.window_text()!r}")
shot(hd, "vprecio_tecleado.png")

ri.press("ENTER"); time.sleep(0.6)
print(f"DESPUÉS de Enter: sin={sin_f.window_text()!r}  con={con_f.window_text()!r}")
shot(hd, "vprecio_despues.png")

# descartar SIN guardar
try:
    dlg.child_window(title="Salir", class_name="TButton").click_input()
    print("Descartado con 'Salir' (no se guardó).")
except Exception as e:
    print("No pude Salir:", e)
