"""
test_set_price.py — PRUEBA del mecanismo de escritura del precio USD con impuesto.

Ubica el campo 'Precio con impuesto USD' en el diálogo 'Costos y Precios' abierto,
le pone un valor de prueba y reporta. Por defecto NO pulsa Aceptar (no compromete
el cambio: puedes descartar con 'Salir').

Uso:
    python test_set_price.py 13.50            # set_text (no foreground)
    python test_set_price.py 13.50 --keys     # focus + teclear (más fiable)
    python test_set_price.py 13.50 --commit    # ADEMÁS pulsa Aceptar (¡compromete!)
"""
import sys
import time
import win32gui
import win32process
from pywinauto import Application


def find_pid():
    handles = []
    win32gui.EnumWindows(lambda h, _: handles.append(h), None)
    for h in handles:
        if win32gui.GetClassName(h) == "TFHCostosPrecios":
            return win32process.GetWindowThreadProcessId(h)[1]
    return None


def find_precio_usd_con_impuesto(dlg):
    """Campo USD 'Precio con impuesto': dentro del panel POtrasMonedas,
    columna izquierda (x<900), el de mayor 'top' (el de más abajo)."""
    panel = dlg.child_window(title="POtrasMonedas", class_name="TPanel")
    candidatos = []
    for c in panel.descendants(class_name="THybridEditNumber"):
        r = c.rectangle()
        if r.left < 900:  # excluye la columna de % utilidad (x~1008)
            candidatos.append((r.top, c))
    if not candidatos:
        raise RuntimeError("No encontré campos USD en POtrasMonedas")
    candidatos.sort(key=lambda t: t[0])
    # el de arriba = sin impuesto (10.34); el de abajo = con impuesto (12.00)
    return candidatos[-1][1]


def main():
    if len(sys.argv) < 2:
        print("Uso: python test_set_price.py <nuevo_valor> [--keys] [--commit]")
        return
    nuevo = sys.argv[1]
    use_keys = "--keys" in sys.argv
    commit = "--commit" in sys.argv

    pid = find_pid()
    if not pid:
        print("Abre 'Costos y Precios' para el producto de prueba primero.")
        return
    app = Application(backend="win32").connect(process=pid, timeout=5)
    dlg = app.window(class_name="TFHCostosPrecios")

    campo = find_precio_usd_con_impuesto(dlg)
    antes = campo.window_text()
    r = campo.rectangle()
    print(f"Campo objetivo: pos=({r.left},{r.top}) valor_actual={antes!r}")

    if use_keys:
        dlg.set_focus()
        campo.click_input()                 # foco real al campo
        time.sleep(0.25)
        # limpiar contenido: seleccionar todo (Home + Shift+End) y borrar
        campo.type_keys("{HOME}+{END}{DELETE}", set_foreground=False)
        time.sleep(0.1)
        campo.type_keys(nuevo, with_spaces=False, set_foreground=False)  # teclea "13.50"
        time.sleep(0.1)
        campo.type_keys("{TAB}", set_foreground=False)  # commit -> dispara recálculo
    else:
        campo.set_text(nuevo)
        # intentar disparar OnChange con un Tab por teclado a nivel de ventana
        try:
            campo.type_keys("{TAB}")
        except Exception:
            pass

    time.sleep(0.4)
    despues = campo.window_text()
    print(f"valor_despues={despues!r}")
    print("Revisa en pantalla si el campo cambió y si los bolívares recalcularon.")

    if commit:
        print("Pulsando 'Aceptar' (COMMIT)...")
        dlg.child_window(title="Aceptar", class_name="TButton").click()
        print("Aceptar pulsado. Recuerda 'Guardar' en la ficha para persistir.")
    else:
        print("NO se pulsó Aceptar. Puedes descartar con 'Salir' si algo se ve mal.")


if __name__ == "__main__":
    main()
