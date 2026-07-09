"""_relanzar_hybrid.py — Cierra HybridLiteOS (ordenado, luego forzado) y lo relanza.
Espera a que aparezca la ventana de login y la deja lista para inspeccionar/grabar."""
import time
import subprocess
import win32gui, win32con, win32process
import flujo_precio as fp

EXE = r"C:\HybridLiteEstacion\HybridLiteOS.exe"
MAIN = "TF_MainHybridCashMG"


def _pids_hybrid():
    import ctypes
    out = set()
    def cb(h, _):
        try:
            _, pid = win32process.GetWindowThreadProcessId(h)
        except Exception:
            return
        try:
            hp = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
            import win32process as wp, win32api
            name = wp.GetModuleFileNameEx(hp, 0).split("\\")[-1].lower()
            win32api.CloseHandle(hp)
            if name == "hybridliteos.exe":
                out.add(pid)
        except Exception:
            pass
    win32gui.EnumWindows(cb, None)
    return out


# 1) cierre ordenado del main (WM_CLOSE)
hm = fp._find_hwnd(MAIN)
if hm:
    print("Cerrando Hybrid (WM_CLOSE)...")
    win32gui.PostMessage(hm, win32con.WM_CLOSE, 0, 0)
    time.sleep(3.0)
    # confirmar diálogos de salida si aparecen (Sí/OK)
    for _ in range(3):
        for cls in ("TFConfirmacion", "TMessageForm"):
            h = fp._find_hwnd(cls)
            if h:
                m = fp._win(h)
                for t in ("&SI", "SI", "Sí", "&Sí", "&Yes", "Yes", "OK", "Aceptar"):
                    try:
                        m.child_window(title=t).click_input(); break
                    except Exception:
                        continue
        time.sleep(0.8)

# 2) forzar si sigue vivo
time.sleep(1.0)
if fp._find_hwnd(MAIN):
    print("Aún vivo; forzando taskkill...")
    subprocess.run(["taskkill", "/F", "/IM", "HybridLiteOS.exe"],
                   capture_output=True)
    time.sleep(2.0)

# 3) relanzar
print("Lanzando HybridLiteOS...")
subprocess.Popen([EXE], cwd=r"C:\HybridLiteEstacion")

# 4) esperar a que aparezca ALGUNA ventana del proceso (login o splash)
t0 = time.time()
while time.time() - t0 < 60:
    ws = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h):
            c = win32gui.GetClassName(h) or ""
            t = win32gui.GetWindowText(h) or ""
            if c.startswith(("TF", "TForm", "TfrmLogin", "TLogin")) or "ogin" in t or "sesi" in t.lower():
                ws.append((c, t[:40]))
    win32gui.EnumWindows(cb, None)
    if ws:
        print("Ventanas visibles:", ws)
        if any("Login" in c or "ogin" in t or "MainHybrid" in c for c, t in ws):
            break
    time.sleep(1.0)
print("Listo. Revisar pantalla.")
