"""dbg_faithful.py — Replica FIEL la grabación del conteo. Fresh row: código→ENTER,
luego Conteo: clic simple → ENTER → teclear → ENTER. Prueba Totalizar; si aparece la
confirmación TFConfirmacion la CANCELA (no guarda). Si sale 'No items', lo reporta."""
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
COD, TARGET = "00-002-024", "5"


def dismiss_ok():
    for _ in range(3):
        h = fp._find_hwnd("TMessageForm")
        if not h: break
        try: fp._win(h).child_window(title="OK").click_input()
        except Exception:
            try: fp._win(h).type_keys("{ENTER}")
            except Exception: pass
        time.sleep(0.4)


dismiss_ok()
ha = fp._find_hwnd(fs.AJU_CLASS); fs._focus(ha); aj = fp._win(ha); grid = fs._grilla(aj)
fs._borrar_items(aj); time.sleep(0.5)
gr = grid.rectangle()

# cargar producto fresco
fs._focus(ha)
ri.click(gr.left+196, gr.top+40); time.sleep(0.3)
ri.type_code(COD); time.sleep(0.4)
ri.press("ENTER"); time.sleep(1.0)
ri.press("ENTER"); time.sleep(0.8)
print("cargado:", fs._leer(aj, grid))

# CONTEO fiel: clic simple, ENTER, teclear numpad, ENTER
c = fs._celdas(aj, grid); r = c["conteo"].rectangle()
cx, cy = (r.left+r.right)//2, (r.top+r.bottom)//2
ri.click(cx, cy); time.sleep(0.3)
ri.press("ENTER"); time.sleep(0.3)          # entra a edición (como en la grabación)
# borrar lo que haya y teclear el objetivo
ri.press("END")
for _ in range(6): ri.press_vk(ri.VK["BACKSPACE"], hold=0.02)
ri.type_number(TARGET); time.sleep(0.2)
ri.press("ENTER"); time.sleep(0.6)
print("tras conteo fiel:", fs._leer(aj, grid))

# Totalizar (detectar confirmación -> cancelar; o 'No items')
fs._focus(ha)
b = aj.child_window(title="&Totalizar", class_name="TFlatButton")
rr = b.rectangle(); ri.click((rr.left+rr.right)//2,(rr.top+rr.bottom)//2)
print("clic Totalizar"); time.sleep(1.3)

hc = fp._find_hwnd(fs.CONF_CLASS)
hm = fp._find_hwnd("TMessageForm")
if hc:
    w = fp._win(hc)
    btns = [b.window_text().strip() for bc in ("TFlatButton","TButton") for b in w.descendants(class_name=bc) if (b.window_text() or "").strip()]
    print("¡CONFIRMACIÓN! (Totalizar VE el ítem) botones=", btns)
    for t in ("&NO","NO","No","&No","Cancelar","&Cancelar"):
        try: w.child_window(title=t).click_input(); print("cancelé con",t); break
        except Exception: continue
elif hm:
    txt = fp._win(hm).window_text()
    print("MENSAJE:", txt, "->", [c.window_text() for c in fp._win(hm).descendants(class_name='TLabel')][:3])
    try: fp._win(hm).child_window(title="OK").click_input()
    except Exception: pass
else:
    print("no apareció ni confirmación ni mensaje (¿se guardó?)")
ImageGrab.grab().save(os.path.join(DIR, "faithful.png")); print("[shot] faithful.png")
