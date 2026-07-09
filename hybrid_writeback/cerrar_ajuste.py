"""cerrar_ajuste.py — Cierra la ventana de Ajustes (Salir) SIN guardar. Si pregunta
por guardar, responde NO. Documento vacío => descarta limpio."""
import time
import win32gui
import flujo_precio as fp
AJU = "TFormHTransaccion_Ajustes"

ha = fp._find_hwnd(AJU)
if not ha:
    print("no hay ventana de ajustes abierta")
else:
    aj = fp._win(ha); aj.set_focus(); time.sleep(0.3)
    try:
        aj.child_window(title="&Salir", class_name="TFlatButton").click_input()
    except Exception:
        try:
            aj.child_window(title="Salir", class_name="TFlatButton").click_input()
        except Exception as e:
            print("no pude Salir:", e)
    time.sleep(1.0)
    # si pregunta por guardar -> No / cancelar guardado
    for _ in range(3):
        h = fp._find_hwnd("TMessageForm")
        if not h:
            break
        m = fp._win(h)
        clicked = False
        for t in ("&No", "No"):
            try:
                m.child_window(title=t).click_input(); clicked = True; break
            except Exception:
                continue
        if not clicked:
            try: m.type_keys("{ESC}")
            except Exception: pass
        time.sleep(0.6)
    print("ventana de ajustes abierta ahora:", bool(fp._find_hwnd(AJU)))
