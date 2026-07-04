"""
inspect_hybrid.py — Inspector de UI (SOLO LECTURA) para HybridLite.

Sirve para "calibrar" la automatización: enumera las ventanas y controles de la
aplicación HybridLite que esté abierta, para descubrir los identificadores
(títulos, class_name, auto_id) que luego usará hybrid_ui.py.

NO escribe nada, NO toca la base de datos, NO hace clics. Solo lee la estructura
de ventanas vía la API de accesibilidad de Windows.

Uso:
    python inspect_hybrid.py                 # lista procesos y ventanas Hybrid
    python inspect_hybrid.py --tree          # vuelca el árbol de controles de la
                                             # ventana activa de Hybrid (backend win32)
    python inspect_hybrid.py --tree --uia    # idem pero con backend UIA
    python inspect_hybrid.py --pid 1234      # inspecciona un proceso por PID
    python inspect_hybrid.py --snapshot      # guarda el volcado a un .txt con fecha
"""
import sys
import io
import datetime

HYBRID_HINTS = ("hybrid", "ptovta", "ptoventa", "litepro", "liteos")


def _print_header(txt):
    print("\n" + "=" * 70)
    print(txt)
    print("=" * 70)


def list_hybrid_windows():
    import win32gui
    import win32process

    _print_header("VENTANAS TOP-LEVEL VISIBLES (posibles candidatas Hybrid)")
    results = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        cls = win32gui.GetClassName(hwnd) or ""
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            pid = -1
        proc_name = _proc_name(pid)
        blob = f"{title} {cls} {proc_name}".lower()
        is_hybrid = any(h in blob for h in HYBRID_HINTS)
        results.append((is_hybrid, hwnd, pid, proc_name, cls, title))

    win32gui.EnumWindows(_cb, None)

    # Primero los que parecen Hybrid, luego el resto (por si el título no ayuda)
    results.sort(key=lambda r: (not r[0], r[3].lower()))
    print(f"{'HWND':>10}  {'PID':>6}  {'PROCESO':<22}  {'CLASS':<24}  TITULO")
    print("-" * 100)
    for is_hybrid, hwnd, pid, proc, cls, title in results:
        mark = ">>" if is_hybrid else "  "
        print(f"{mark}{hwnd:>8}  {pid:>6}  {proc[:22]:<22}  {cls[:24]:<24}  {title[:40]}")
    print("\n(Las filas con '>>' parecen de Hybrid. Usa --pid <PID> o --tree para profundizar.)")
    return results


def _proc_name(pid):
    try:
        import win32api
        import win32con
        import win32process
        h = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        try:
            return win32process.GetModuleFileNameEx(h, 0).split("\\")[-1]
        finally:
            win32api.CloseHandle(h)
    except Exception:
        # Fallback sin permisos: solo el pid
        return f"pid:{pid}"


def dump_tree(pid=None, use_uia=False, depth=None):
    from pywinauto import Application, Desktop

    backend = "uia" if use_uia else "win32"
    _print_header(f"ÁRBOL DE CONTROLES (backend={backend}, pid={pid or 'auto'})")

    app = None
    try:
        if pid:
            app = Application(backend=backend).connect(process=pid, timeout=5)
        else:
            # auto: busca una ventana cuyo título contenga una pista Hybrid
            for w in Desktop(backend=backend).windows():
                try:
                    t = (w.window_text() or "").lower()
                except Exception:
                    continue
                if any(h in t for h in HYBRID_HINTS):
                    pid = w.process_id()
                    app = Application(backend=backend).connect(process=pid, timeout=5)
                    break
        if app is None:
            print("No encontré ninguna ventana Hybrid abierta. Abre HybridLitePro y reintenta,")
            print("o pásame el PID con --pid (míralo con 'python inspect_hybrid.py').")
            return

        for win in app.windows():
            try:
                txt = win.window_text()
            except Exception:
                txt = "<sin titulo>"
            print(f"\n----- Ventana: '{txt}' -----")
            try:
                win.print_control_identifiers(depth=depth)
            except Exception as e:
                print(f"  (no pude volcar identificadores: {e})")
    except Exception as e:
        print(f"ERROR conectando a la app: {e}")
        print("Pistas: 1) la app debe estar ABIERTA y con sesión iniciada;")
        print("        2) prueba con --uia si win32 no muestra los controles;")
        print("        3) ejecuta esta consola como el MISMO usuario que abrió la app.")


def main():
    args = sys.argv[1:]
    use_uia = "--uia" in args
    snapshot = "--snapshot" in args
    pid = None
    if "--pid" in args:
        try:
            pid = int(args[args.index("--pid") + 1])
        except Exception:
            print("--pid requiere un número (PID).")
            return

    out_buffer = None
    if snapshot:
        out_buffer = io.StringIO()
        sys.stdout = _Tee(sys.__stdout__, out_buffer)

    try:
        import win32gui  # noqa  (validar que pywin32 está)
    except ImportError:
        print("Falta pywin32. Instala con:  python -m pip install --user pywin32")
        return

    if "--tree" in args:
        dump_tree(pid=pid, use_uia=use_uia)
    else:
        list_hybrid_windows()
        if pid:
            dump_tree(pid=pid, use_uia=use_uia)

    if snapshot and out_buffer is not None:
        sys.stdout = sys.__stdout__
        fname = f"inspeccion_hybrid_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(out_buffer.getvalue())
        print(f"\n[OK] Volcado guardado en: {fname}")


class _Tee:
    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            try:
                s.write(data)
            except Exception:
                pass

    def flush(self):
        for s in self._streams:
            try:
                s.flush()
            except Exception:
                pass


if __name__ == "__main__":
    main()
