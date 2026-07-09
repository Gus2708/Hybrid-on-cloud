"""
diag_write_con.py — Mete el foco SÍ O SÍ en 'Precio con impuesto' y reemplaza el valor.
Instrumenta qué control queda enfocado y descarta con 'Salir' (NO guarda).
"""
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
VALOR = sys.argv[1] if len(sys.argv) > 1 else "13,50"


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
    return out[0][1], out[-1][1]   # (sin, con)


hd = fp._find_hwnd(fp.PRECIOS_CLASS)
if not hd:
    hf = fp._find_hwnd(fp.FICHA_CLASS)
    if not hf:
        raise SystemExit("Abre Costos y Precios (con un producto cargado) primero.")
    _focus_win(hf)
    b = fp._win(hf).child_window(title="Costos &y Precios", class_name="TFlatButton")
    r = b.rectangle(); ri.click((r.left+r.right)//2,(r.top+r.bottom)//2)
    hd = fp._wait_for(fp.PRECIOS_CLASS, desc="Costos y Precios"); time.sleep(0.6)

_focus_win(hd)
dlg = fp._win(hd)
sin_f, con_f = om_fields(dlg)
sin_h, con_h = sin_f.handle, con_f.handle
print(f"handles -> sin={sin_h} con={con_h}")
print(f"ANTES: sin={sin_f.window_text()!r}  con={con_f.window_text()!r}")


def quien_tiene_foco():
    f = win32gui.GetFocus()
    if f == con_h: return "CON"
    if f == sin_h: return "SIN"
    return f"otro({f})"


# --- Estrategia 1: set_focus del control (pywinauto) ---
try:
    con_f.set_focus()
    time.sleep(0.3)
    print(f"[E1 set_focus] foco={quien_tiene_foco()}")
except Exception as e:
    print("[E1] error:", e)

# --- Estrategia 2: clic real en el centro del campo con ---
r = con_f.rectangle()
cx, cy = (r.left+r.right)//2, (r.top+r.bottom)//2
ri.click(cx, cy); time.sleep(0.3)
print(f"[E2 click centro ({cx},{cy})] foco={quien_tiene_foco()}")

# --- Estrategia 3: clic real más abajo dentro del campo con ---
cy2 = r.bottom - 4
ri.click(cx, cy2); time.sleep(0.3)
print(f"[E3 click bajo ({cx},{cy2})] foco={quien_tiene_foco()}")

# Elegir la que haya dejado el foco en CON; si ninguna, forzar set_focus otra vez
if quien_tiene_foco() != "CON":
    try:
        con_f.set_focus(); time.sleep(0.2)
    except Exception:
        pass
print(f"FOCO FINAL antes de escribir: {quien_tiene_foco()}")

# --- BORRAR el contenido de forma dura y verificar ---
ri.press("END")
for _ in range(12):
    ri.press("BACKSPACE")
time.sleep(0.2)
print(f"tras borrar: con={con_f.window_text()!r}  (foco={quien_tiene_foco()})")

# --- Escribir el nuevo valor (coma) ---
ri.type_text(VALOR)
time.sleep(0.2)
print(f"tras teclear {VALOR!r}: sin={sin_f.window_text()!r}  con={con_f.window_text()!r}")
ri.press("ENTER"); time.sleep(0.6)
print(f"tras ENTER: sin={sin_f.window_text()!r}  con={con_f.window_text()!r}")

_focus_win(hd)
L, T, R, B = win32gui.GetWindowRect(hd)
ImageGrab.grab(bbox=(L, T, R, B)).save(os.path.join(DIR, "vcon_despues.png"))
print("[shot] vcon_despues.png")

try:
    dlg.child_window(title="Salir", class_name="TButton").click_input()
    print("Descartado con 'Salir' (no se guardó).")
except Exception as e:
    print("No pude Salir:", e)
