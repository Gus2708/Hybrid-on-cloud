"""dbg_conteo.py — Fija el Conteo y prueba qué acción hace que la Diferencia recalcule.
Descarta con Cancelar (no guarda)."""
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
COD = "00-002-024"
TARGET = 5

ha = fs.abrir_ajustes(); aj = fp._win(ha); grid = fs._grilla(aj); gr = grid.rectangle()
fs._focus(ha)
ri.click(gr.left+196, gr.top+40); time.sleep(0.3)
ri.type_code(COD); time.sleep(0.3)
ri.press("ENTER"); time.sleep(1.0)
ri.press("ENTER"); time.sleep(0.8)
print("cargado:", fs._leer(aj, grid))

# enfocar celda conteo
c = fs._celdas(aj, grid)
conteo = c["conteo"]; r = conteo.rectangle()
cx, cy = (r.left+r.right)//2, (r.top+r.bottom)//2
print(f"conteo cell x={r.left} rect=({r.left},{r.top},{r.right},{r.bottom})")
ri.click(cx, cy); time.sleep(0.2)
ri.click(cx, cy, double=True); time.sleep(0.2)
ri.clear_hard()
ri.type_number(str(TARGET)); time.sleep(0.2)
print("tras teclear (sin Enter):", fs._leer(aj, grid))

ri.press("ENTER"); time.sleep(0.6)
print("tras ENTER:", fs._leer(aj, grid))

ri.press("TAB"); time.sleep(0.6)
print("tras TAB:", fs._leer(aj, grid))

ri.press("DOWN"); time.sleep(0.6)
print("tras DOWN:", fs._leer(aj, grid))

ri.press("UP"); time.sleep(0.6)
print("tras UP:", fs._leer(aj, grid))

fs._focus(ha)
L,T,R,B = win32gui.GetWindowRect(ha)
ImageGrab.grab(bbox=(L,T,R,B)).save(os.path.join(DIR, "dbg_conteo.png"))
print("[shot] dbg_conteo.png")
fs._cancelar(aj)
print("cancelado; ventana abierta:", bool(fp._find_hwnd(fs.AJU_CLASS)))
