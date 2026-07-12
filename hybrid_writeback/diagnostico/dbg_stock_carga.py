"""dbg_stock_carga.py — Depura la carga de producto en flujo_stock_real paso a paso."""
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
COD = sys.argv[1] if len(sys.argv) > 1 else "00-002-024"

ha = fs.abrir_ajustes()
aj = fp._win(ha)
grid = fs._grilla(aj)
gr = grid.rectangle()
print(f"ajustes hwnd={ha} grid rect=({gr.left},{gr.top},{gr.right},{gr.bottom})")

fs._focus(ha)
print(f"clic código en ({gr.left+196},{gr.top+40})")
ri.click(gr.left + 196, gr.top + 40)
time.sleep(0.3)
ri.type_code(COD)
time.sleep(0.3)
print("celdas tras teclear (antes de Enter):", fs._leer(aj, grid))
ri.press("ENTER"); time.sleep(1.0)
print("celdas tras 1er Enter:", fs._leer(aj, grid))
ri.press("ENTER"); time.sleep(0.8)
print("celdas tras 2do Enter:", fs._leer(aj, grid))

# volcado crudo de edits en la fila
print("\n-- edits/nums en la fila activa --")
for cls in ("THybridEdit", "THybridEditNumber"):
    for c in aj.descendants(class_name=cls):
        r = c.rectangle()
        if gr.top < r.top < gr.top+46 and gr.left <= r.left < gr.right:
            print(f"  {cls} x={r.left} '{c.window_text()}'")

fs._focus(ha)
L,T,R,B = win32gui.GetWindowRect(ha)
ImageGrab.grab(bbox=(L,T,R,B)).save(os.path.join(DIR, "dbg_stock.png"))
print("[shot] dbg_stock.png")
fs._cancelar(aj)
