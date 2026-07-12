"""_estado_login.py — Cierra mensajes y muestra el contenido de los campos de login."""
import time
import win32gui
from PIL import ImageGrab
import flujo_precio as fp

LOGIN = "TFUserPassMainForm"
# cerrar cualquier mensaje de error
for _ in range(3):
    h = fp._find_hwnd("TMessageForm")
    if not h:
        break
    m = fp._win(h)
    for t in ("OK", "Aceptar", "&OK"):
        try:
            m.child_window(title=t).click_input(); break
        except Exception:
            continue
    time.sleep(0.5)

h = fp._find_hwnd(LOGIN)
if not h:
    print("Login no visible. ¿Ya entró o está cerrado?")
    print("main abierto:", bool(fp._find_hwnd("TF_MainHybridCashMG")))
else:
    fp._win(h).set_focus(); time.sleep(0.3)
    win32gui.SetForegroundWindow(h); time.sleep(0.3)
    w = fp._win(h)
    print("campos del login (top | texto):")
    eds = []
    for cls in ("THybridEdit", "TEdit", "TMaskEdit"):
        for c in w.descendants(class_name=cls):
            eds.append((c.rectangle().top, c.rectangle().left, c.window_text()))
    for top, left, txt in sorted(eds):
        print(f"  top={top} left={left} texto={txt!r}")
    L, T, R, B = win32gui.GetWindowRect(h)
    ImageGrab.grab(bbox=(L, T, R, B)).save("login_estado.png")
    print("[shot] login_estado.png")
