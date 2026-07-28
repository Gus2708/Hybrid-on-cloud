"""diag_item_perdido_pedidos.py — ¿el flujo DETECTA un ítem cuyas teclas se
perdieron?

Reproduce contra la aplicación real el fallo del 2026-07-28 (doc 00004751 quedó
con 24 de 25 ítems porque una alerta se comió las teclas del código 05133 y
cargar_item lo dio por cargado igual).

Simula la pérdida anulando ri.type_code para UN ítem concreto: se pulsan los
ENTER y la cantidad, pero el código nunca llega a la celda — exactamente lo que
pasa cuando otra ventana tiene el foco.

ESPERADO: PedidoError en ese ítem, etapa 'carga_item', documento CANCELADO
completo (todo-o-nada). Si termina en 'preview' con ok=True, la verificación NO
está funcionando.

Corre SIEMPRE en preview (nunca commitea). Toma el mouse/teclado ~50s.

Uso:
    python diagnostico/diag_item_perdido_pedidos.py [cliente]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flujo_pedido_real as f
import realinput as ri
import abrir_hybrid

CLIENTE = sys.argv[1] if len(sys.argv) > 1 else "001"
ITEMS = [
    {"codigo": "01418", "cantidad": 1.0, "precio": None},
    {"codigo": "TPH-12", "cantidad": 2.0, "precio": None},   # <- a este se le comen las teclas
    {"codigo": "05126", "cantidad": 1.0, "precio": None},
]
SABOTEADO = "TPH-12"

_type_code_real = ri.type_code


def type_code_saboteado(texto, *a, **kw):
    if str(texto).strip().upper() == SABOTEADO.upper():
        print(f"    [SABOTAJE] descarto el tecleo de {texto!r} (simula alerta que roba el foco)")
        return
    return _type_code_real(texto, *a, **kw)


def main():
    ri.type_code = type_code_saboteado
    try:
        res = f.registrar_pedido(CLIENTE, ITEMS, commit=False)
    finally:
        ri.type_code = _type_code_real
        try:
            abrir_hybrid.cerrar_aislada()
        except Exception as e:
            print("(aviso: no pude cerrar la instancia aislada:", e, ")")

    print("\n=== RESULTADO ===")
    for k, v in res.items():
        print(f"  {k}: {v}")

    detecto = (not res["ok"]) and res["etapa"] == "carga_item" and SABOTEADO in res["detalle"]
    print("\n=== VEREDICTO ===")
    print("  DETECTADO y cancelado" if detecto
          else "  NO DETECTADO -> la verificación no está funcionando")


if __name__ == "__main__":
    main()
