"""Cierra Vista Previa y la ventana de Ajustes (Salir sin guardar). Deja limpio."""
import time
import win32gui, win32con
import flujo_precio as fp
import flujo_stock_real as fs
import realinput as ri

for _ in range(3):
    h = fp._find_hwnd("TfrxPreviewForm")
    if not h:
        break
    try:
        win32gui.SetForegroundWindow(h); time.sleep(0.2); ri.press("ESC")
    except Exception:
        pass
    time.sleep(0.5)

ha = fp._find_hwnd(fs.AJU_CLASS)
if ha:
    aj = fp._win(ha); aj.set_focus(); time.sleep(0.3)
    try:
        aj.child_window(title="&Salir", class_name="TFlatButton").click_input()
    except Exception:
        pass
    time.sleep(1.0)
    for _ in range(3):
        h = fp._find_hwnd("TFConfirmacion") or fp._find_hwnd("TMessageForm")
        if not h:
            break
        m = fp._win(h)
        for t in ("&NO", "No", "&No", "NO", "OK"):
            try:
                m.child_window(title=t).click_input(); break
            except Exception:
                continue
        time.sleep(0.5)

print("Vista Previa abierta:", bool(fp._find_hwnd("TfrxPreviewForm")))
print("Ajustes abierto:", bool(fp._find_hwnd(fs.AJU_CLASS)))
