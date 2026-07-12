"""diag_campos_precio.py — Abre Costos y Precios del producto cargado y vuelca TODOS
los campos numéricos con su posición y valor actual. NO teclea nada. Screenshot."""
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

# abrir Costos y Precios (producto ya cargado en la Ficha)
hd = fp._find_hwnd(fp.PRECIOS_CLASS)
if not hd:
    hf = fp._find_hwnd(fp.FICHA_CLASS)
    if not hf:
        raise SystemExit("Ni Ficha ni diálogo abiertos; carga un producto primero.")
    fi = fp._win(hf); fi.set_focus(); time.sleep(0.3)
    btn = fi.child_window(title="Costos &y Precios", class_name="TFlatButton")
    btn.wait("exists visible", timeout=8)
    r = btn.rectangle()
    ri.click((r.left+r.right)//2, (r.top+r.bottom)//2)
    hd = fp._wait_for(fp.PRECIOS_CLASS, desc="Costos y Precios")
    time.sleep(0.6)

dlg = fp._win(hd)
WL, WT, WR, WB = win32gui.GetWindowRect(hd)
print(f"Diálogo TFHCostosPrecios rect={ (WL,WT,WR,WB) }")

# volcar paneles y campos numéricos
print("\n=== paneles TPanel (title) ===")
for p in dlg.descendants(class_name="TPanel"):
    t = (p.window_text() or "").strip()
    if t:
        r = p.rectangle()
        print(f"  '{t}'  rect=({r.left},{r.top},{r.right},{r.bottom})")

print("\n=== THybridEditNumber (rel al diálogo | valor) ===")
for c in dlg.descendants(class_name="THybridEditNumber"):
    r = c.rectangle()
    rel = (r.left - WL, r.top - WT)
    # ¿en qué panel cae? (por geometría, POtrasMonedas)
    print(f"  rel={rel}  screen=({r.left},{r.top})  valor={c.window_text()!r}")

# la grabación: el dueño tecleó en rel≈(637,298). Marca el más cercano.
objetivo_rel = (640, 298)
best = None
for c in dlg.descendants(class_name="THybridEditNumber"):
    r = c.rectangle()
    rel = (r.left - WL, r.top - WT)
    d = abs(rel[0]-objetivo_rel[0]) + abs(rel[1]-objetivo_rel[1])
    if best is None or d < best[0]:
        best = (d, rel, c.window_text())
print(f"\n>>> Campo más cercano a rel(640,298) [el que edita el dueño]: rel={best[1]} valor={best[2]!r}")

ImageGrab.grab(bbox=(WL, WT, WR, WB)).save(os.path.join(DIR, "campos_precio.png"))
print("guardado campos_precio.png")
