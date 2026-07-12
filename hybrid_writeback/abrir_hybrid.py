"""
abrir_hybrid.py — Asegura que haya una instancia AISLADA de HybridLiteOS
abierta y con sesión iniciada, para que el bot trabaje ahí sin tocar la
ventana que un empleado pueda tener abierta haciendo ajustes/compras.

`asegurar_hybrid()` (usada por flujo_stock_real.py y flujo_precio_real.py)
NUNCA reutiliza el módulo principal que ya esté visible: eso era exactamente
el bug — si un empleado estaba a mitad de un ajuste o una compra sin guardar,
el bot tomaba control real del teclado/mouse SOBRE ESA MISMA ventana y el
empleado perdía el trabajo en curso. Ahora:

  1. Si ya existe una instancia aislada abierta por una pasada anterior de
     ESTE proceso (mismo PID vivo) -> la reutiliza (evita relanzar/loguear en
     cada pasada del listener).
  2. Si no, lanza SIEMPRE un proceso NUEVO de HybridLiteOS.exe y detecta cuál
     ventana de login/módulo-principal es la NUEVA (por diff de hwnds antes/
     después de lanzar — robusto a que el exe relance un proceso hijo con
     otro PID). Ninguna ventana preexistente (la del empleado) se toca.
  3. Todo lo que pasa después (flujo_precio_real, flujo_stock_real, y este
     mismo módulo) queda restringido a esa instancia vía
     flujo_precio.set_target_pid() — ver ese módulo para el filtro real.

Credenciales: se leen de hybrid_login.json (junto a este script); si no existe, usa
los valores por defecto (user=SU, pass=SU) capturados de la grabación del dueño.
El login teclea usuario y clave con clic DIRECTO en cada campo THybridEdit del
form TFUserPassMainForm (SIN un ENTER intermedio entre ambos: ese ENTER disparaba
el submit con la clave vacía y desordenaba el form), y recién al final ENTER
para enviar. Todo con INPUT REAL.

Uso:
    python abrir_hybrid.py            # asegura una instancia aislada abierta+logueada
    from abrir_hybrid import asegurar_hybrid; asegurar_hybrid()
"""
import os
import sys
import json
import time
import subprocess

import win32gui
import win32process

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


def _llenar_campo_login(edit, valor):
    """Enfoca un campo de login (triple-clic + select-all + clear_hard) y teclea
    `valor` con INPUT REAL. Devuelve el window_text final (stripped).

    Los THybridEdit del login muestran un placeholder decorativo ('USUARIO' /
    'CLAVE') cuando están vacíos; backspace normal no lo borra, por eso el
    triple-clic (selecciona todo) + select_all_field + clear_hard. Al escribir,
    el campo de usuario muestra el texto real; el de clave (password) queda con
    window_text '' porque oculta el contenido — el llamador decide si entró
    comparando contra el placeholder inicial, no contra el valor."""
    r = edit.rectangle()
    cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
    ri.click(cx, cy); time.sleep(0.15)
    ri.click(cx, cy); time.sleep(0.15)
    ri.click(cx, cy); time.sleep(0.3)      # triple-clic: activa y selecciona todo
    ri.select_all_field(); time.sleep(0.12)
    ri.clear_hard(24); time.sleep(0.12)
    ri.type_text(valor, per_char=0.06); time.sleep(0.25)
    return (edit.window_text() or "").strip()


def hacer_login(hlogin=None, timeout_main=60, antes_main=None):
    """Inicia sesión en la ventana de login `hlogin`.

    `antes_main` (opcional): set de hwnds de MAIN existentes ANTES de lanzar la
    instancia nueva. Si se pasa, el módulo principal se detecta como una
    ventana MAIN *nueva* (diff), y el PID objetivo se RE-HOMOLOGA al de esa
    ventana — robusto al caso en que el login y el módulo principal corran en
    procesos distintos (login como stub lanzador). Si es None (p.ej. reuso de
    una instancia aislada trabada en login), se usa la espera clásica por PID."""
    global _AISLADO_PID
    usuario, clave = _creds()
    hlogin = hlogin or fp._find_hwnd(LOGIN)
    if not hlogin:
        return False, "No hay pantalla de login."
    _focus(hlogin)
    w = fp._win(hlogin)
    user_edit, pass_edit = _campos_login(w)
    if not user_edit:
        return False, "No ubiqué el campo de usuario."
    if not pass_edit:
        return False, "No ubiqué el campo de clave."

    # placeholders decorativos iniciales ('USUARIO' / 'CLAVE'), para saber si
    # cada campo llegó a aceptar texto (el de clave oculta el contenido).
    ph_clave = (pass_edit.window_text() or "").strip()

    # --- USUARIO: clic directo + borrado robusto + teclear, hasta 3 intentos ---
    leido = _llenar_campo_login(user_edit, usuario)
    for _ in range(2):
        if leido.lower() == usuario.lower():
            break
        leido = _llenar_campo_login(user_edit, usuario)
    if leido.lower() != usuario.lower():
        return False, (f"El campo usuario quedó como {leido!r}, no {usuario!r} "
                       "(placeholder no borrado). NO envío para no fallar el login.")

    # --- CLAVE: clic DIRECTO en el 2º campo (NO un ENTER intermedio) ---
    # BUG ARREGLADO (2026-07-11, confirmado en vivo): el ENTER que se hacía tras
    # el usuario disparaba el submit del login con la clave vacía y desordenaba
    # el form -> la clave nunca se colocaba. Se va directo al campo de clave.
    # El campo es password: window_text queda '' al escribir; se considera que
    # NO entró solo si sigue mostrando el placeholder inicial ('CLAVE').
    leido_clave = _llenar_campo_login(pass_edit, clave)
    intentos_clave = 0
    while ph_clave and leido_clave == ph_clave and intentos_clave < 2:
        leido_clave = _llenar_campo_login(pass_edit, clave)
        intentos_clave += 1
    if ph_clave and leido_clave == ph_clave:
        return False, ("El campo de clave no aceptó el texto (sigue con el "
                       "placeholder). NO envío para no fallar el login.")

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

    if antes_main is not None:
        # Detección robusta: el módulo principal es una ventana MAIN que NO
        # existía antes de lanzar la instancia. Re-homologa el PID objetivo al
        # de esa ventana (puede diferir del PID del login).
        hmain = fp._esperar_ventana_nueva(MAIN, antes_main, timeout=timeout_main)
        if hmain:
            pid = _pid_de(hmain)
            if pid is not None:
                _AISLADO_PID = pid
                fp.set_target_pid(pid)
            return True, "Sesión iniciada; módulo principal (instancia aislada) listo."
    else:
        hmain = _wait(MAIN, timeout=timeout_main)
        if hmain:
            return True, "Sesión iniciada; módulo principal listo."
    if fp._find_hwnd(LOGIN):
        return False, "Sigue en la pantalla de login (¿credenciales incorrectas?)."
    return False, "No apareció el módulo principal tras el login."


# PID de la instancia AISLADA que este proceso ya abrió (si alguna). Se
# reutiliza entre pasadas consecutivas del listener para no relanzar+loguear
# HybridLite cada vez; si esa ventana ya no existe (se cerró, crasheó) se
# detecta y se lanza una instancia nueva.
_AISLADO_PID = None


def _pid_de(hwnd):
    try:
        return win32process.GetWindowThreadProcessId(hwnd)[1] & 0xFFFFFFFF
    except Exception:
        return None


def _instancia_aislada_viva():
    """hwnd de MAIN o LOGIN de la instancia aislada ya conocida (_AISLADO_PID),
    si sigue existiendo. None si no hay una registrada o ya se cerró."""
    if _AISLADO_PID is None:
        return None, None
    for cls in (MAIN, LOGIN):
        out = []

        def _cb(h, _, cls=cls, out=out):
            if not win32gui.IsWindowVisible(h):
                return
            if win32gui.GetClassName(h) != cls:
                return
            if _pid_de(h) != _AISLADO_PID:
                return
            out.append(h)

        win32gui.EnumWindows(_cb, None)
        if out:
            return cls, out[0]
    return None, None


def asegurar_hybrid(timeout_login=60, timeout_main=60):
    """Asegura una instancia AISLADA de HybridLite abierta+logueada, sin
    tocar la ventana que un empleado pueda tener abierta (ver docstring del
    módulo). Deja flujo_precio.set_target_pid() apuntando a esa instancia."""
    global _AISLADO_PID

    # 1) ¿la instancia aislada de una pasada anterior sigue viva? -> reusarla
    cls_viva, h_viva = _instancia_aislada_viva()
    if h_viva:
        fp.set_target_pid(_AISLADO_PID)
        if cls_viva == MAIN:
            # pudo quedar minimizada por minimizar_aislada() al final de la
            # pasada anterior: SetForegroundWindow solo no la restaura de
            # forma confiable, hay que pedir SW_RESTORE primero.
            try:
                import win32con
                win32gui.ShowWindow(h_viva, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(h_viva)
            except Exception:
                pass
            return True, "Reutilizando la instancia aislada de Hybrid ya abierta."
        return hacer_login(h_viva, timeout_main=timeout_main)
    _AISLADO_PID = None
    fp.clear_target_pid()

    # 2) no hay instancia aislada viva -> lanzar SIEMPRE una instancia NUEVA.
    #    NUNCA se reutiliza el módulo principal/login que ya esté visible:
    #    esa ventana puede ser la de un empleado trabajando ahora mismo.
    if not os.path.exists(EXE):
        return False, f"No encuentro el ejecutable: {EXE}"

    antes_login = fp._hwnds_de_clase(LOGIN)
    antes_main = fp._hwnds_de_clase(MAIN)
    subprocess.Popen([EXE], cwd=EXE_DIR)

    hlogin = fp._esperar_ventana_nueva(LOGIN, antes_login, timeout=timeout_login)
    if hlogin:
        pid = _pid_de(hlogin)
        if pid is None:
            return False, "Apareció una pantalla de login nueva pero no pude leer su PID."
        # Provisional: apuntar al PID del login para que el tecleo y el chequeo
        # de mensaje de error queden scopeados a ESE proceso. hacer_login
        # re-homologa el target al PID del módulo principal (puede diferir).
        _AISLADO_PID = pid
        fp.set_target_pid(pid)
        return hacer_login(hlogin, timeout_main=timeout_main, antes_main=antes_main)

    # algunas configs entran directo al módulo principal, sin login
    hmain = fp._esperar_ventana_nueva(MAIN, antes_main, timeout=10)
    if hmain:
        pid = _pid_de(hmain)
        if pid is None:
            return False, "Abrió el módulo principal pero no pude leer su PID."
        _AISLADO_PID = pid
        fp.set_target_pid(pid)
        return True, "Hybrid abrió una instancia nueva y aislada, directo al módulo principal (sin login)."

    return False, ("Lancé una instancia nueva de Hybrid pero no detecté ni login ni "
                   "módulo principal NUEVOS (¿la app bloquea multi-instancia en este equipo?).")


def minimizar_aislada():
    """Minimiza (no cierra) la ventana principal de la instancia aislada al
    terminar una pasada, para no dejar una segunda ventana de Hybrid tapando
    la pantalla del empleado. Se queda abierta en la barra de tareas y se
    restaura sola en la próxima pasada (ver _instancia_aislada_viva). Inocuo
    si no hay instancia aislada o ya se cerró."""
    cls_viva, h_viva = _instancia_aislada_viva()
    if cls_viva == MAIN and h_viva:
        try:
            import win32con
            win32gui.ShowWindow(h_viva, win32con.SW_MINIMIZE)
        except Exception as e:
            print(f"No pude minimizar la instancia aislada de Hybrid: {e}")


if __name__ == "__main__":
    ok, msg = asegurar_hybrid()
    print(("OK: " if ok else "FALLO: ") + msg)
    sys.exit(0 if ok else 1)
