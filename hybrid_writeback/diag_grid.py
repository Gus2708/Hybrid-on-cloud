"""diag_grid.py — Inspecciona la grilla de la búsqueda YA ABIERTA (no selecciona)."""
import time
import win32gui
import flujo_precio as fp

hbusq = fp._find_hwnd(fp.BUSQ_CLASS)
if not hbusq:
    raise SystemExit("La búsqueda no está abierta.")
busq = fp._win(hbusq)

print("=== controles TDBGrid / grids ===")
for cls in ("TDBGrid", "THybridGrid", "TStringGrid", "TDrawGrid"):
    for g in busq.descendants(class_name=cls):
        r = g.rectangle()
        print(f"{cls}: rect={r}")
        # texto de la grilla (VCL a veces expone rows via texts())
        try:
            txts = [t for t in g.texts() if t]
            print(f"   texts ({len(txts)}): {txts[:20]}")
        except Exception as e:
            print(f"   texts: (no) {e}")

print("\n=== botones de la búsqueda ===")
for cls in ("TFlatButton", "TBitBtn", "TButton"):
    for b in busq.descendants(class_name=cls):
        print(f"{cls}: {b.window_text()!r} rect={b.rectangle()}")

print("\n=== todos los edits/combos (por si el filtro tiene 2do campo) ===")
for cls in ("THybridEdit", "TComboBox", "TEdit"):
    for c in busq.descendants(class_name=cls):
        print(f"{cls}: {c.window_text()!r} rect={c.rectangle()}")
