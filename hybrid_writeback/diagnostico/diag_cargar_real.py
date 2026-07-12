"""
diag_cargar_real.py — Carga un producto con INPUT REAL, replicando la grabación.
Secuencia probada a mano:  Modificar -> Ed_Buscar -> teclear codigo -> ENTER
(ejecuta busqueda) -> doble-clic primera fila del TDBGrid -> carga en la Ficha.
NO toca precio ni guarda. Verifica que la Ficha muestre el codigo pedido.
"""
import sys, os, time
import win32gui
from PIL import ImageGrab
import flujo_precio as fp
import realinput as ri

CODIGO = sys.argv[1] if len(sys.argv) > 1 else "00-002-024"
DIR = os.path.dirname(os.path.abspath(__file__))

# Coordenadas de botones owner-drawn de la barra de la Ficha (de la grabación 16:34):
MODIFICAR_REL = (122, 62)   # abre la Busqueda


def ficha_edits():
    hf = fp._find_hwnd(fp.FICHA_CLASS)
    if not hf:
        return []
    fi = fp._win(hf)
    out = []
    for cls in ("THybridEdit", "TEdit"):
        for c in fi.descendants(class_name=cls):
            t = (c.window_text() or "").strip()
            if t:
                out.append(t)
    return out[:10]


def abrir_ficha():
    hf = fp._find_hwnd(fp.FICHA_CLASS)
    if hf:
        return hf
    hmain = fp._find_hwnd(fp.MAIN_CLASS)
    main = fp._win(hmain)
    main.set_focus(); time.sleep(0.3)
    btn = main.child_window(title="Items de Inventario", class_name="TAdvGlassButton")
    btn.wait("exists visible", timeout=8)
    r = btn.rectangle()
    ri.click((r.left+r.right)//2, (r.top+r.bottom)//2)   # real
    return fp._wait_for(fp.FICHA_CLASS, desc="Ficha")


print(f"[0] Ficha antes: {ficha_edits()}")

hf = abrir_ficha()
fi = fp._win(hf)
fi.set_focus(); time.sleep(0.4)

# 1) Modificar (abre Busqueda) — input real en coords de la barra
L, T, _, _ = win32gui.GetWindowRect(hf)
print("[1] clic Modificar (real)...")
ri.click(L + MODIFICAR_REL[0], T + MODIFICAR_REL[1])
hbusq = fp._wait_for(fp.BUSQ_CLASS, desc="Busqueda")
busq = fp._win(hbusq)
time.sleep(0.5)

# 2) Ed_Buscar: clic real + limpiar + teclear codigo real
try:
    ed = busq.child_window(class_name="THybridEdit", found_index=0)
    r = ed.rectangle()
except Exception:
    r = win32gui.GetWindowRect(hbusq)
print("[2] clic campo Ed_Buscar + teclear (real)...")
ri.click((r.left+r.right)//2, (r.top+r.bottom)//2)
time.sleep(0.3)
ri.clear_field()
ri.type_text(CODIGO)
time.sleep(0.4)

# 3) ENTER real -> ejecuta la busqueda (llena la grilla)
print("[3] ENTER (ejecutar busqueda, real)...")
ri.press("ENTER")
time.sleep(1.8)

# captura del estado de la busqueda tras ENTER
if fp._find_hwnd(fp.BUSQ_CLASS):
    LL, TT, RR, BB = win32gui.GetWindowRect(hbusq)
    ImageGrab.grab(bbox=(LL, TT, RR, BB)).save(os.path.join(DIR, "real_1_busqueda.png"))
    print("    [shot] real_1_busqueda.png")

# 4) doble-clic en la primera fila de la grilla (real)
if fp._find_hwnd(fp.BUSQ_CLASS):
    grid = busq.child_window(class_name="TDBGrid")
    gr = grid.rectangle()
    print("[4] doble-clic primera fila del grid (real)...")
    ri.click(gr.left + 100, gr.top + 26, double=True)
    time.sleep(1.2)

# 5) si sigue abierta, probar un ENTER extra (a veces el 2do Enter selecciona)
if fp._find_hwnd(fp.BUSQ_CLASS):
    print("[5] busqueda sigue abierta; ENTER extra (real)...")
    ri.press("ENTER")
    time.sleep(1.2)

# cerrar busqueda si quedara abierta (Salir), para no dejar ventanas
if fp._find_hwnd(fp.BUSQ_CLASS):
    try:
        fp._win(fp._find_hwnd(fp.BUSQ_CLASS)).child_window(
            title="&Salir", class_name="TFlatButton").click_input()
        time.sleep(0.6)
    except Exception:
        pass

err = fp._find_hwnd("TMessageForm")
print(f"[6] error 'Database name is missing'? {bool(err)}")
if err:
    try:
        print("    dialog:", fp._win(err).texts())
    except Exception:
        pass

edits = ficha_edits()
ok = any(CODIGO.lower() == e.lower() or CODIGO.lower() in e.lower() for e in edits)
print(f"[7] Ficha después: {edits}")
print(f"[8] ¿cargó {CODIGO} con INPUT REAL? {'SÍ ✅' if ok else 'NO ❌'}")

hf = fp._find_hwnd(fp.FICHA_CLASS)
if hf:
    LL, TT, RR, BB = win32gui.GetWindowRect(hf)
    ImageGrab.grab(bbox=(LL, TT, RR, BB)).save(os.path.join(DIR, "real_2_ficha.png"))
    print("    [shot] real_2_ficha.png")
