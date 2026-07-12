"""
dump_form.py — Vuelca los controles de un formulario de HybridLite (SOLO LECTURA).

Uso:
    python dump_form.py                      # lista todos los TForm* de la app
    python dump_form.py TFUserPassMainForm   # vuelca ese formulario por class_name
    python dump_form.py "Modulo Principal"   # ...o por parte del título
    python dump_form.py <algo> --snapshot    # además guarda a archivo .txt
"""
import sys
import io
import datetime
import win32gui
import win32process
from pywinauto import Application

HINT_EXE = "hybridliteos"


def find_app_pid():
    """Devuelve el pid del proceso que tiene formularios Delphi 'TF...' de Hybrid."""
    candidates = {}
    handles = []
    win32gui.EnumWindows(lambda h, _: handles.append(h), None)
    for h in handles:
        cls = win32gui.GetClassName(h) or ""
        title = win32gui.GetWindowText(h) or ""
        if cls.startswith("TF") or "hybrid" in title.lower():
            pid = win32process.GetWindowThreadProcessId(h)[1]
            candidates[pid] = candidates.get(pid, 0) + 1
    if not candidates:
        return None
    # el pid con más formularios Delphi es la app
    return max(candidates, key=candidates.get)


def list_forms(pid):
    print(f"\nFormularios visibles/ocultos del pid {pid}:")
    print(f"{'VIS':>3}  {'CLASS':<32}  TITULO")
    print("-" * 80)
    handles = []
    win32gui.EnumWindows(lambda h, _: handles.append(h), None)
    for h in handles:
        if win32process.GetWindowThreadProcessId(h)[1] != pid:
            continue
        cls = win32gui.GetClassName(h) or ""
        if not (cls.startswith("TF") or cls.startswith("TForm")):
            continue
        vis = "1" if win32gui.IsWindowVisible(h) else "0"
        title = win32gui.GetWindowText(h) or ""
        print(f"{vis:>3}  {cls[:32]:<32}  {title[:40]}")


def dump(pid, selector):
    app = Application(backend="win32").connect(process=pid, timeout=5)
    # intentar por class_name exacto, luego por título (regex parcial)
    win = None
    try:
        win = app.window(class_name=selector)
        win.wait("exists", timeout=3)
    except Exception:
        win = None
    if win is None:
        try:
            win = app.window(title_re=f".*{selector}.*")
            win.wait("exists", timeout=3)
        except Exception:
            win = None
    if win is None:
        print(f"No encontré un formulario que coincida con '{selector}'.")
        print("Ejecuta sin argumentos para ver la lista de formularios disponibles.")
        return
    print(f"\n===== Controles de '{win.window_text()}' (class={win.class_name()}) =====")
    win.print_control_identifiers(depth=None)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    snapshot = "--snapshot" in sys.argv

    buf = None
    if snapshot:
        buf = io.StringIO()
        real = sys.stdout

        class _Tee:
            def write(self, d):
                real.write(d); buf.write(d)
            def flush(self):
                real.flush()
        sys.stdout = _Tee()

    pid = find_app_pid()
    if not pid:
        print("No encontré HybridLiteOS abierto. Ábrelo e inicia sesión primero.")
        return

    if not args:
        list_forms(pid)
    else:
        dump(pid, args[0])

    if snapshot and buf is not None:
        sys.stdout = sys.__stdout__
        fn = f"dump_{(args[0] if args else 'forms')}_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt"
        fn = "".join(c for c in fn if c.isalnum() or c in "._-")
        with open(fn, "w", encoding="utf-8") as f:
            f.write(buf.getvalue())
        print(f"\n[OK] Guardado en {fn}")


if __name__ == "__main__":
    main()
