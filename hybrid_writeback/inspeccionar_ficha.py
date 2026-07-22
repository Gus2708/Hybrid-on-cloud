"""inspeccionar_ficha.py — Vuelca el árbol de controles (clase / texto / posición
relativa a la ventana) de una ventana de HybridLite, para CALIBRAR los flujos de
alta de ficha (Clientes / Proveedores):

  * la CLASE de la ventana de mantenimiento (para la constante *_CLASS del flujo),
  * las FRANJAS de posición (rel_top / rel_left) de cada THybridEdit, que es como
    _campos_ficha localiza nombre / rif / teléfono / etc. por banda,
  * de paso, títulos de botones que SÍ sean ventanas reales (TFlatButton, etc.).

OJO: la barra superior de la Ficha (Incluir · Modificar · Cancelar · Guardar ·
Borrar · Salir) es OWNER-DRAWN (dibujada, no son ventanas reales) y NO aparece en
este volcado; esos botones se calibran por COORDENADA sobre una captura de
pantalla (ver INCLUIR_REL / CANCELAR_REL en flujo_compra_real.py).

Es SOLO LECTURA de la UI: no clickea ni teclea nada. Corre seguro con la ficha ya
abierta en pantalla.

Uso:
    python inspeccionar_ficha.py                 # la ventana en primer plano
    python inspeccionar_ficha.py TTConfigForm    # por clase (primera visible)
    python inspeccionar_ficha.py --list          # lista ventanas top-level visibles
"""
import sys
import datetime

import win32gui

import flujo_precio as fp


def _listar_top_level():
    """Imprime las ventanas top-level visibles con título (para ubicar la clase
    de la ficha de Clientes/Proveedores cuando no se sabe de antemano)."""
    filas = []

    def _cb(h, _):
        if not win32gui.IsWindowVisible(h):
            return
        titulo = win32gui.GetWindowText(h)
        if not titulo:
            return
        filas.append((win32gui.GetClassName(h), titulo))

    win32gui.EnumWindows(_cb, None)
    print("=== Ventanas top-level visibles (clase — título) ===")
    for cls, titulo in filas:
        print(f"  {cls:<32} {titulo!r}")


def _dump(hwnd, out):
    cls = win32gui.GetClassName(hwnd)
    titulo = win32gui.GetWindowText(hwnd)
    L, T, R, B = win32gui.GetWindowRect(hwnd)
    cab = (f"VENTANA class={cls!r} title={titulo!r}\n"
           f"  rect=({L},{T},{R},{B})  size=({R - L}x{B - T})")
    out.append(cab)
    print(cab)

    try:
        w = fp._win(hwnd)
        hijos = w.descendants()
    except Exception as e:
        msg = f"  (no pude enumerar hijos con pywinauto: {e!r})"
        out.append(msg)
        print(msg)
        return

    for c in hijos:
        try:
            r = c.rectangle()
            linea = (f"  rel=({r.left - L:4d},{r.top - T:4d}) "
                     f"size=({r.width():3d}x{r.height():2d}) "
                     f"class={c.class_name():<26} text={(c.window_text() or '').strip()!r}")
        except Exception:
            continue
        out.append(linea)
        print(linea)


def main():
    if "--list" in sys.argv:
        _listar_top_level()
        return

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        cls = args[0]
        hwnd = fp._find_hwnd(cls, visible=True)
        if not hwnd:
            print(f"No encontré ninguna ventana visible de clase {cls!r}. "
                  f"Probá 'python inspeccionar_ficha.py --list' para ver las clases.")
            return
    else:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            print("No pude obtener la ventana en primer plano.")
            return

    out = []
    _dump(hwnd, out)

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    cls = win32gui.GetClassName(hwnd)
    archivo = f"inspeccion_{cls}_{stamp}.txt"
    try:
        with open(archivo, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        print(f"\n(guardado en {archivo})")
    except Exception as e:
        print(f"\n(no pude guardar el volcado: {e!r})")


if __name__ == "__main__":
    main()
