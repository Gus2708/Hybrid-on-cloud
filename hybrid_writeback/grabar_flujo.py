"""
grabar_flujo.py — Graba clics y teclas MIENTRAS el dueño cambia un precio a mano.

Objetivo: descubrir la interacción EXACTA que la app acepta (cómo se dispara la
búsqueda, cómo se selecciona el producto, cómo se abre Costos y Precios, cómo se
guarda), para replicarla. No hace clics ni escribe: solo observa.

Privacidad: SOLO registra eventos cuando la ventana al frente pertenece a
HybridLiteOS.exe. Si pasas a otra app (navegador, WhatsApp, etc.) no se graba nada.

Salida: escribe en vivo (append) a  grabar_flujo_<fecha>.log  (una línea por evento).

Parar: presiona **F12** dentro de Hybrid, o cierra este proceso.

Uso:
    cd "C:\\Proyect\\backend serrucho\\hybrid_writeback"
    python grabar_flujo.py
"""
import os
import time
import datetime
import ctypes
from ctypes import wintypes

import win32gui
import win32api
import win32con
import win32process

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Tipos correctos para 64 bits (evita OverflowError con punteros grandes)
LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t
HHOOK = ctypes.c_void_p
LPMSG = ctypes.c_void_p

user32.SetWindowsHookExW.restype = HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.UnhookWindowsHookEx.argtypes = [HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207

DIR = os.path.dirname(os.path.abspath(__file__))
STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOGPATH = os.path.join(DIR, f"grabar_flujo_{STAMP}.log")
PROC_NAME = "hybridliteos.exe"

_last_click = {"t": 0.0, "x": -1, "y": -1}
_stop = False
_mouse_cb = None
_kbd_cb = None
_logf = open(LOGPATH, "a", encoding="utf-8", buffering=1)  # line-buffered


# ─── mapa de teclas ──────────────────────────────────────────────────────────
_VK = {
    0x08: "BACKSPACE", 0x09: "TAB", 0x0D: "ENTER", 0x1B: "ESC", 0x20: "SPACE",
    0x25: "LEFT", 0x26: "UP", 0x27: "RIGHT", 0x28: "DOWN",
    0x2D: "INS", 0x2E: "DEL", 0x24: "HOME", 0x23: "END",
    0x21: "PGUP", 0x22: "PGDN",
    0x10: "SHIFT", 0x11: "CTRL", 0x12: "ALT",
    0xA0: "LSHIFT", 0xA1: "RSHIFT", 0xA2: "LCTRL", 0xA3: "RCTRL",
}
for i in range(12):
    _VK[0x70 + i] = f"F{i+1}"


def _keyname(vk):
    if vk in _VK:
        return _VK[vk]
    if 0x30 <= vk <= 0x39:
        return chr(vk)              # 0-9
    if 0x41 <= vk <= 0x5A:
        return chr(vk)              # A-Z
    if 0x60 <= vk <= 0x69:
        return f"NUM{vk-0x60}"
    # puntuación común
    m = {0xBE: ".", 0xBC: ",", 0xBD: "-", 0xBB: "+", 0xBF: "/", 0xC0: "`",
         0xDB: "[", 0xDD: "]", 0xDC: "\\", 0xBA: ";", 0xDE: "'"}
    return m.get(vk, f"VK_{vk:02X}")


# ─── utilidades de ventana ───────────────────────────────────────────────────
def _proc_name(pid):
    try:
        h = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        try:
            return os.path.basename(win32process.GetModuleFileNameEx(h, 0)).lower()
        finally:
            win32api.CloseHandle(h)
    except Exception:
        return ""


def _top(hwnd):
    return user32.GetAncestor(hwnd, 2)  # GA_ROOT


def _is_hybrid_fg():
    fg = win32gui.GetForegroundWindow()
    if not fg:
        return False, None
    _, pid = win32process.GetWindowThreadProcessId(fg)
    if _proc_name(pid) != PROC_NAME:
        return False, None
    return True, fg


def _emit(line):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    full = f"[{ts}] {line}"
    print(full, flush=True)
    _logf.write(full + "\n")


def _describe_point(x, y):
    hwnd = win32gui.WindowFromPoint((x, y))
    if not hwnd:
        return None
    top = _top(hwnd)
    _, pid = win32process.GetWindowThreadProcessId(top)
    if _proc_name(pid) != PROC_NAME:
        return None
    top_cls = win32gui.GetClassName(top) or ""
    top_title = win32gui.GetWindowText(top) or ""
    L, T, _, _ = win32gui.GetWindowRect(top)
    child_cls = win32gui.GetClassName(hwnd) or ""
    child_txt = win32gui.GetWindowText(hwnd) or ""
    cl, ct, _, _ = win32gui.GetWindowRect(hwnd)
    return {
        "top_cls": top_cls, "top_title": top_title,
        "rel_top": (x - L, y - T),
        "child_cls": child_cls, "child_txt": child_txt[:40],
        "rel_child": (x - cl, y - ct),
    }


# ─── procedimientos de hook ──────────────────────────────────────────────────
CMPFUNC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class MSLL(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class KBDLL(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


def mouse_proc(nCode, wParam, lParam):
    try:
        if nCode == 0 and wParam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
            ms = ctypes.cast(lParam, ctypes.POINTER(MSLL)).contents
            x, y = ms.pt.x, ms.pt.y
            info = _describe_point(x, y)
            if info is not None:
                btn = {WM_LBUTTONDOWN: "L", WM_RBUTTONDOWN: "R", WM_MBUTTONDOWN: "M"}[wParam]
                now = time.time()
                dbl = (btn == "L" and now - _last_click["t"] < 0.45
                       and abs(x - _last_click["x"]) < 6 and abs(y - _last_click["y"]) < 6)
                _last_click.update(t=now, x=x, y=y)
                kind = "DBLCLICK" if dbl else f"{btn}CLICK"
                _emit(f"{kind:9} ventana={info['top_cls']} '{info['top_title'][:32]}' "
                      f"rel={info['rel_top']} | control={info['child_cls']} "
                      f"'{info['child_txt']}' relctrl={info['rel_child']}")
    except Exception as e:
        try:
            _emit(f"(err mouse_proc: {e})")
        except Exception:
            pass
    return user32.CallNextHookEx(None, nCode, wParam, lParam)


def kbd_proc(nCode, wParam, lParam):
    global _stop
    try:
        if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLL)).contents
            name = _keyname(kb.vkCode)
            if name == "F12":
                _emit("F12 -> STOP solicitado")
                _stop = True
                user32.PostQuitMessage(0)
                return user32.CallNextHookEx(None, nCode, wParam, lParam)
            is_hy, fg = _is_hybrid_fg()
            if is_hy:
                top_cls = win32gui.GetClassName(fg) or ""
                top_title = win32gui.GetWindowText(fg) or ""
                try:
                    foco = win32gui.GetFocus()
                    fcls = win32gui.GetClassName(foco) if foco else ""
                except Exception:
                    fcls = ""
                _emit(f"KEY {name:9} ventana={top_cls} '{top_title[:32]}' foco={fcls}")
    except Exception as e:
        try:
            _emit(f"(err kbd_proc: {e})")
        except Exception:
            pass
    return user32.CallNextHookEx(None, nCode, wParam, lParam)


def main():
    _emit(f"=== GRABANDO (solo cuando Hybrid está al frente). Log: {os.path.basename(LOGPATH)} ===")
    _emit("Haz el cambio de precio a mano como siempre. Presiona F12 para terminar.")

    global _mouse_cb, _kbd_cb  # mantener referencias vivas (evita GC del callback)
    _mouse_cb = CMPFUNC(mouse_proc)
    _kbd_cb = CMPFUNC(kbd_proc)
    hm = user32.SetWindowsHookExW(WH_MOUSE_LL, ctypes.cast(_mouse_cb, ctypes.c_void_p), None, 0)
    hk = user32.SetWindowsHookExW(WH_KEYBOARD_LL, ctypes.cast(_kbd_cb, ctypes.c_void_p), None, 0)
    if not hm or not hk:
        _emit("ERROR: no pude instalar los hooks.")
        return

    msg = wintypes.MSG()
    try:
        while not _stop:
            r = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)  # PM_REMOVE
            if r:
                if msg.message == win32con.WM_QUIT:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(0.004)
    except KeyboardInterrupt:
        pass
    finally:
        user32.UnhookWindowsHookEx(hm)
        user32.UnhookWindowsHookEx(hk)
        _emit("=== FIN de la grabación ===")
        _logf.close()


if __name__ == "__main__":
    main()
