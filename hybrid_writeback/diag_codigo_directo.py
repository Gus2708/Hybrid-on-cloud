"""
diag_codigo_directo.py — Carga un producto escribiendo el CÓDIGO directo en la Ficha.
Ruta candidata (sin búsqueda): campo 'Código' -> teclear -> Enter -> carga la ficha.
NO guarda; solo verifica qué producto quedó cargado. Captura antes/después.
"""
import sys, os, time
import win32gui
from PIL import ImageGrab
import flujo_precio as fp

CODIGO = sys.argv[1] if len(sys.argv) > 1 else "00-002-024"
DIR = os.path.dirname(os.path.abspath(__file__))


def codigo_field(fi):
    """El THybridEdit más arriba-izquierda = campo Código."""
    cands = []
    for c in fi.descendants(class_name="THybridEdit"):
        r = c.rectangle()
        cands.append((r.top, r.left, c))
    cands.sort(key=lambda t: (t[0], t[1]))
    return cands[0][2] if cands else None


def ficha_edits(fi):
    out = []
    for cls in ("THybridEdit", "TEdit"):
        for c in fi.descendants(class_name=cls):
            t = (c.window_text() or "").strip()
            if t:
                out.append(t)
    return out[:10]


hf = fp._find_hwnd(fp.FICHA_CLASS)
if not hf:
    raise SystemExit("Ficha no abierta.")
fi = fp._win(hf)
fi.set_focus()

cf = codigo_field(fi)
r = cf.rectangle()
print(f"campo código en L{r.left} T{r.top}, texto actual={cf.window_text()!r}")

cf.click_input()
time.sleep(0.3)
cf.type_keys("^a{DELETE}", set_foreground=False)
cf.type_keys(CODIGO, with_spaces=False, set_foreground=False, pause=0.06)
time.sleep(0.4)
print(f"tras teclear: {cf.window_text()!r}")
cf.type_keys("{ENTER}", set_foreground=False)
time.sleep(1.5)

# ¿apareció un diálogo de error o de búsqueda?
err = fp._find_hwnd("TMessageForm")
busq = fp._find_hwnd(fp.BUSQ_CLASS)
print(f"error TMessageForm: {bool(err)} | búsqueda abierta: {bool(busq)}")

hf = fp._find_hwnd(fp.FICHA_CLASS)
fi = fp._win(hf)
edits = ficha_edits(fi)
print(f"ficha después: {edits}")
ok = any(CODIGO.lower() == e.lower() or CODIGO.lower() in e.lower() for e in edits)
print(f"¿cargó {CODIGO}? {'SÍ' if ok else 'NO'}")

fi.set_focus(); time.sleep(0.3)
L, T, R, B = win32gui.GetWindowRect(hf)
ImageGrab.grab(bbox=(L, T, R, B)).save(os.path.join(DIR, "shot_codigo_directo.png"))
print("guardado shot_codigo_directo.png")
