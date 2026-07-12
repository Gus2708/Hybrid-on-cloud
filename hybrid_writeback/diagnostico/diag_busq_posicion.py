"""diag_busq_posicion.py — Teclea un código NO-primero en la búsqueda y vuelca todo
lo legible (DETALLES, statusbar, grid por UIA) para hallar la señal de 'ya posicionó'.
NO selecciona; cierra con Salir."""
import os, sys, time
import win32gui
from PIL import ImageGrab
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import flujo_precio as fp
import realinput as ri
from pywinauto import Desktop

DIR = os.path.dirname(os.path.abspath(__file__))
CODIGO = sys.argv[1] if len(sys.argv) > 1 else "03630"
MODIFICAR_REL = (122, 62)


def _focus(hwnd):
    try: fp._win(hwnd).set_focus()
    except Exception: pass
    try: win32gui.SetForegroundWindow(hwnd)
    except Exception: pass
    time.sleep(0.25)


# asegurar ficha
hf = fp._find_hwnd(fp.FICHA_CLASS)
if not hf:
    hmain = fp._find_hwnd(fp.MAIN_CLASS)
    main = fp._win(hmain); main.set_focus(); time.sleep(0.3)
    b = main.child_window(title="Items de Inventario", class_name="TAdvGlassButton")
    r = b.rectangle(); ri.click((r.left+r.right)//2,(r.top+r.bottom)//2)
    hf = fp._wait_for(fp.FICHA_CLASS, desc="Ficha")

_focus(hf)
L, T, _, _ = win32gui.GetWindowRect(hf)
ri.click(L + MODIFICAR_REL[0], T + MODIFICAR_REL[1])
hbusq = fp._wait_for(fp.BUSQ_CLASS, desc="Busqueda")
busq = fp._win(hbusq); time.sleep(0.5)
_focus(hbusq)

ed = busq.child_window(class_name="THybridEdit", found_index=0)
r = ed.rectangle(); ri.click((r.left+r.right)//2,(r.top+r.bottom)//2); time.sleep(0.3)
ri.clear_hard()
ri.type_number(CODIGO)   # los códigos con letras (ZA021) NO sirven por numérico; este es numérico
time.sleep(0.3)
print(f"campo buscar dice: {ed.window_text()!r}")
ri.press("ENTER")

# muestrear cada 0.5s qué se puede leer, por ~4s
for k in range(8):
    time.sleep(0.5)
    if not fp._find_hwnd(fp.BUSQ_CLASS):
        print(f"[{k}] búsqueda se cerró sola")
        break
    # statusbar
    sb_txt = []
    for sb in busq.descendants(class_name="TStatusBar"):
        sb_txt += [t for t in sb.texts() if t]
    # paneles con texto (DETALLES suele mostrar el producto seleccionado)
    pan = []
    for p in busq.descendants(class_name="TPanel"):
        t = (p.window_text() or "").strip()
        if t and t not in ("Panel",):
            pan.append(t)
    print(f"[{k}] status={sb_txt} paneles={pan[:6]}")

# intento UIA: leer la fila seleccionada del grid
try:
    uwin = Desktop(backend="uia").window(handle=hbusq)
    # buscar Table/DataItem seleccionados
    tabs = uwin.descendants(control_type="Table")
    print(f"UIA tables: {len(tabs)}")
    for t in tabs[:1]:
        rows = t.descendants(control_type="DataItem") or t.descendants(control_type="ListItem")
        print(f"  filas UIA: {len(rows)} (muestro 3)")
        for rr in rows[:3]:
            print("   ->", rr.window_text())
except Exception as e:
    print("UIA no pudo leer grid:", str(e)[:120])

# screenshot
if fp._find_hwnd(fp.BUSQ_CLASS):
    LL,TT,RR,BB = win32gui.GetWindowRect(hbusq)
    ImageGrab.grab(bbox=(LL,TT,RR,BB)).save(os.path.join(DIR, "busq_posicion.png"))
    print("[shot] busq_posicion.png")
    # cerrar sin seleccionar
    try:
        busq.child_window(title="&Salir", class_name="TFlatButton").click_input()
    except Exception:
        pass
