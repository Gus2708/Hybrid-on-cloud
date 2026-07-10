"""
safety_control.py — Señalización y seguridad para el operador mientras el bot
controla el equipo real (mouse/teclado de hardware vía realinput.py).

Uso:
    from safety_control import control_seguro, fue_abortado

    with control_seguro("BOT ACTIVO — NO TOCAR..."):
        ...automatizacion que mueve mouse/teclado real...

    if fue_abortado():
        ...

Tres capas de protección, cada una degrada con gracia si no está disponible
(nunca lanza excepción por falta de un componente — solo loguea warning):

  1. BANNER visual (tkinter, stdlib) — ventana roja topmost que avisa al
     operador que NO debe tocar el equipo.
  2. HOTKEY F12 (lib `keyboard`, opcional) — aborto de emergencia manual.
  3. BLOCKINPUT (ctypes, stdlib) — bloqueo físico de mouse/teclado, SOLO si
     el proceso corre como administrador.

Advertencias operativas importantes sobre BlockInput (leer antes de confiar
en esta capa):
  (a) BlockInput requiere privilegios de administrador. El listener normalmente
      corre SIN admin (pythonw.exe de usuario) -> en la práctica esta capa
      casi siempre es un no-op silencioso, solo con un warning en el log.
  (b) Con BlockInput activo, Windows descarta el input FÍSICO antes de que
      llegue a los hooks de bajo nivel -> la hotkey F12 física puede NO
      dispararse mientras el input está bloqueado. La vía de escape
      GARANTIZADA en ese caso es Ctrl+Alt+Del, que SIEMPRE reactiva el input
      (Windows lo exige por diseño, ningún proceso puede bloquear esa
      combinación).
  (c) Si el hilo/proceso que llamó BlockInput(True) muere sin llamar
      BlockInput(False), Windows desbloquea el input automáticamente (no
      queda el equipo bloqueado para siempre).
  (d) El input INYECTADO por el propio bot vía SendInput (ver realinput.py)
      NO es bloqueado por BlockInput — por eso el bot puede seguir operando
      con normalidad mientras el humano está bloqueado; BlockInput solo
      filtra el input físico de hardware.
"""
import ctypes
import logging
import threading
import time
from contextlib import contextmanager

log = logging.getLogger("safety")

# ── estado global de aborto ────────────────────────────────────────────────
_abort_flag = threading.Event()


def fue_abortado():
    """True si F12 fue pulsado en esta corrida (flag en memoria)."""
    return _abort_flag.is_set()


# ── capa 3: BLOCKINPUT (ctypes, stdlib) ────────────────────────────────────
def _es_admin():
    """True si el proceso actual corre con privilegios de administrador."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _bloquear_inputs(bloquear):
    """Llama BlockInput(bloquear). Inocuo si no hay admin o si falla:
    solo loguea warning y sigue. Llamar con False es siempre seguro, incluso
    si nunca se bloqueó nada."""
    try:
        ok = ctypes.windll.user32.BlockInput(bool(bloquear))
        if bloquear and not ok:
            # falla típica: sin privilegios de admin -> no-op silencioso de Windows
            log.warning("BlockInput(True) no tuvo efecto (¿sin privilegios de admin?)")
    except Exception as e:
        log.warning("BlockInput no disponible: %s", e)


# ── capa 2: HOTKEY F12 de emergencia (lib `keyboard`, opcional) ───────────
def _abortar():
    """Callback de F12: aborta el bot de inmediato.

    Usa os._exit (no sys.exit) a propósito: esto corta el input real de
    hardware a mitad de flujo sin ejecutar ningún cleanup normal de Python
    (no hay un estado intermedio "seguro" que valga la pena salvar a mitad
    de una automatización de UI). El watchdog del backend revive el proceso,
    y la recuperación de huérfanos marca los items en 'aplicando' como error
    para revisión manual — ese es el comportamiento deseado ante una
    emergencia, no un bug.
    """
    _abort_flag.set()
    _bloquear_inputs(False)  # por si estaba bloqueado, liberar YA al humano
    log.error("¡EMERGENCIA F12! Abortando bot.")
    import os
    os._exit(2)


def _registrar_hotkey():
    """Registra F12 como hotkey global de aborto. Devuelve True si quedó
    activa; False (con warning ya logueado) si la lib `keyboard` no está
    disponible o falla el registro."""
    try:
        import keyboard
    except Exception as e:
        log.warning("Sin hotkey de emergencia (lib 'keyboard' no disponible): %s", e)
        return False
    try:
        keyboard.add_hotkey("f12", _abortar)
        return True
    except Exception as e:
        log.warning("No se pudo registrar hotkey F12: %s", e)
        return False


def _quitar_hotkey():
    """Desregistra la hotkey F12. Nunca lanza."""
    try:
        import keyboard
        keyboard.remove_hotkey("f12")
    except Exception:
        # puede fallar si nunca se registró, o si unhook_all ya limpió todo
        try:
            import keyboard
            keyboard.unhook_all_hotkeys()
        except Exception as e:
            log.warning("No se pudo limpiar hotkey F12: %s", e)


# ── capa 1: BANNER visual (tkinter, stdlib) ────────────────────────────────
# tkinter no es thread-safe entre hilos: TODO el ciclo de vida del root vive
# en UN hilo daemon dedicado. El hilo crea la ventana, corre un bucle propio
# alternando root.update() + sleep corto, y termina apenas ve el Event de
# cierre en True (ahí hace root.destroy() y retorna). El contextmanager solo
# arranca/detiene ese hilo y espera con timeout a que la ventana exista antes
# de seguir, para no arrancar la automatización sin el aviso visible.
class _Banner:
    # colores de la barra — rojo oscuro profesional + franja de acento
    _BG = "#B71C1C"
    _ACCENT = "#7F0000"
    _FG_LINEA1 = "white"
    _FG_ICONO_A = "white"
    _FG_ICONO_B = "#FFEB3B"
    _FG_LINEA2 = "#FFCDD2"
    _PARPADEO_S = 0.6  # período del parpadeo del icono, en segundos

    def __init__(self, mensaje):
        self._mensaje = mensaje
        self._cerrar_evt = threading.Event()
        self._listo_evt = threading.Event()
        self._hilo = None
        # texto de la línea 1: mutable en caliente desde otro hilo vía
        # set_texto(); protegido por _lock porque tkinter no es thread-safe
        # y el bucle _loop_tk es quien único toca los widgets reales
        self._lock = threading.Lock()
        self._texto_actual = mensaje
        self._texto_aplicado = None

    def iniciar(self, timeout=2.0):
        """Arranca el hilo del banner y espera (con timeout) a que la ventana
        quede lista. Si tkinter falla, loguea warning y no bloquea nada más."""
        self._hilo = threading.Thread(target=self._loop_tk, daemon=True,
                                       name="safety-banner")
        self._hilo.start()
        if not self._listo_evt.wait(timeout):
            log.warning("El banner de seguridad no confirmó estar listo a tiempo "
                        "(¿tkinter no disponible en este entorno?)")

    def set_texto(self, texto):
        """Actualiza el texto de la línea principal del banner en caliente.

        Thread-safe: solo guarda el texto nuevo bajo lock. El propio hilo del
        banner (_loop_tk) es quien detecta el cambio y toca el Label real —
        nunca se debe mutar un widget Tk desde un hilo que no sea el suyo.
        Si el banner real no llegó a existir (tkinter falló, tests, etc.)
        esta llamada sigue siendo inofensiva: el texto queda guardado y
        simplemente nadie lo lee.
        """
        with self._lock:
            self._texto_actual = texto

    def _texto_pendiente(self):
        with self._lock:
            return self._texto_actual

    def _aplicar_estilo_click_through(self, root):
        """Hace la ventana click-through y no-activable a nivel de Windows.

        POR QUÉ: el bot clickea al POS con input real de hardware
        (SendInput, ver realinput.py). La barra vive siempre pegada arriba de
        la pantalla; si algún control de HybridLite queda debajo de ella, sin
        WS_EX_TRANSPARENT ese clic lo comería la ventana del banner en vez de
        llegar al POS, y el flujo de automatización fallaría. WS_EX_NOACTIVATE
        evita además que la sola aparición de la barra le robe el foco a
        HybridLite a mitad de una automatización. Ninguna de las dos cosas es
        crítica para que el banner cumpla su función de aviso visual, así que
        cualquier fallo aquí solo se loguea — el banner sigue siendo útil sin
        click-through, simplemente bloquearía clics debajo de sí mismo.
        """
        try:
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020  # los clics ATRAVIESAN la ventana
            WS_EX_NOACTIVATE = 0x08000000   # nunca toma el foco

            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            estilo = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                estilo | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
        except Exception as e:
            log.warning("No se pudo activar click-through en el banner "
                        "(los clics del bot podrían chocar con la barra): %s", e)

    def _loop_tk(self):
        try:
            import tkinter as tk

            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.attributes("-alpha", 0.96)
            root.configure(bg=self._BG)

            # barra de ancho completo de pantalla, pegada arriba, estilo
            # barra de sistema — nada de ventana flotante de 600px
            ancho = root.winfo_screenwidth()
            alto = 48
            root.geometry(f"{ancho}x{alto}+0+0")

            contenedor = tk.Frame(root, bg=self._BG)
            contenedor.pack(expand=True, fill="both")

            fila1 = tk.Frame(contenedor, bg=self._BG)
            fila1.pack(pady=(6, 0))

            label_icono = tk.Label(fila1, text="⚠", bg=self._BG,
                                    fg=self._FG_ICONO_A,
                                    font=("Segoe UI", 13, "bold"))
            label_icono.pack(side="left", padx=(0, 8))

            label_principal = tk.Label(fila1, text=self._mensaje, bg=self._BG,
                                        fg=self._FG_LINEA1,
                                        font=("Segoe UI", 13, "bold"))
            label_principal.pack(side="left")

            label_secundario = tk.Label(
                contenedor,
                text="No toques el teclado ni el mouse   ·   "
                     "F12 = abortar de emergencia",
                bg=self._BG, fg=self._FG_LINEA2, font=("Segoe UI", 9))
            label_secundario.pack(pady=(0, 4))

            franja = tk.Frame(root, bg=self._ACCENT, height=3)
            franja.pack(side="bottom", fill="x")

            self._aplicar_estilo_click_through(root)

            self._listo_evt.set()

            icono_encendido = True
            ultimo_parpadeo = time.monotonic()
            self._texto_aplicado = self._mensaje

            # bucle propio: nada de mainloop() bloqueante, así podemos
            # revisar el Event de cierre y salir del hilo con destroy() limpio
            while not self._cerrar_evt.is_set():
                ahora = time.monotonic()

                if ahora - ultimo_parpadeo >= self._PARPADEO_S:
                    icono_encendido = not icono_encendido
                    label_icono.config(
                        fg=self._FG_ICONO_A if icono_encendido else self._FG_ICONO_B)
                    ultimo_parpadeo = ahora

                texto_pendiente = self._texto_pendiente()
                if texto_pendiente != self._texto_aplicado:
                    label_principal.config(text=texto_pendiente)
                    self._texto_aplicado = texto_pendiente

                root.update()
                time.sleep(0.05)

            root.destroy()
        except Exception as e:
            # cualquier fallo de Tk (sin display, sin tkinter, etc.) no debe
            # tumbar al bot bajo pythonw -- solo lo dejamos registrado
            log.warning("Banner de seguridad no disponible: %s", e)
            self._listo_evt.set()  # no dejar colgado a quien espera el timeout

    def cerrar(self):
        self._cerrar_evt.set()
        if self._hilo is not None:
            self._hilo.join(timeout=2.0)
            if self._hilo.is_alive():
                log.warning("El hilo del banner de seguridad no terminó a tiempo")


# ── API pública ─────────────────────────────────────────────────────────────
@contextmanager
def control_seguro(mensaje="BOT ACTIVO — APLICANDO CAMBIOS EN HYBRIDLITE"):
    """Envuelve una sección donde el bot controla el equipo:
      1. Muestra un banner rojo topmost con `mensaje` (línea 1; la línea 2,
         fija, ya trae la advertencia de no tocar y la hotkey F12).
      2. Registra hotkey global F12 = aborto de emergencia.
      3. Si el proceso corre como admin, bloquea el input físico (BlockInput).
    Al salir (normal o por excepción): desbloquea input, quita hotkey, cierra banner.
    Cada capa degrada con gracia si no está disponible (sin tkinter, sin lib
    keyboard, sin admin): loguea warning y sigue — NUNCA lanza por eso.

    Yieldea un handle con `.set_texto(str)` para actualizar la línea 1 del
    banner en caliente durante la automatización (p.ej. el listener puede ir
    narrando qué item se está aplicando). Si el banner real no llegó a
    existir, el handle sigue siendo el mismo objeto `_Banner` y su
    `set_texto` es inofensivo (solo guarda el texto; nadie lo lee) — no hace
    falta una clase separada de "no-op" para ese caso.

    `with control_seguro():` sin `as` sigue funcionando igual que antes.
    """
    _abort_flag.clear()
    banner = _Banner(mensaje)

    try:
        banner.iniciar()
        _registrar_hotkey()

        if _es_admin():
            _bloquear_inputs(True)
        else:
            log.info("Proceso sin privilegios de admin: BlockInput no se activa "
                     "(el banner y F12 siguen protegiendo)")

        yield banner
    finally:
        # orden inverso, y cada paso protegido: liberar al humano es lo más
        # importante, así que BlockInput(False) va primero y siempre se llama
        _bloquear_inputs(False)
        _quitar_hotkey()
        try:
            banner.cerrar()
        except Exception as e:
            log.warning("No se pudo cerrar el banner de seguridad con normalidad: %s", e)


# ── demo manual (NO se ejecuta al importar; correr `python safety_control.py`) ──
if __name__ == "__main__":
    # Demo SEGURA: solo banner, ~6 segundos, SIN BlockInput y SIN os._exit,
    # para que el operador pueda probar visualmente el banner y el cambio de
    # texto en caliente (set_texto) a mano.
    print("Demo de safety_control: mostrando banner ~6s (sin bloqueo de input)...")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with control_seguro("DEMO — banner de prueba (sin bloqueo real)") as banner:
        print("Banner visible. Esperando 3 segundos...")
        time.sleep(3)
        print("Actualizando texto con set_texto()...")
        banner.set_texto("DEMO — set_texto() en caliente funcionando")
        time.sleep(3)
    print(f"Demo terminada. fue_abortado() = {fue_abortado()}")
