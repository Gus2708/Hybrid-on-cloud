"""
hybrid_health.py — Detecta si HybridLiteOS quedó COLGADO y lo recupera matando
TODAS sus instancias, para que el flujo pueda arrancar una limpia.

Problema real que resuelve: cada tanto HybridLiteOS deja de responder (ventana
"no responde", o un proceso que quedó en memoria sin ventana y traba el
arranque de instancias nuevas). Hasta ahora el bot no lo distinguía de un
Hybrid sano: `asegurar_hybrid()` intentaba reutilizar/lanzar sobre una app
muerta, el flujo fallaba en "abrir_hybrid" y alguien tenía que ir al
Administrador de tareas a matar todo a mano.

Ahora `abrir_hybrid.asegurar_hybrid()` llama a `recuperar_si_colgado()` ANTES
de cada flujo: si confirma un cuelgue, mata todos los HybridLiteOS.exe y deja
la casa limpia para que el mismo `asegurar_hybrid()` lance y loguee una
instancia nueva y el flujo siga su curso.

DOS SÍNTOMAS de cuelgue (cualquiera alcanza):
  a) una ventana visible de Hybrid no bombea mensajes (IsHungAppWindow /
     SendMessageTimeout con SMTO_ABORTIFHUNG);
  b) un proceso HybridLiteOS.exe vivo SIN ninguna ventana visible propia
     (instancia fantasma: no sirve para nada y suele trabar los .Dat). Solo
     cuenta si el proceso ya tiene sus buenos segundos de vida: uno recién
     lanzado todavía no dibujó su ventana y NO es un fantasma.

⚠️ ESTA ES LA ÚNICA EXCEPCIÓN a la regla "nunca taskkill /IM HybridLiteOS.exe"
(ver abrir_hybrid.cerrar_aislada): el kill acá es a TODAS las instancias, así
que también se lleva la ventana que un empleado pudiera tener abierta. Por eso
solo se dispara con el cuelgue CONFIRMADO tras `HYBRID_HANG_GRACE` segundos de
insistir — una app colgada ya le hizo perder el trabajo al empleado igual, y
una operación pesada momentánea (un reporte largo) se descarta con la gracia.

Variables de entorno (todas opcionales):
  HYBRID_HANG_GRACE     segundos que el síntoma debe SOSTENERSE para
                        considerarlo cuelgue real (default 10; 0 = actuar al
                        primer síntoma, no recomendado).
  HYBRID_HANG_KILL      "0" para diagnosticar sin matar nada (default: mata).
  HYBRID_HANG_PING_MS   timeout de cada ping a una ventana (default 800 ms).
  HYBRID_HANG_EDAD_MIN  edad mínima de un proceso sin ventana para tratarlo
                        como fantasma (default 90 s: margen para que un Hybrid
                        que está arrancando lento alcance a mostrarla).
  HYBRID_HANG_SETTLE    pausa tras el kill, para que el SO libere los handles
                        de los .Dat antes de relanzar (default 3 s).
  HYBRID_HANG_EXES      lista separada por comas de ejecutables a matar
                        (default "hybridliteos.exe").

Uso manual (diagnóstico, no toca nada):
    python hybrid_health.py
    python hybrid_health.py --matar     # mata todas las instancias, colgadas o no
"""
import ctypes
import datetime
import logging
import os
import subprocess
import sys
import time
from ctypes import wintypes

import pywintypes
import win32api
import win32con
import win32gui
import win32process

try:
    h_def = ctypes.windll.user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if h_def:
        ctypes.windll.user32.SetThreadDesktop(h_def)
except Exception:
    pass

log = logging.getLogger("hybrid_health")


def _env_float(nombre, default):
    try:
        return float(os.environ.get(nombre, "") or default)
    except ValueError:
        return default


EXES = tuple(e.strip().lower()
             for e in os.environ.get("HYBRID_HANG_EXES", "hybridliteos.exe").split(",")
             if e.strip())
GRACIA_S = _env_float("HYBRID_HANG_GRACE", 10.0)
PING_MS = int(_env_float("HYBRID_HANG_PING_MS", 800))
ESPERA_TRAS_MATAR = _env_float("HYBRID_HANG_SETTLE", 3.0)
EDAD_MIN_FANTASMA = _env_float("HYBRID_HANG_EDAD_MIN", 90.0)
MATAR_HABILITADO = os.environ.get("HYBRID_HANG_KILL", "1") != "0"

PAUSA_RECHEQUEO = 1.5      # s entre reconfirmaciones dentro de la gracia
TIMEOUT_MUERTE = 15        # s de espera a que los procesos desaparezcan de verdad

# ─── API de Windows para "¿esta ventana responde?" ──────────────────────────
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.IsHungAppWindow.argtypes = [wintypes.HWND]
_user32.IsHungAppWindow.restype = wintypes.BOOL
_user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
]
_user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t

WM_NULL = 0x0000
SMTO_ABORTIFHUNG = 0x0002
ERROR_INVALID_WINDOW_HANDLE = 1400


def responde(hwnd, timeout_ms=None):
    """True si la ventana bombea mensajes (app viva).

    Un WM_NULL con SMTO_ABORTIFHUNG es el ping estándar: no hace nada en la app
    y vuelve enseguida. Si la ventana se destruyó entre el enum y el ping se
    considera "responde" (no es un cuelgue, simplemente ya no está)."""
    timeout_ms = PING_MS if timeout_ms is None else timeout_ms
    if _user32.IsHungAppWindow(hwnd):
        return False
    resultado = ctypes.c_size_t()
    ctypes.set_last_error(0)
    if _user32.SendMessageTimeoutW(hwnd, WM_NULL, 0, 0, SMTO_ABORTIFHUNG,
                                   timeout_ms, ctypes.byref(resultado)):
        return True
    return ctypes.get_last_error() == ERROR_INVALID_WINDOW_HANDLE


# ─── Inventario de procesos y ventanas de Hybrid ────────────────────────────
def _nombre_proceso(pid):
    """Nombre del ejecutable de `pid` en minúsculas, o None si no se puede
    consultar (proceso de otro usuario, ya muerto, del sistema, etc.)."""
    try:
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except Exception:
        return None
    try:
        return os.path.basename(win32process.GetModuleFileNameEx(handle, 0)).lower()
    except Exception:
        return None
    finally:
        win32api.CloseHandle(handle)


def edad_proceso(pid):
    """Segundos desde que arrancó `pid`, o None si no se puede consultar."""
    try:
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except Exception:
        return None
    try:
        creado = win32process.GetProcessTimes(handle)["CreationTime"]
        return (datetime.datetime.now(datetime.timezone.utc) - creado).total_seconds()
    except Exception:
        return None
    finally:
        win32api.CloseHandle(handle)


def pids_hybrid():
    """PIDs vivos de HybridLiteOS.exe — TODAS las instancias, la del empleado y
    las aisladas del bot. Barrer los ~260 procesos del equipo cuesta ~17 ms, así
    que es barato hacerlo al inicio de cada flujo."""
    try:
        todos = win32process.EnumProcesses()
    except Exception as e:
        log.warning("No pude enumerar procesos: %r", e)
        return set()
    return {pid for pid in todos if _nombre_proceso(pid) in EXES}


def ventanas_visibles(pids):
    """[(hwnd, pid, clase)] de las ventanas top-level VISIBLES de esos PIDs.
    Una instancia sana siempre tiene al menos una (el módulo principal, aunque
    esté minimizado: IsWindowVisible sigue en True)."""
    out = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        try:
            pid = win32process.GetWindowThreadProcessId(hwnd)[1] & 0xFFFFFFFF
        except Exception:
            return
        if pid in pids:
            out.append((hwnd, pid, win32gui.GetClassName(hwnd)))

    # Mismo retry que flujo_precio._find_hwnd: EnumWindows tira error 122 si una
    # ventana se destruye a mitad de la enumeración.
    for _ in range(3):
        try:
            win32gui.EnumWindows(_cb, None)
            break
        except pywintypes.error:
            out.clear()
            time.sleep(0.1)
    return out


def _sintoma(pids):
    """Descripción del problema AHORA MISMO, o None si Hybrid está sano."""
    ventanas = ventanas_visibles(pids)
    sin_ventana = pids - {pid for _, pid, _ in ventanas}
    # Un proceso recién lanzado todavía no dibujó su ventana: NO es fantasma.
    # Sin esta guarda, un empleado abriendo Hybrid (o nuestra propia instancia
    # arrancando) se vería como cuelgue y le mataríamos el arranque.
    fantasmas = sorted(pid for pid in sin_ventana
                       if (edad_proceso(pid) or 0) >= EDAD_MIN_FANTASMA)
    if fantasmas:
        return (f"proceso(s) HybridLiteOS.exe {fantasmas} vivos SIN ninguna "
                "ventana visible (instancia fantasma)")
    colgadas = [(pid, clase) for hwnd, pid, clase in ventanas if not responde(hwnd)]
    if colgadas:
        detalle = ", ".join(f"{clase} (PID {pid})" for pid, clase in colgadas)
        return f"{len(colgadas)} ventana(s) de Hybrid sin responder: {detalle}"
    return None


# ─── Diagnóstico y recuperación ─────────────────────────────────────────────
def diagnosticar(gracia=None, logger=None):
    """None si Hybrid está sano (o directamente no está corriendo); si no, el
    texto del síntoma CONFIRMADO.

    Reconfirma el síntoma durante `gracia` segundos antes de darlo por cuelgue:
    una operación pesada (un reporte largo, un .Dat grande) deja la ventana sin
    responder unos segundos y NO es motivo para matar la app de nadie."""
    lg = logger or log
    gracia = GRACIA_S if gracia is None else gracia
    pids = pids_hybrid()
    if not pids:
        return None
    sintoma = _sintoma(pids)
    if sintoma is None:
        return None

    lg.warning("HybridLite parece colgado (%s); reconfirmando hasta %.0fs antes de actuar.",
               sintoma, gracia)
    t0 = time.time()
    while time.time() - t0 < gracia:
        time.sleep(PAUSA_RECHEQUEO)
        pids = pids_hybrid()
        if not pids:
            lg.info("Los procesos de Hybrid se cerraron solos; no hay nada que matar.")
            return None
        sintoma = _sintoma(pids)
        if sintoma is None:
            lg.info("HybridLite volvió a responder tras %.1fs; no se toca nada.",
                    time.time() - t0)
            return None
    return f"{sintoma} — sostenido {gracia:.0f}s"


def matar_todo(logger=None, espera=None):
    """Mata TODAS las instancias de HybridLiteOS.exe. (ok, detalle).

    Se lleva puesta también la ventana de un empleado: llamar solo con un
    cuelgue confirmado (ver el aviso del docstring del módulo)."""
    lg = logger or log
    espera = ESPERA_TRAS_MATAR if espera is None else espera
    antes = pids_hybrid()
    if not antes:
        return True, "no había procesos de HybridLiteOS.exe vivos."

    for exe in EXES:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/IM", exe],
                           capture_output=True, timeout=20)
        except Exception as e:
            lg.error("taskkill /IM %s falló: %r", exe, e)

    # taskkill vuelve antes de que el SO termine de bajar los procesos.
    t0 = time.time()
    quedan = pids_hybrid()
    while quedan and time.time() - t0 < TIMEOUT_MUERTE:
        time.sleep(0.5)
        quedan = pids_hybrid()
    for pid in sorted(quedan):
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=10)
        except Exception as e:
            lg.error("taskkill /PID %s falló: %r", pid, e)
    if quedan:
        time.sleep(1)
        quedan = pids_hybrid()
    if quedan:
        return False, f"quedaron procesos de Hybrid vivos tras el kill: {sorted(quedan)}."

    if espera > 0:
        # que el SO libere los handles de los .Dat antes de relanzar
        time.sleep(espera)
    return True, f"matadas {len(antes)} instancia(s) de Hybrid (PIDs {sorted(antes)})."


def recuperar_si_colgado(gracia=None, logger=None):
    """Chequeo de arranque de flujo: detecta un cuelgue de HybridLite y, si lo
    confirma, mata TODAS las instancias para que el llamador lance una limpia.

    Devuelve (accion, detalle):
      "sano"        -> Hybrid responde (o no está corriendo); detalle None.
      "recuperado"  -> estaba colgado y ya no queda ningún proceso: relanzar.
      "fallo"       -> está colgado y NO se pudo dejar limpio (kill deshabilitado
                       o procesos que no murieron): el flujo debe abortar."""
    lg = logger or log
    sintoma = diagnosticar(gracia=gracia, logger=lg)
    if sintoma is None:
        return "sano", None
    if not MATAR_HABILITADO:
        lg.error("HybridLite COLGADO (%s) pero HYBRID_HANG_KILL=0: no mato nada.", sintoma)
        return "fallo", f"{sintoma}; el kill automático está deshabilitado (HYBRID_HANG_KILL=0)"
    lg.warning("HybridLite COLGADO (%s) -> matando TODAS las instancias para arrancar de cero.",
               sintoma)
    ok, detalle = matar_todo(logger=lg)
    if not ok:
        lg.error("No pude dejar limpio Hybrid: %s", detalle)
        return "fallo", f"{sintoma}; {detalle}"
    lg.warning("Hybrid colgado recuperado: %s Se relanza una instancia nueva.", detalle)
    return "recuperado", f"{sintoma}; {detalle}"


def matar_huerfanos(pids_previos, logger=None):
    """Mata los procesos de Hybrid que NO existían en `pids_previos` y no
    llegaron a mostrar ninguna ventana visible.

    Se usa cuando un intento de lanzar la instancia aislada no produjo ventana:
    sin esto el proceso a medio arrancar queda en memoria como fantasma y va
    ensuciando el equipo intento tras intento. SEGURO: solo toca PIDs que
    aparecieron durante ESTE intento, nunca la instancia de un empleado."""
    lg = logger or log
    nuevos = pids_hybrid() - set(pids_previos)
    if not nuevos:
        return 0
    con_ventana = {pid for _, pid, _ in ventanas_visibles(nuevos)}
    huerfanos = sorted(nuevos - con_ventana)
    for pid in huerfanos:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=10)
            lg.warning("Proceso de Hybrid huérfano (PID %s, sin ventana) cerrado.", pid)
        except Exception as e:
            lg.error("No pude cerrar el proceso huérfano %s: %r", pid, e)
    return len(huerfanos)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pids = pids_hybrid()
    print(f"Procesos HybridLiteOS.exe vivos: {sorted(pids) or 'ninguno'}")
    for hwnd, pid, clase in ventanas_visibles(pids):
        estado = "responde" if responde(hwnd) else "NO RESPONDE"
        print(f"  hwnd={hwnd} pid={pid} {clase} -> {estado}")

    if "--matar" in sys.argv:
        ok, detalle = matar_todo()
        print(("OK: " if ok else "FALLO: ") + detalle)
        sys.exit(0 if ok else 1)

    sintoma = diagnosticar()
    print("Diagnóstico: " + (sintoma or "Hybrid sano (o no está corriendo)."))
    sys.exit(1 if sintoma else 0)
