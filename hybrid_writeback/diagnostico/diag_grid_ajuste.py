"""
diag_grid_ajuste.py — Abre Ajustes, carga un producto en la grilla, e intenta LEER
la grilla (código/existencia/diferencia) por varios métodos. Descarta sin guardar.
NO totaliza (no crea documento).
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
from pywinauto import Desktop

DIR = os.path.dirname(os.path.abspath(__file__))
COD = sys.argv[1] if len(sys.argv) > 1 else "00-002-024"
AJU = "TFormHTransaccion_Ajustes"

# offsets de columna dentro del control TAdvStringGrid (de la grabación)
COD_DX, ROW_DY = 196, 40
CONTEO_DX = 860


def _focus(hwnd):
    try: fp._win(hwnd).set_focus()
    except Exception: pass
    try: win32gui.SetForegroundWindow(hwnd)
    except Exception: pass
    time.sleep(0.25)


def abrir_ajustes():
    import json
    ha = fp._find_hwnd(AJU)
    if ha:
        return ha
    hmain = fp._find_hwnd(fp.MAIN_CLASS)
    main = fp._win(hmain); _focus(hmain)
    # ¿ya se ve el botón? si no, abrir el submenú Inventario (panel izquierdo)
    try:
        b = main.child_window(title="Ajustes de inventario", class_name="TAdvGlassButton")
        b.wait("exists visible", timeout=1.5)
    except Exception:
        puntos = json.load(open(os.path.join(DIR, "calib_puntos.json"), encoding="utf-8"))
        rel = puntos["menu_inventario"]["rel"]
        L, T, _, _ = win32gui.GetWindowRect(hmain)
        ri.click(L + rel[0], T + rel[1])       # menú lateral Inventario
        time.sleep(0.8)
        b = main.child_window(title="Ajustes de inventario", class_name="TAdvGlassButton")
        b.wait("exists visible", timeout=6)
    r = b.rectangle(); ri.click((r.left+r.right)//2,(r.top+r.bottom)//2)
    # esperar la ventana
    t0 = time.time()
    while time.time()-t0 < 15:
        ha = fp._find_hwnd(AJU)
        if ha:
            time.sleep(1.0)
            return ha
        time.sleep(0.3)
    raise SystemExit("No abrió la ventana de Ajustes.")


ha = abrir_ajustes()
_focus(ha)
aj = fp._win(ha)
# puede haber 2 TAdvStringGrid: elegir la más grande (la grilla Principal de ítems)
grids = aj.descendants(class_name="TAdvStringGrid")
def _area(c):
    r = c.rectangle(); return (r.right-r.left)*(r.bottom-r.top)
grid = max(grids, key=_area)
gr = grid.rectangle()
print(f"grids={len(grids)}  grilla principal rect=({gr.left},{gr.top},{gr.right},{gr.bottom})")

# clic en celda Código (1a fila) y teclear código
ri.click(gr.left + COD_DX, gr.top + ROW_DY); time.sleep(0.3)
ri.type_code(COD)
time.sleep(0.3)
ri.press("ENTER"); time.sleep(0.8)
ri.press("ENTER"); time.sleep(0.8)   # confirma/carga

# screenshot
_focus(ha)
L,T,R,B = win32gui.GetWindowRect(ha)
ImageGrab.grab(bbox=(L,T,R,B)).save(os.path.join(DIR, "grid_ajuste.png"))
print("[shot] grid_ajuste.png")

# intentos de LECTURA de la grilla
print("\n--- pywinauto texts() del grid ---")
try:
    txts = [t for t in grid.texts() if t]
    print(txts[:30])
except Exception as e:
    print("no:", e)

print("\n--- THybridEditNumber / edits visibles en la ventana ---")
for cls in ("THybridEditNumber", "THybridEdit", "TEdit"):
    for c in aj.descendants(class_name=cls):
        t = (c.window_text() or "").strip()
        if t:
            r = c.rectangle()
            print(f"  {cls} '{t}' rect=({r.left},{r.top})")

print("\n--- UIA: filas del grid ---")
try:
    uwin = Desktop(backend="uia").window(handle=ha)
    for ct in ("Table", "DataGrid", "List"):
        els = uwin.descendants(control_type=ct)
        if els:
            print(f"  {ct}: {len(els)}")
            items = els[0].descendants(control_type="DataItem") or els[0].descendants(control_type="ListItem")
            for it in items[:3]:
                print("   fila:", it.window_text(), [d.window_text() for d in it.descendants()][:6])
except Exception as e:
    print("  UIA no:", str(e)[:100])

# DESCARTAR sin guardar: Cancelar, luego Salir + No
print("\n--- descartando (Cancelar/Salir sin guardar) ---")
for titulo in ("C&ancelar", "Cancelar"):
    try:
        aj.child_window(title=titulo, class_name="TFlatButton").click_input()
        print(f"  clic '{titulo}'"); time.sleep(0.8)
        break
    except Exception:
        continue
# si aparece confirm
for _ in range(2):
    h = fp._find_hwnd("TFConfirmacion") or fp._find_hwnd("TMessageForm")
    if h:
        m = fp._win(h)
        for t in ("&NO", "No", "&No"):
            try: m.child_window(title=t).click_input(); print(f"  confirm '{t}'"); break
            except Exception: continue
        time.sleep(0.5)
print("ventana Ajustes sigue abierta:", bool(fp._find_hwnd(AJU)))
