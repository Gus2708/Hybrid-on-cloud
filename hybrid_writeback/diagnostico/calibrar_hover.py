"""
calibrar_hover.py — Captura posiciones de botones por HOVER (SOLO LECTURA).

Para los controles que Windows no expone (menú lateral de imágenes, botones de
icono de la barra de la Ficha), este script registra DÓNDE están: tú dejas el
mouse quieto encima de cada uno ~1.5 segundos (SIN hacer clic) y el script
guarda la posición relativa a su ventana. Nunca hace clic ni escribe.

USO:
    cd "C:\\Proyect\\backend serrucho\\hybrid_writeback"
    python calibrar_hover.py

Luego pasa el mouse (quieto ~1.5s, sin clic) por estos puntos EN ESTE ORDEN:

  1. Menú lateral izquierdo del módulo principal: el ítem/categoría "INVENTARIO"
     (el que hace aparecer los botones 'Items de Inventario', 'Ajustes...', etc.)
  2. En la FICHA DE INVENTARIO: el botón que abre la BÚSQUEDA de productos.
  3. En la FICHA DE INVENTARIO: el botón GUARDAR.
  4. (opcional) cualquier otro botón que uses en el flujo; me dices cuál fue.

Cada captura suena un beep y se imprime. Ctrl+C para terminar: se guarda todo
en calib_hover_<fecha>.txt con el orden de captura.
"""
import os
import time
import datetime

import win32api
import win32gui
import win32process

PROC_NAME = "hybridliteos.exe"
DWELL_SECS = 1.5          # tiempo quieto para registrar
RADIUS = 6                # px de tolerancia de "quieto"
MIN_DIST_NEW = 25         # px mínimos respecto al último punto registrado
OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def _proc_name(pid):
    try:
        import win32con
        h = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        try:
            return win32process.GetModuleFileNameEx(h, 0).split("\\")[-1].lower()
        finally:
            win32api.CloseHandle(h)
    except Exception:
        return ""


def _top_level(hwnd):
    import win32con
    GA_ROOT = 2
    try:
        import ctypes
        return ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT)
    except Exception:
        return hwnd


def _info_at(pt):
    """Devuelve info de la ventana/control bajo el cursor, o None si no es Hybrid."""
    hwnd = win32gui.WindowFromPoint(pt)
    if not hwnd:
        return None
    top = _top_level(hwnd)
    try:
        _, pid = win32process.GetWindowThreadProcessId(top)
    except Exception:
        return None
    if _proc_name(pid) != PROC_NAME:
        return None
    top_cls = win32gui.GetClassName(top) or ""
    top_title = win32gui.GetWindowText(top) or ""
    top_rect = win32gui.GetWindowRect(top)          # (L, T, R, B)
    child_cls = win32gui.GetClassName(hwnd) or ""
    child_txt = win32gui.GetWindowText(hwnd) or ""
    child_rect = win32gui.GetWindowRect(hwnd)
    rel = (pt[0] - top_rect[0], pt[1] - top_rect[1])
    rel_child = (pt[0] - child_rect[0], pt[1] - child_rect[1])
    return {
        "screen": pt,
        "top": {"class": top_cls, "title": top_title, "rect": top_rect, "rel": rel},
        "child": {"class": child_cls, "text": child_txt, "rect": child_rect,
                  "rel": rel_child},
    }


def main():
    print("=" * 66)
    print(" CALIBRACIÓN POR HOVER — deja el mouse quieto ~1.5s sobre cada botón")
    print(" (SIN hacer clic). Beep = capturado. Ctrl+C para terminar.")
    print("=" * 66)
    print(" Orden sugerido: 1) menú lateral 'INVENTARIO'  2) Ficha: botón BUSCAR")
    print("                 3) Ficha: botón GUARDAR\n")

    capturas = []
    anchor = None          # (x, y) donde empezó la quietud
    anchor_t = None
    last_saved = None      # último punto guardado

    try:
        while True:
            pt = win32api.GetCursorPos()
            now = time.time()

            if anchor is None or abs(pt[0] - anchor[0]) > RADIUS or abs(pt[1] - anchor[1]) > RADIUS:
                anchor, anchor_t = pt, now
                time.sleep(0.08)
                continue

            if now - anchor_t >= DWELL_SECS:
                if last_saved and abs(pt[0] - last_saved[0]) <= MIN_DIST_NEW \
                        and abs(pt[1] - last_saved[1]) <= MIN_DIST_NEW:
                    time.sleep(0.08)
                    continue
                info = _info_at(pt)
                if info:
                    capturas.append(info)
                    last_saved = pt
                    win32api.MessageBeep(0x40)  # MB_ICONASTERISK
                    n = len(capturas)
                    t = info["top"]
                    c = info["child"]
                    print(f"[{n}] {t['class']} '{t['title'][:30]}'  rel_ventana={t['rel']}  "
                          f"control={c['class']} '{c['text'][:20]}' rel_control={c['rel']}")
                anchor_t = now + 3600  # no re-capturar el mismo dwell
            time.sleep(0.08)
    except KeyboardInterrupt:
        pass

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = os.path.join(OUT_DIR, f"calib_hover_{stamp}.txt")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(f"# Capturas de hover — {stamp}\n")
        f.write("# Orden pedido: 1=menu lateral INVENTARIO, 2=Ficha BUSCAR, 3=Ficha GUARDAR, resto=extra\n\n")
        for i, cap in enumerate(capturas, 1):
            t, c = cap["top"], cap["child"]
            f.write(f"[{i}] screen={cap['screen']}\n")
            f.write(f"    ventana: class={t['class']!r} title={t['title']!r} rect={t['rect']} rel={t['rel']}\n")
            f.write(f"    control: class={c['class']!r} text={c['text']!r} rect={c['rect']} rel={c['rel']}\n\n")
    print(f"\n[fin] {len(capturas)} puntos guardados en {os.path.basename(fname)}")


if __name__ == "__main__":
    main()
