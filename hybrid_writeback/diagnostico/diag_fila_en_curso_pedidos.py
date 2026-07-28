"""diag_fila_en_curso_pedidos.py — ¿la fila EN CURSO (la que se está tecleando)
muestra el código y la descripción del producto?

diag_fila_activa_pedidos.py ya probó que la fila activa baja 40px al postear, lo
que sirve para detectar un ítem perdido DESPUÉS del posteo. Si además la fila en
curso es legible, se puede detectar el problema aún antes: apenas se teclea el
código y HybridLite carga el producto.

Este script teclea SOLO el código + ENTER (sin cantidad, sin postear) y dumpea la
banda de editores de la fila activa con sus textos.

NO commitea: CANCELA al final. Toma el mouse/teclado ~40s.

Uso:
    python diagnostico/diag_fila_en_curso_pedidos.py [cliente] [codigo]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import win32gui

import flujo_precio as fp
import flujo_pedido_real as f
import abrir_hybrid
import realinput as ri

CLIENTE = sys.argv[1] if len(sys.argv) > 1 else "001"
CODIGO = sys.argv[2] if len(sys.argv) > 2 else "01418"

EDITOR_CLASSES = ("THybridEdit", "THybridEditNumber")


def banda_activa(ped, grid):
    """[(left, class, text), ...] de la fila activa, ordenada por left."""
    gr = grid.rectangle()
    ctrls = []
    for c in ped.descendants():
        try:
            cls = c.class_name()
            r = c.rectangle()
        except Exception:
            continue
        if cls not in EDITOR_CLASSES:
            continue
        if not (gr.left <= r.left < gr.right and gr.top <= r.top < gr.bottom):
            continue
        try:
            txt = c.window_text()
        except Exception:
            txt = "<no legible>"
        ctrls.append((r.top, r.left, cls, txt))

    bandas = {}
    for top, left, cls, txt in ctrls:
        clave = next((k for k in bandas if abs(k - top) <= 3), top)
        bandas.setdefault(clave, []).append((left, cls, txt))

    candidatas = {k: v for k, v in bandas.items() if len(v) >= 3}
    if not candidatas:
        return None, []
    top = max(candidatas)
    return top, sorted(candidatas[top])


def mostrar(ped, grid, etiqueta):
    top, fila = banda_activa(ped, grid)
    print(f"\n--- {etiqueta} (top={top}) ---")
    if not fila:
        print("   (sin banda legible)")
        return
    for left, cls, txt in fila:
        print(f"   left={left:<6} {cls:<20} text={txt!r}")


def main():
    ok, msg = abrir_hybrid.asegurar_hybrid()
    if not ok:
        print("No pude abrir Hybrid:", msg)
        return

    hped = None
    try:
        hped = f.abrir_pedidos()
        ped = fp._win(hped)
        f.seleccionar_cliente(ped, CLIENTE)
        grid = ped.child_window(class_name="TAdvStringGrid", found_index=0)

        # clic en la celda Código de la 1a fila (mismo patrón que cargar_item)
        gr = grid.rectangle()
        ri.click(gr.left + 68, gr.top + 34)
        time.sleep(0.3)
        mostrar(ped, grid, "tras el clic, ANTES de teclear")

        ri.type_code(str(CODIGO))
        time.sleep(0.2)
        mostrar(ped, grid, f"tecleado {CODIGO}, ANTES del ENTER")

        ri.press("ENTER")
        time.sleep(0.8)
        mostrar(ped, grid, "DESPUÉS del ENTER (producto cargado)")

        print(f"\n>>> si el código {CODIGO!r} y/o la descripción aparecen arriba, "
              "se puede validar el ítem apenas se teclea, antes de postear.")
    finally:
        try:
            f._cancelar_pedido(hped or fp._find_hwnd(f.PEDIDOS_CLASS))
            f._salir_pedidos()
        except Exception as e:
            print("(aviso: fallo cancelando/saliendo:", e, ")")
        try:
            abrir_hybrid.cerrar_aislada()
        except Exception as e:
            print("(aviso: no pude cerrar la instancia aislada:", e, ")")


if __name__ == "__main__":
    main()
