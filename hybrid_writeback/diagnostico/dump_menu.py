"""dump_menu.py — Lee la barra de menú del módulo principal de HybridLite (SOLO LECTURA)."""
import sys
import win32gui
import win32process
from pywinauto import Application


def find_main_pid_and_class():
    handles = []
    win32gui.EnumWindows(lambda h, _: handles.append(h), None)
    best = None
    for h in handles:
        cls = win32gui.GetClassName(h) or ""
        if cls == "TF_MainHybridCashMG" and win32gui.IsWindowVisible(h):
            return win32process.GetWindowThreadProcessId(h)[1], cls
        if cls.startswith("TF") and win32gui.IsWindowVisible(h):
            best = (win32process.GetWindowThreadProcessId(h)[1], cls)
    return best if best else (None, None)


def walk(items, indent=0):
    for it in items:
        try:
            text = it.text()
        except Exception:
            text = "<?>"
        try:
            cmd = it.item_id()
        except Exception:
            cmd = "?"
        print("  " * indent + f"- {text!r}  (id={cmd})")
        try:
            sub = it.sub_menu()
            if sub:
                walk(sub.items(), indent + 1)
        except Exception:
            pass


def main():
    pid, cls = find_main_pid_and_class()
    if not pid:
        print("No encontré el módulo principal visible. Inicia sesión en HybridLiteOS.")
        return
    print(f"pid={pid} class={cls}")
    app = Application(backend="win32").connect(process=pid, timeout=5)
    win = app.window(class_name=cls)
    try:
        menu = win.menu()
    except Exception as e:
        print(f"Esta ventana no expone barra de menú clásica: {e}")
        print("=> El menú puede ser un componente custom (toolbar/ribbon). "
              "Navega manualmente a la pantalla de precio y la volcamos con dump_form.py.")
        return
    if not menu:
        print("Sin barra de menú clásica (probablemente menú custom/ribbon).")
        return
    print("\n===== MENÚ PRINCIPAL =====")
    walk(menu.items())


if __name__ == "__main__":
    main()
