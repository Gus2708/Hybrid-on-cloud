"""diag_ficha_campos.py — Mapea los edits de la Ficha con su posición (sin tocar nada).
Úsalo con un producto YA cargado a mano para saber qué edit tiene el código."""
import flujo_precio as fp

hf = fp._find_hwnd(fp.FICHA_CLASS)
if not hf:
    raise SystemExit("Ficha no abierta. Carga un producto a mano y reintenta.")
fi = fp._win(hf)
print("=== edits de la Ficha (clase | texto | rect) ===")
for cls in ("THybridEdit", "TEdit", "THybridEditNumber", "TISComboBox", "TComboBox"):
    for c in fi.descendants(class_name=cls):
        t = (c.window_text() or "").strip()
        r = c.rectangle()
        print(f"{cls:18} | {t[:38]!r:40} | L{r.left} T{r.top}")
