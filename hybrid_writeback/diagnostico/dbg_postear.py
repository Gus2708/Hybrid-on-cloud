"""dbg_postear.py — Descubre cómo se 'postea' la fila (Conteo) para que Totalizar la
procese. Señal = 'Total Items' del encabezado y la Diferencia. NO totaliza de verdad:
si aparece la confirmación TFConfirmacion, la CANCELA (no guarda)."""
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


def dismiss_ok():
    for _ in range(3):
        h = fp._find_hwnd("TMessageForm")
        if not h: break
        try: fp._win(h).child_window(title="OK").click_input()
        except Exception:
            try: fp._win(h).type_keys("{ENTER}")
            except Exception: pass
        time.sleep(0.4)


def header_totales(aj):
    """Lee etiquetas 'Total Items' / 'Total Cantidad' del panel oscuro (derecha)."""
    vals = []
    for c in aj.descendants(class_name="TLabel"):
        t = (c.window_text() or "").strip()
        if t and any(k in t for k in ("Total", "Items", "Cantidad", "Referencial")):
            vals.append(t)
    return vals


dismiss_ok()
ha = fp._find_hwnd(fs.AJU_CLASS); fs._focus(ha); aj = fp._win(ha); grid = fs._grilla(aj)
print("carga inicial:", fs._leer(aj, grid))
print("totales:", header_totales(aj))

# enfocar conteo, borrar, teclear 5
c = fs._celdas(aj, grid); r = c["conteo"].rectangle()
cx, cy = (r.left+r.right)//2, (r.top+r.bottom)//2
ri.click(cx, cy); time.sleep(0.2)
ri.click(cx, cy, double=True); time.sleep(0.2)
ri.clear_hard(); ri.type_number("5"); time.sleep(0.2)
print("tras teclear conteo (sin Enter):", fs._leer(aj, grid))

ri.press("ENTER"); time.sleep(0.6)
print("tras ENTER:", fs._leer(aj, grid), "| totales:", header_totales(aj))

ri.press("DOWN"); time.sleep(0.8)
print("tras DOWN:", fs._leer(aj, grid), "| totales:", header_totales(aj))

# probar Totalizar y ver si aparece confirmación (si sí, CANCELAR sin guardar)
fs._focus(ha)
try:
    b = aj.child_window(title="&Totalizar", class_name="TFlatButton")
    rr = b.rectangle(); ri.click((rr.left+rr.right)//2,(rr.top+rr.bottom)//2)
    print("clic Totalizar")
except Exception as e:
    print("no Totalizar:", e)
time.sleep(1.2)

# ¿qué apareció?
for cls in ("TFConfirmacion", "TMessageForm"):
    h = fp._find_hwnd(cls)
    if h:
        w = fp._win(h)
        btns = []
        for bc in ("TFlatButton","TButton","TBitBtn"):
            for b in w.descendants(class_name=bc):
                if (b.window_text() or "").strip(): btns.append(b.window_text().strip())
        print(f"apareció {cls} botones={btns}")
        # si es TFConfirmacion (pide confirmar guardar) -> CANCELAR con NO
        if cls == "TFConfirmacion":
            for t in ("&NO","NO","No","&No","Cancelar"):
                try: w.child_window(title=t).click_input(); print("CANCELÉ con",t); break
                except Exception: continue
        else:
            try: w.child_window(title="OK").click_input()
            except Exception: pass
        time.sleep(0.5)

ImageGrab.grab().save(os.path.join(DIR, "postear.png")); print("[shot] postear.png")
