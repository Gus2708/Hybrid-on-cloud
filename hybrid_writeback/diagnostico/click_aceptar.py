"""click_aceptar.py — Pulsa 'Aceptar' en el diálogo 'Costos y Precios' abierto.
Verifica antes el valor del precio USD con impuesto y reporta el estado después."""
import time
import win32gui
import win32process
from pywinauto import Application


def find_pid(cls_name):
    handles = []
    win32gui.EnumWindows(lambda h, _: handles.append(h), None)
    for h in handles:
        if win32gui.GetClassName(h) == cls_name and win32gui.IsWindowVisible(h):
            return win32process.GetWindowThreadProcessId(h)[1]
    return None


def main():
    pid = find_pid("TFHCostosPrecios")
    if not pid:
        print("El diálogo 'Costos y Precios' no está abierto/visible.")
        return
    app = Application(backend="win32").connect(process=pid, timeout=5)
    dlg = app.window(class_name="TFHCostosPrecios")

    # leer el precio USD con impuesto (panel POtrasMonedas, col izq, el de abajo)
    panel = dlg.child_window(title="POtrasMonedas", class_name="TPanel")
    izq = sorted(
        [(c.rectangle().top, c) for c in panel.descendants(class_name="THybridEditNumber")
         if c.rectangle().left < 900],
        key=lambda t: t[0],
    )
    precio = izq[-1][1].window_text() if izq else "?"
    print(f"Precio USD con impuesto antes de Aceptar: {precio!r}")

    print("Pulsando 'Aceptar' (clic de raton real)...")
    dlg.set_focus()
    time.sleep(0.2)
    dlg.child_window(title="Aceptar", class_name="TButton").click_input()
    time.sleep(0.8)

    # estado después
    still = find_pid("TFHCostosPrecios")
    print(f"Diálogo 'Costos y Precios' sigue abierto: {bool(still)}")
    ficha = find_pid("TFHFichaInventario") or find_pid("TForm_FichaInventario")
    print("Revisa la ficha: ahora habría que pulsar 'Guardar' para persistir.")


if __name__ == "__main__":
    main()
