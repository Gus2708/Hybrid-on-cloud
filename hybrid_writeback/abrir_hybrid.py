"""
abrir_hybrid.py — Asegura que HybridLiteOS esté ABIERTO y con sesión iniciada.

- Si el módulo principal ya está visible -> no hace nada.
- Si está la pantalla de login -> inicia sesión.
- Si la app está cerrada -> la lanza, espera el login e inicia sesión.

Credenciales: se leen de hybrid_login.json (junto a este script); si no existe, usa
los valores por defecto (user=SU, pass=SU) capturados de la grabación del dueño.
El login es: usuario -> ENTER -> clave -> ENTER (campos THybridEdit del form
TFUserPassMainForm). Todo con INPUT REAL.

Uso:
    python abrir_hybrid.py            # asegura abierto+logueado
    from abrir_hybrid import asegurar_hybrid; asegurar_hybrid()
"""
import os
import sys
import json
import time
import subprocess

import win32gui

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import flujo_precio as fp
import realinput as ri

DIR = os.path.dirname(os.path.abspath(__file__))
EXE = r"C:\HybridLiteEstacion\HybridLiteOS.exe"
EXE_DIR = r"C:\HybridLiteEstacion"
MAIN = "TF_MainHybridCashMG"
LOGIN = "TFUserPassMainForm"
CONF = os.path.join(DIR, "hybrid_login.json")

DEFAULTS = {"usuario": "SU", "clave": "SU"}


def _creds():
    if os.path.exists(CONF):
        try:
            with open(CONF, encoding="utf-8") as f:
                d = json.load(f)
            return d.get("usuario", DEFAULTS["usuario"]), d.get("clave", DEFAULTS["clave"])
        except Exception:
            pass
    return DEFAULTS["usuario"], DEFAULTS["clave"]


def _focus(hwnd):
    try:
        fp._win(hwnd).set_focus()
    except Exception:
        pass
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.3)


def _wait(cls, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = fp._find_hwnd(cls)
        if h:
            return h
        time.sleep(0.5)
    return None


def _campos_login(w):
    """Devuelve (usuario_edit, clave_edit) ordenados por 'top' (usuario arriba)."""
    eds = []
    for cls in ("THybridEdit", "TEdit", "TMaskEdit"):
        for c in w.descendants(class_name=cls):
            eds.append((c.rectangle().top, c))
    eds.sort(key=lambda t: t[0])
    return (eds[0][1] if eds else None,
            eds[1][1] if len(eds) > 1 else None)


def hacer_login(hlogin=None, timeout_main=60):
    usuario, clave = _creds()
    hlogin = hlogin or fp._find_hwnd(LOGIN)
    if not hlogin:
        return False, "No hay pantalla de login."
    _focus(hlogin)
    w = fp._win(hlogin)
    user_edit, pass_edit = _campos_login(w)
    if not user_edit:
        return False, "No ubiqué el campo de usuario."

    # --- USUARIO: enfocar, BORRAR DURO el placeholder, teclear, y VERIFICAR ---
    r = user_edit.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    time.sleep(0.3)
    ri.clear_hard(24)                 # backspaces + deletes (limpia 'USUARIO')
    time.sleep(0.15)
    ri.type_text(usuario, per_char=0.06)
    time.sleep(0.25)
    leido = (user_edit.window_text() or "").strip()
    if leido.lower() != usuario.lower():
        # segundo intento de borrado si quedó el placeholder pegado
        ri.clear_hard(24); time.sleep(0.15)
        ri.type_text(usuario, per_char=0.06); time.sleep(0.25)
        leido = (user_edit.window_text() or "").strip()
    if leido.lower() != usuario.lower():
        return False, (f"El campo usuario quedó como {leido!r}, no {usuario!r} "
                       "(placeholder no borrado). NO envío para no fallar el login.")

    # --- CLAVE: pasar al 2º campo, BORRAR DURO, teclear ---
    ri.press("ENTER")                 # el ENTER pasa al campo de clave
    time.sleep(0.5)
    if pass_edit:                     # respaldo: clic directo en el campo de clave
        rp = pass_edit.rectangle()
        ri.click((rp.left + rp.right) // 2, (rp.top + rp.bottom) // 2)
        time.sleep(0.2)
    ri.clear_hard(24)
    time.sleep(0.15)
    ri.type_text(clave, per_char=0.06)
    time.sleep(0.25)
    ri.press("ENTER")                 # envía el login
    time.sleep(1.0)

    # a veces sale un mensaje (clave incorrecta u otro) -> reportar
    hmsg = fp._find_hwnd("TMessageForm")
    if hmsg and fp._find_hwnd(LOGIN):
        try:
            txt = fp._win(hmsg).window_text()
        except Exception:
            txt = "?"
        return False, f"Login rechazado (mensaje: {txt}). Revisá usuario/clave en hybrid_login.json."

    hmain = _wait(MAIN, timeout=timeout_main)
    if hmain:
        return True, "Sesión iniciada; módulo principal listo."
    if fp._find_hwnd(LOGIN):
        return False, "Sigue en la pantalla de login (¿credenciales incorrectas?)."
    return False, "No apareció el módulo principal tras el login."


def asegurar_hybrid(timeout_login=60, timeout_main=60):
    # 1) ¿ya está el módulo principal?
    if fp._find_hwnd(MAIN):
        return True, "Hybrid ya estaba abierto y logueado."

    # 2) ¿está la pantalla de login?
    if fp._find_hwnd(LOGIN):
        return hacer_login(timeout_main=timeout_main)

    # 3) lanzar la app
    if not os.path.exists(EXE):
        return False, f"No encuentro el ejecutable: {EXE}"
    subprocess.Popen([EXE], cwd=EXE_DIR)

    hlogin = _wait(LOGIN, timeout=timeout_login)
    if hlogin:
        return hacer_login(hlogin, timeout_main=timeout_main)
    # algunas configs entran directo sin login
    if _wait(MAIN, timeout=10):
        return True, "Hybrid abrió directo al módulo principal (sin login)."
    return False, "Lancé Hybrid pero no apareció ni login ni módulo principal."


if __name__ == "__main__":
    ok, msg = asegurar_hybrid()
    print(("OK: " if ok else "FALLO: ") + msg)
    sys.exit(0 if ok else 1)
