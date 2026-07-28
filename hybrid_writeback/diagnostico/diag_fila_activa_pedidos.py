"""diag_fila_activa_pedidos.py — ¿la fila ACTIVA de la grilla de Pedidos baja al
postear un ítem?

Contexto: diag_grid_pedidos.py mostró que tras postear un ítem los editores
THybridEdit/THybridEditNumber vivos están VACÍOS: son los de la fila siguiente,
no los del ítem recién cargado. O sea la fila posteada no se puede leer.

Pero la POSICIÓN de esos editores sí sirve: si el ítem entró, la fila activa baja
una fila; si una alerta se comió las teclas, se queda donde estaba. Este script
mide el 'top' de la fila activa en cada paso para confirmar que ese salto existe
y es consistente.

NO commitea: carga 2 ítems y CANCELA. Toma el mouse/teclado ~50s.

Uso:
    python diagnostico/diag_fila_activa_pedidos.py [cliente] [cod1] [cod2]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flujo_precio as fp
import flujo_pedido_real as f
import abrir_hybrid

CLIENTE = sys.argv[1] if len(sys.argv) > 1 else "001"
COD1 = sys.argv[2] if len(sys.argv) > 2 else "01418"
COD2 = sys.argv[3] if len(sys.argv) > 3 else "TPH-12"

EDITOR_CLASSES = ("THybridEdit", "THybridEditNumber")


def top_fila_activa(ped, grid):
    """'top' de la banda de editores de la fila activa, o None.

    Una fila activa expone ~6 editores alineados al mismo 'top'. Se agrupan los
    editores por 'top' (tolerancia 3px) y se toma la banda con >=3 controles, así
    se descartan los edits sueltos de la ventana (buscador, panel de seriales)
    que también caen dentro del rectángulo de la grilla.
    """
    gr = grid.rectangle()
    tops = []
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
        tops.append(r.top)

    bandas = {}
    for t in tops:
        clave = next((k for k in bandas if abs(k - t) <= 3), t)
        bandas.setdefault(clave, []).append(t)

    candidatas = [k for k, v in bandas.items() if len(v) >= 3]
    return max(candidatas) if candidatas else None


def paso(ped, grid, etiqueta):
    t = top_fila_activa(ped, grid)
    print(f"  {etiqueta:<38} fila activa top = {t}")
    return t


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

        print("\n=== SECUENCIA ===")
        t0 = paso(ped, grid, "recién abierto (sin clic)")

        f.cargar_item(COD1, 1, es_primero=True)
        time.sleep(0.6)
        t1 = paso(ped, grid, f"posteado {COD1}")

        f.cargar_item(COD2, 2, es_primero=False)
        time.sleep(0.6)
        t2 = paso(ped, grid, f"posteado {COD2}")

        print("\n=== LECTURA ===")
        print(f"  t0={t0}  t1={t1}  t2={t2}")
        if t1 is not None and t2 is not None:
            print(f"  salto por ítem = {t2 - t1} px")
            print("  VEREDICTO:", "la fila activa BAJA al postear -> sirve como evidencia"
                  if t2 > t1 else "NO baja -> no sirve, buscar otra señal")
        else:
            print("  VEREDICTO: no pude leer la banda de la fila activa -> no sirve")
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
