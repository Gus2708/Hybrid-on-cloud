"""
calibrar_flujo.py — Capturador de calibración (SOLO LECTURA) para HybridLiteOS.

Objetivo: mapear el flujo de UI SIN que Claude/el script hagan clics en el POS.
TÚ navegas la app normalmente; este script vigila las ventanas de HybridLiteOS y,
cada vez que aparece una pantalla/diálogo nuevo, guarda su árbol de controles
(identificadores pywinauto) en un .txt con fecha. Nunca hace clic ni escribe.

Con esos volcados se cablean set_price (navegación → diálogo de precios ya resuelto)
y adjust_stock (documento de ajuste de inventario).

USO:
    cd "C:\\Proyect\\backend serrucho\\hybrid_writeback"
    python calibrar_flujo.py
    # ... deja esta consola corriendo y navega la app a mano ...
    # Ctrl+C para terminar.

QUÉ NAVEGAR (para capturar todo lo necesario):
  A) PRECIO:  Inventario → buscar un producto → abrir su Ficha →
              botón "Costos y Precios" (déjalo abierto un segundo) → Salir.
  B) STOCK :  Inventario → Ajuste de inventario → Nuevo documento →
              (pantalla de línea: producto + cantidad) → observaciones.
              *No hace falta guardar nada; solo que las pantallas se abran.*

Todo lo capturado queda en   calib_<CLASE>_<fecha>.txt   en esta carpeta.
"""
import os
import sys
import time
import datetime

PROC_NAME = "HybridLiteOS.exe"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
POLL_SECS = 0.8


def _proc_name(pid):
    try:
        import win32api, win32con, win32process
        h = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        try:
            return win32process.GetModuleFileNameEx(h, 0).split("\\")[-1]
        finally:
            win32api.CloseHandle(h)
    except Exception:
        return ""


def _hybrid_windows():
    """Lista (hwnd, pid, class, title) de ventanas TOP-LEVEL visibles de HybridLiteOS."""
    import win32gui, win32process
    out = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return
        if _proc_name(pid).lower() != PROC_NAME.lower():
            return
        cls = win32gui.GetClassName(hwnd) or ""
        title = win32gui.GetWindowText(hwnd) or ""
        out.append((hwnd, pid, cls, title))

    win32gui.EnumWindows(_cb, None)
    return out


def _dump_window(pid, hwnd, cls, title):
    """Vuelca los identificadores de una ventana concreta a un .txt con fecha."""
    from pywinauto import Application
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_cls = "".join(c if c.isalnum() else "_" for c in (cls or "win"))[:40]
    fname = os.path.join(OUT_DIR, f"calib_{safe_cls}_{stamp}.txt")
    try:
        app = Application(backend="win32").connect(process=pid, timeout=5)
        win = app.window(handle=hwnd)
        import io
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            print(f"===== CAPTURA: class={cls!r} title={title!r} hwnd={hwnd} pid={pid} =====")
            print(f"Fecha: {stamp}\n")
            win.print_control_identifiers()
        finally:
            sys.stdout = old
        with open(fname, "w", encoding="utf-8") as f:
            f.write(buf.getvalue())
        return fname
    except Exception as e:
        return f"<error volcando {cls}: {e}>"


def main():
    try:
        import win32gui  # noqa
        import pywinauto  # noqa
    except ImportError as e:
        print(f"Falta dependencia ({e}). Instala: python -m pip install --user pywin32 pywinauto")
        return

    print("=" * 66)
    print(" CAPTURADOR DE CALIBRACIÓN (solo lectura) — HybridLiteOS")
    print("=" * 66)
    print(" Navega la app a mano. Cada pantalla NUEVA se guarda sola.")
    print(" Ctrl+C para terminar.\n")

    seen = set()   # claves (class, title) ya capturadas
    # marcar la principal como vista SIN volcarla de nuevo (ya la tenemos), opcional:
    while True:
        try:
            for hwnd, pid, cls, title in _hybrid_windows():
                key = (cls, title)
                if key in seen:
                    continue
                seen.add(key)
                fname = _dump_window(pid, hwnd, cls, title)
                marca = os.path.basename(fname) if fname.endswith(".txt") else fname
                print(f"[{datetime.datetime.now():%H:%M:%S}] Nueva pantalla  "
                      f"class={cls:<24} title={title[:32]!r}  -> {marca}")
            time.sleep(POLL_SECS)
        except KeyboardInterrupt:
            print("\n[fin] Calibración terminada. Volcados en:", OUT_DIR)
            print("      Archivos: calib_*.txt")
            break
        except Exception as e:
            print(f"[aviso] {e}")
            time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
