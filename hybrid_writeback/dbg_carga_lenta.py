"""dbg_carga_lenta.py — Grid limpio: teclea el código LENTO en la celda y observa qué
ventana se abre (búsqueda?) y qué queda. Detecta popups. Lista ventanas en cada paso."""
import os, sys, time
import win32gui, win32process
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


def hy_windows():
    hm = fp._find_hwnd("TF_MainHybridCashMG")
    _, mainpid = win32process.GetWindowThreadProcessId(hm)
    out = []
    def cb(h, _):
        if not win32gui.IsWindowVisible(h): return
        try: _, pid = win32process.GetWindowThreadProcessId(h)
        except Exception: return
        if pid == mainpid:
            c = win32gui.GetClassName(h) or ""
            if c not in ("TApplication",):
                out.append((c, (win32gui.GetWindowText(h) or "")[:30]))
    win32gui.EnumWindows(cb, out)
    return out


ha = fp._find_hwnd(fs.AJU_CLASS); fs._focus(ha); aj = fp._win(ha); grid = fs._grilla(aj)
gr = grid.rectangle()
print("ventanas iniciales:", hy_windows())

# clic celda código (fila datos) y teclear LENTO
ri.click(gr.left + 196, gr.top + 40); time.sleep(0.4)
print("clic hecho; ventanas:", hy_windows())
# teclear dígito por dígito lento, observando
for ch in COD:
    if ch == "-":
        ri.press_vk(ri.VK_SUBTRACT, hold=0.03)
    else:
        ri.press_vk(ri.VK_NUMPAD[ch], hold=0.03)
    time.sleep(0.18)
time.sleep(0.4)
print("tras teclear (lento):", fs._leer(aj, grid), "| ventanas:", hy_windows())
ri.press("ENTER"); time.sleep(1.2)
print("tras ENTER:", "ventanas:", hy_windows())
try:
    print("  lectura grilla:", fs._leer(aj, grid))
except Exception as e:
    print("  no pude leer grilla:", e)

# captura de pantalla completa (por si hay popup)
ImageGrab.grab().save(os.path.join(DIR, "carga_lenta.png"))
print("[shot] carga_lenta.png")
