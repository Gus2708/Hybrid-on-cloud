"""diag_grid_pedidos.py — ¿se puede LEER la grilla de Pedidos?

Motivo: el 2026-07-28 el pedido 13 se registró con 24 de 25 ítems (doc 00004751,
faltó 05133 x4). Una alerta de HybridLite robó el foco y se comió las teclas del
ítem, pero cargar_item lo dio por cargado igual. La verificación contra DBISAM lo
detectó DESPUÉS de Totalizar, o sea con el documento ya permanente.

Para detectarlo ANTES hay que confirmar en pantalla que la fila entró. En
flujo_stock_real._celdas se documenta que en la grilla de Ajustes solo la fila
ACTIVA expone editores THybridEdit/THybridEditNumber legibles. Este script
comprueba si en la grilla de PEDIDOS pasa lo mismo, y con qué geometría.

NO commitea: abre Pedidos, carga un ítem, dumpea los controles de la grilla y
CANCELA el documento. Toma el mouse/teclado ~40s.

Uso:
    python diagnostico/diag_grid_pedidos.py [cliente] [codigo] [cantidad]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flujo_precio as fp
import flujo_pedido_real as f
import abrir_hybrid

CLIENTE = sys.argv[1] if len(sys.argv) > 1 else "001"
CODIGO = sys.argv[2] if len(sys.argv) > 2 else "01418"
CANT = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0


def dump(ped, grid, etiqueta):
    """Todo control cuyo rectángulo cae dentro de la grilla, con su texto."""
    gr = grid.rectangle()
    print(f"\n===== {etiqueta} =====")
    print(f"grilla rect: {gr}")
    encontrados = 0
    for c in ped.descendants():
        try:
            r = c.rectangle()
        except Exception:
            continue
        if not (gr.left <= r.left < gr.right and gr.top <= r.top < gr.bottom):
            continue
        try:
            txt = c.window_text()
        except Exception:
            txt = "<no legible>"
        try:
            cls = c.class_name()
        except Exception:
            cls = "?"
        encontrados += 1
        print(f"  {cls:<22} left={r.left:<6} top={r.top:<6} w={r.right-r.left:<5} "
              f"h={r.bottom-r.top:<4} text={txt!r}")
    if not encontrados:
        print("  (ningún control hijo dentro de la grilla: NO se puede leer así)")


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
        dump(ped, grid, "ANTES de cargar ningún ítem")

        f.cargar_item(CODIGO, CANT, es_primero=True)
        time.sleep(0.6)
        dump(ped, grid, f"DESPUÉS de cargar {CODIGO} x{CANT}")

        print(f"\n>>> ¿aparece {CODIGO!r} en algún texto de la grilla? "
              "eso es lo que decide si se puede verificar en pantalla.")
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
