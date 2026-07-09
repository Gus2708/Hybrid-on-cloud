"""
diag_seleccion.py — Prueba de SELECCIÓN correcta en la búsqueda (sin guardar).

Abre búsqueda → filtra por código → inspecciona grilla → doble-clic en la
primera fila de datos → verifica qué producto quedó cargado en la Ficha.
NO toca precios ni guarda: solo navega para validar la selección.
"""
import sys
import time
import win32gui
import flujo_precio as fp

CODIGO = sys.argv[1] if len(sys.argv) > 1 else "00-002-024"
import json, os
DIR = os.path.dirname(os.path.abspath(__file__))
puntos = json.load(open(os.path.join(DIR, "calib_puntos.json"), encoding="utf-8"))


def dump_ficha_edits():
    hf = fp._find_hwnd(fp.FICHA_CLASS)
    fi = fp._win(hf)
    out = []
    for cls in ("THybridEdit", "TEdit"):
        for c in fi.descendants(class_name=cls):
            t = (c.window_text() or "").strip()
            if t:
                out.append(t)
    return out[:12]


print(f"[0] Ficha antes: {dump_ficha_edits()}")

fp._click_punto(puntos, "ficha_buscar", fp.FICHA_CLASS)
hbusq = fp._wait_for(fp.BUSQ_CLASS, desc="búsqueda")
busq = fp._win(hbusq)
print(f"[1] Búsqueda abierta.")

edit = busq.child_window(class_name="THybridEdit")
edit.click_input()
time.sleep(0.3)
edit.type_keys("^a{DELETE}", set_foreground=False)
edit.type_keys(CODIGO, with_spaces=False, set_foreground=False, pause=0.06)
time.sleep(1.5)
print(f"[2] filtro escrito: {edit.window_text()!r}")

# inspeccionar grilla
grid = None
for cls in ("TDBGrid", "THybridGrid", "TStringGrid", "TDrawGrid"):
    ds = busq.descendants(class_name=cls)
    if ds:
        grid = ds[0]
        print(f"[3] grilla {cls} rect={grid.rectangle()}")
        break
if grid is None:
    print("[3] No hallé grilla; cierro y salgo.")
    busq.child_window(title="&Salir", class_name="TFlatButton").click_input()
    raise SystemExit(1)

# doble-clic en la primera fila de datos (debajo del encabezado ~22px)
r = grid.rectangle()
fila_y = r.top + 34
fila_x = r.left + 60
print(f"[4] doble-clic en primera fila (x={fila_x}, y={fila_y})")
from pywinauto.mouse import double_click
double_click(button="left", coords=(fila_x, fila_y))
time.sleep(1.0)

cerrada = not fp._find_hwnd(fp.BUSQ_CLASS)
print(f"[5] búsqueda cerrada tras doble-clic: {cerrada}")
if not cerrada:
    # a veces requiere Enter tras posicionar
    fp._win(hbusq).type_keys("{ENTER}", set_foreground=False)
    time.sleep(0.8)
    cerrada = not fp._find_hwnd(fp.BUSQ_CLASS)
    print(f"    tras ENTER: cerrada={cerrada}")
    if not cerrada:
        fp._win(hbusq).child_window(title="&Salir", class_name="TFlatButton").click_input()
        print("    (cerré con Salir; selección fallida)")

time.sleep(0.6)
edits = dump_ficha_edits()
print(f"[6] Ficha después: {edits}")
ok = any(CODIGO.lower() == e.lower() or CODIGO.lower() in e.lower() for e in edits)
print(f"[7] ¿cargó {CODIGO}? {'SÍ' if ok else 'NO'}")
