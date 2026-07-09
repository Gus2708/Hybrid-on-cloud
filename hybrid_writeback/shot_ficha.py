"""shot_ficha.py — Cierra diálogos de error, cierra la búsqueda, captura la Ficha."""
import os, time
import win32gui
from PIL import ImageGrab
import flujo_precio as fp

DIR = os.path.dirname(os.path.abspath(__file__))

# 1) cerrar cualquier TMessageForm (el "Database name is missing")
for _ in range(3):
    h = fp._find_hwnd("TMessageForm")
    if not h:
        break
    m = fp._win(h)
    for btxt in ("Aceptar", "OK", "&OK", "Aceptar"):
        try:
            m.child_window(title=btxt).click_input()
            print(f"cerré error con '{btxt}'")
            time.sleep(0.5)
            break
        except Exception:
            continue
    else:
        # fallback: enviar Enter a la ventana de mensaje
        try:
            m.type_keys("{ENTER}")
        except Exception:
            pass
    time.sleep(0.4)

# 2) cerrar la búsqueda si sigue abierta
h = fp._find_hwnd(fp.BUSQ_CLASS)
if h:
    try:
        fp._win(h).child_window(title="&Salir", class_name="TFlatButton").click_input()
        print("cerré búsqueda")
        time.sleep(0.6)
    except Exception:
        pass

# 3) capturar la Ficha completa
hf = fp._find_hwnd(fp.FICHA_CLASS)
if not hf:
    print("Ficha no abierta.")
else:
    f = fp._win(hf)
    f.set_focus()
    time.sleep(0.3)
    L, T, R, B = win32gui.GetWindowRect(hf)
    ImageGrab.grab(bbox=(L, T, R, B)).save(os.path.join(DIR, "shot_ficha.png"))
    print(f"guardado shot_ficha.png ({R-L}x{B-T})")
