"""dbg_conteo2.py — Carga, fija Conteo=5, ENTER, captura INMEDIATA (sin navegar).
Descarta con Cancelar."""
import os, sys, time
import win32gui
from PIL import ImageGrab
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import flujo_precio as fp
import realinput as ri
import flujo_stock_real as fs

DIR = os.path.dirname(os.path.abspath(__file__))
ha = fs.abrir_ajustes(); aj = fp._win(ha); grid = fs._grilla(aj); gr = grid.rectangle()
fs._focus(ha)
ri.click(gr.left+196, gr.top+40); time.sleep(0.3)
ri.type_code("00-002-024"); time.sleep(0.3)
ri.press("ENTER"); time.sleep(1.0)
ri.press("ENTER"); time.sleep(0.8)

c = fs._celdas(aj, grid); conteo = c["conteo"]; r = conteo.rectangle()
ri.click((r.left+r.right)//2, (r.top+r.bottom)//2); time.sleep(0.2)
ri.click((r.left+r.right)//2, (r.top+r.bottom)//2, double=True); time.sleep(0.2)
ri.clear_hard(); ri.type_number("5"); time.sleep(0.2)
ri.press("ENTER"); time.sleep(0.8)

# captura inmediata + lectura
fs._focus(ha)
L,T,R,B = win32gui.GetWindowRect(ha)
ImageGrab.grab(bbox=(L,T,R,B)).save(os.path.join(DIR, "dbg_conteo2.png"))
print("lectura:", fs._leer(aj, grid))
# volcado de TODOS los nums en la fila
for cnum in aj.descendants(class_name="THybridEditNumber"):
    rr = cnum.rectangle()
    if gr.top < rr.top < gr.top+46:
        print(f"  num x={rr.left} '{cnum.window_text()}'")
print("[shot] dbg_conteo2.png")
fs._cancelar(aj)
