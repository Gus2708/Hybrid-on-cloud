"""read_price_fields.py — Lee (SOLO LECTURA) los campos numéricos del diálogo
'Costos y Precios' (TFHCostosPrecios) con su identificador y valor, para confirmar
cuál es el campo del 'Precio con impuesto USD'."""
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


def main():
    pid = find_pid()
    if not pid:
        print("No está abierto 'Costos y Precios'. Ábrelo para un producto.")
        return
    app = Application(backend="win32").connect(process=pid, timeout=5)
    dlg = app.window(class_name="TFHCostosPrecios")

    print("=== Campos THybridEditNumber / THybridEdit en 'Costos y Precios' ===")
    for ctrl in dlg.descendants():
        cls = ctrl.class_name() or ""
        if "THybridEdit" in cls:
            try:
                val = ctrl.window_text()
            except Exception:
                val = "<?>"
            try:
                aid = ctrl.element_info.automation_id
            except Exception:
                aid = ""
            # auto_id de pywinauto win32 = no aplica; usamos los "best match" ids
            rect = ctrl.rectangle()
            print(f"  class={cls:<20} value={val!r:<16} pos=({rect.left},{rect.top}) "
                  f"ctrl_id={ctrl.control_id()}")
    print("\nPista: el 'Precio con impuesto USD' es el que mostraba 12.00 "
          "(panel POtrasMonedas, lado derecho).")


if __name__ == "__main__":
    main()
