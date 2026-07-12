"""diag_write_field.py — Escribe en el campo USD con-impuesto (12.00) e instrumenta
cada paso. Descarta con 'Salir' (NO guarda). Sirve para ver por qué el valor cae
en el campo equivocado."""
import os, sys, time
import win32gui
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import flujo_precio as fp
import hybrid_price_writer as hpw
import realinput as ri

TARGET = float(sys.argv[1]) if len(sys.argv) > 1 else 13.50


def otras_monedas_fields(dlg):
    """Campos numéricos del panel POtrasMonedas, columna izquierda (x<900),
    ordenados por 'top'. Devuelve lista [(top, control, valor)]."""
    panel = dlg.child_window(title="POtrasMonedas", class_name="TPanel")
    out = []
    for c in panel.descendants(class_name="THybridEditNumber"):
        r = c.rectangle()
        if r.left < 900:
            out.append((r.top, c, c.window_text()))
    out.sort(key=lambda t: t[0])
    return out


def dump(dlg, tag):
    fields = otras_monedas_fields(dlg)
    print(f"  [{tag}] POtrasMonedas izq: " +
          " | ".join(f"top{t}={v!r}" for t, _, v in fields))


hd = fp._find_hwnd(fp.PRECIOS_CLASS)
if not hd:
    raise SystemExit("El diálogo Costos y Precios no está abierto.")
dlg = fp._win(hd)

fields = otras_monedas_fields(dlg)
print("Campos POtrasMonedas (izq) por top:")
for t, c, v in fields:
    r = c.rectangle()
    print(f"  top={t} rect=({r.left},{r.top},{r.right},{r.bottom}) valor={v!r}")

# con-impuesto = el de MAYOR top (más abajo)
con_top, con_field, con_val = fields[-1]
sin_top, sin_field, sin_val = fields[0]
r = con_field.rectangle()
cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
print(f"\nCon-impuesto elegido: valor={con_val!r} rect=({r.left},{r.top},{r.right},{r.bottom}) centro=({cx},{cy})")

dump(dlg, "ANTES")
print(f"click en el campo con-impuesto ({cx},{cy}) [real]...")
ri.click(cx, cy)
time.sleep(0.3)
# seleccionar todo con Home + Shift+End (más fiable que Ctrl+A en VCL)
ri.press("HOME")
# Shift+End:
import ctypes
u = ctypes.windll.user32
u.SendInput  # noqa
# shift down
from realinput import _key_input, _send, KEYEVENTF_KEYUP
_send(_key_input(vk=0x10))          # SHIFT down
ri.press("END")
_send(_key_input(vk=0x10, flags=KEYEVENTF_KEYUP))  # SHIFT up
time.sleep(0.1)
ri.press("DELETE")
time.sleep(0.15)
dump(dlg, "tras borrar")

print(f"teclear {TARGET:.2f} [real]...")
ri.type_text(f"{TARGET:.2f}")
time.sleep(0.2)
dump(dlg, "tras teclear (sin Enter)")

ri.press("ENTER")
time.sleep(0.5)
dump(dlg, "tras ENTER")

# descartar SIN guardar
try:
    b = dlg.child_window(title="Salir", class_name="TButton")
    rr = b.rectangle()
    ri.click((rr.left+rr.right)//2, (rr.top+rr.bottom)//2)
    print("Descartado con 'Salir'.")
except Exception as e:
    print("No pude pulsar Salir:", e)
