"""find_ficha.py — Localiza la ventana 'Ficha de Inventario' (top-level o hija MDI)
y su botón 'Guardar'. SOLO LECTURA."""
import win32gui
import win32process
from pywinauto import Application


def hybrid_pid():
    h = []
    win32gui.EnumWindows(lambda x, _: h.append(x), None)
    for w in h:
        if win32gui.GetClassName(w) == "TF_MainHybridCashMG":
            return win32process.GetWindowThreadProcessId(w)[1]
    return None


def main():
    pid = hybrid_pid()
    if not pid:
        print("HybridLiteOS no está abierto.")
        return
    app = Application(backend="win32").connect(process=pid, timeout=5)

    print("=== Ventanas top-level del proceso que contengan 'Ficha' ===")
    for w in app.windows():
        try:
            t = w.window_text()
            c = w.class_name()
        except Exception:
            continue
        if "Ficha" in (t or "") or "Ficha" in (c or ""):
            print(f"  TOP class={c!r} title={t!r}")

    print("\n=== Buscando 'Ficha de Inventario' en todo el árbol (incl. hijas) ===")
    from pywinauto import Desktop
    for w in Desktop(backend="win32").windows():
        if w.process_id() != pid:
            continue
        for d in [w] + w.descendants():
            try:
                t = d.window_text()
                c = d.class_name()
            except Exception:
                continue
            if "Ficha de Inventario" in (t or ""):
                print(f"  -> class={c!r} title={t!r} hwnd={d.handle}")
                # buscar botones dentro
                try:
                    for b in d.descendants(class_name="TButton"):
                        print(f"       TButton: {b.window_text()!r}")
                except Exception as e:
                    print(f"       (no pude listar botones: {e})")
                return


if __name__ == "__main__":
    main()
