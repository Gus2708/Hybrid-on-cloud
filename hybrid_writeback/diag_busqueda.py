"""
diag_busqueda.py — Diagnóstico de la ventana de búsqueda (NO selecciona nada).

Abre la búsqueda desde la Ficha, escribe el código en el filtro, lee de vuelta
qué quedó en cada control (combo, edit, statusbar) y cierra con '&Salir'.
No presiona Enter ni toca la grilla: no carga ningún producto.
"""
import json
import os
import time

import win32gui
import flujo_precio as fp

DIR = os.path.dirname(os.path.abspath(__file__))
CODIGO = "00-002-024"

puntos = json.load(open(os.path.join(DIR, "calib_puntos.json"), encoding="utf-8"))

# 1) abrir búsqueda desde la ficha
h = fp._find_hwnd(fp.FICHA_CLASS)
if not h:
    raise SystemExit("La Ficha de Inventario no está abierta.")
fp._click_punto(puntos, "ficha_buscar", fp.FICHA_CLASS)
hbusq = fp._wait_for(fp.BUSQ_CLASS, desc="búsqueda")
busq = fp._win(hbusq)
print(f"[1] Búsqueda abierta: {win32gui.GetWindowText(hbusq)!r}")

# 2) estado inicial de los controles
combo = busq.child_window(class_name="TComboBox")
edit = busq.child_window(class_name="THybridEdit")
print(f"[2] combo texto inicial: {combo.window_text()!r}")
try:
    print(f"    combo items: {combo.item_texts()}")
except Exception as e:
    print(f"    combo items: (no legibles: {e})")
print(f"    edit texto inicial: {edit.window_text()!r}")

# 3) escribir el código en el edit (con clic previo y pausas)
edit.click_input()
time.sleep(0.3)
edit.type_keys("^a{DELETE}", set_foreground=False)
time.sleep(0.2)
edit.type_keys(CODIGO, with_spaces=False, set_foreground=False, pause=0.06)
time.sleep(1.5)   # dejar filtrar
print(f"[3] edit tras escribir: {edit.window_text()!r}")

# 4) foco actual y textos de la ventana (statusbar suele decir cuántas filas hay)
try:
    hfoco = win32gui.GetFocus()
except Exception:
    hfoco = 0
print(f"[4] control con foco: hwnd={hfoco} clase={win32gui.GetClassName(hfoco) if hfoco else '?'}")
for sb in busq.descendants(class_name="TStatusBar"):
    print(f"    statusbar: {sb.texts()!r}")
for pnl in busq.descendants(class_name="TPanel"):
    t = (pnl.window_text() or "").strip()
    if t and t not in ("Panel",):
        print(f"    panel: {t!r}")

# 5) cerrar con Salir (sin seleccionar nada)
print("[5] Cerrando con '&Salir'...")
busq.child_window(title="&Salir", class_name="TFlatButton").click_input()
time.sleep(0.6)
print(f"    búsqueda sigue abierta: {bool(fp._find_hwnd(fp.BUSQ_CLASS))}")
