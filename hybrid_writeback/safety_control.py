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


# ── capa 0: MUTEX de mouse entre procesos (listener_writeback / listener_compras) ──
# listener_writeback.py y listener_compras.py corren como procesos SEPARADOS y
# AMBOS toman el mouse/teclado real (SendInput vía realinput.py) dentro de
# `control_seguro`. Si llegaran a pisarse (por ejemplo un sondeo de compras
# arranca mientras un ajuste de stock sigue en curso), los dos bots clickearían
# la misma pantalla a la vez -> input entreverado, alto riesgo de escribir en
# el campo/documento equivocado de HybridLite. Un Mutex con nombre de Windows
# ("Local\\...") es visible entre procesos (no solo entre hilos, a diferencia
# de threading.Lock) y serializa el acceso: el segundo proceso que llegue
# espera a que el primero libere el mouse antes de arrancar su propia pasada.
_MOUSE_MUTEX_NAME = "Local\\SerruchoBotMouseLock"
_MOUSE_MUTEX_TIMEOUT_MS = 5 * 60 * 1000  # 5 min: una pasada normal no debería tardar tanto


def _adquirir_mutex_mouse():
    """Crea/abre el mutex con nombre y espera a tenerlo. Degradación con
    gracia: si ctypes/kernel32 falla por cualquier motivo, loguea warning y
    sigue igual (no bloquear el bot para siempre por falta de esta capa).
    Devuelve el handle (o None si no se pudo adquirir/crear)."""
    try:
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, _MOUSE_MUTEX_NAME)
        if not handle:
            log.warning("No se pudo crear/abrir el mutex de mouse %r (GetLastError=%s)",
                        _MOUSE_MUTEX_NAME, ctypes.windll.kernel32.GetLastError())
            return None
        WAIT_FAILED = 0xFFFFFFFF
        WAIT_TIMEOUT = 0x00000102
        resultado = ctypes.windll.kernel32.WaitForSingleObject(handle, _MOUSE_MUTEX_TIMEOUT_MS)
        if resultado == WAIT_TIMEOUT:
            log.warning("Timeout de %ss esperando el mutex de mouse %r (¿el otro listener "
                        "quedó colgado sosteniéndolo?); sigo SIN el mutex para no bloquear "
                        "este proceso para siempre.", _MOUSE_MUTEX_TIMEOUT_MS // 1000, _MOUSE_MUTEX_NAME)
            return handle  # no se adquirió el lock, pero igual devolvemos el handle para poder CloseHandle
        if resultado == WAIT_FAILED:
            log.warning("WaitForSingleObject falló sobre el mutex de mouse %r (GetLastError=%s)",
                        _MOUSE_MUTEX_NAME, ctypes.windll.kernel32.GetLastError())
        return handle
    except Exception as e:
        log.warning("Mutex de mouse entre procesos no disponible (degradado, sin serializar "
                    "con otros listeners): %s", e)
        return None


def _liberar_mutex_mouse(handle):
    """Libera y cierra el handle del mutex. Nunca lanza."""
    if handle is None:
        return
    try:
        ctypes.windll.kernel32.ReleaseMutex(handle)
    except Exception as e:
        log.warning("No se pudo liberar el mutex de mouse (sigo cerrando el handle): %s", e)
    try:
        ctypes.windll.kernel32.CloseHandle(handle)
    except Exception as e:
        log.warning("No se pudo cerrar el handle del mutex de mouse: %s", e)


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

    # panel lateral de productos pendientes (a la derecha del banner)
    _PANEL_BG = "#1B1B1B"
    _PANEL_TITULO_FG = "#FFEB3B"
    _PANEL_ANCHO = 320
    _PANEL_ALTO_MAX = 640

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
        # lista de productos pendientes del panel lateral: [(texto, hecho)].
        # Mismo patrón de lock que _texto_actual/set_texto.
        self._lista_actual = []
        self._lista_aplicada = None

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

    def set_lista(self, items):
        """Actualiza la lista de productos del panel lateral (a la derecha
        del banner). `items`: iterable de (texto, hecho) — hecho=True tacha
        ese renglón (ya aplicado en HybridLite). Pensada para llamarse una
        vez por item a medida que el listener los va completando, para que
        el operador vea en vivo qué falta y qué ya está.

        Thread-safe: solo guarda la lista bajo lock; el hilo del banner
        (_loop_tk) es quien redibuja los Labels reales. Si la ventana del
        panel no llegó a existir (tkinter falló), esta llamada sigue siendo
        inofensiva, igual que set_texto()."""
        with self._lock:
            self._lista_actual = list(items)

    def _lista_pendiente(self):
        with self._lock:
            return list(self._lista_actual)

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
            LWA_ALPHA = 0x00000002

            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            estilo = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                estilo | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)

            # CRÍTICO (bug confirmado: el banner salía INVISIBLE): al re-setear
            # el exstyle con SetWindowLong, Windows descarta la opacidad que
            # tkinter había puesto con -alpha, y la ventana layered queda 100%
            # transparente aunque el click-through funcione. Hay que re-aplicar
            # la opacidad a mano para que se vea. 245 ≈ 0.96*255 (el mismo -alpha).
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 245, LWA_ALPHA)
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

            # ── panel lateral de productos pendientes (a la derecha) ──────
            # Toplevel aparte (no cabe en la barra de 48px). Empieza oculto
            # (withdraw) y solo se muestra cuando set_lista() trae algo —
            # los usos del banner que no llaman set_lista() (flujos de
            # precio/stock corridos a mano) no ven ningún panel.
            panel = tk.Toplevel(root)
            panel.overrideredirect(True)
            panel.attributes("-topmost", True)
            panel.attributes("-alpha", 0.96)
            panel.configure(bg=self._PANEL_BG)
            panel.geometry(f"{self._PANEL_ANCHO}x1+{ancho - self._PANEL_ANCHO}+{alto + 4}")

            panel_titulo = tk.Label(
                panel, text="PRODUCTOS DE ESTA ORDEN", bg=self._PANEL_BG,
                fg=self._PANEL_TITULO_FG, font=("Segoe UI", 9, "bold"),
                anchor="w")
            panel_titulo.pack(fill="x", padx=10, pady=(8, 4))

            panel_lista = tk.Frame(panel, bg=self._PANEL_BG)
            panel_lista.pack(fill="both", expand=True, padx=10, pady=(0, 8))

            self._aplicar_estilo_click_through(panel)
            panel.withdraw()

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

                lista_pendiente = self._lista_pendiente()
                if lista_pendiente != self._lista_aplicada:
                    for w in panel_lista.winfo_children():
                        w.destroy()
                    if lista_pendiente:
                        for texto, hecho in lista_pendiente:
                            prefijo = "✓ " if hecho else "• "
                            estilo = ("Segoe UI", 10, "overstrike") if hecho else ("Segoe UI", 10)
                            tk.Label(
                                panel_lista, text=prefijo + texto,
                                bg=self._PANEL_BG,
                                fg="#4CAF50" if hecho else "white",
                                font=estilo, anchor="w", justify="left",
                                wraplength=self._PANEL_ANCHO - 24,
                            ).pack(fill="x", anchor="w", pady=1)
                        alto_panel = min(self._PANEL_ALTO_MAX,
                                          44 + 22 * len(lista_pendiente))
                        panel.geometry(
                            f"{self._PANEL_ANCHO}x{alto_panel}"
                            f"+{ancho - self._PANEL_ANCHO}+{alto + 4}")
                        panel.deiconify()
                    else:
                        panel.withdraw()
                    self._lista_aplicada = lista_pendiente

                root.update()
                time.sleep(0.05)

            panel.destroy()
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


# ── ocultar ventanas que estorban (widget del backend) ──────────────────────
def _pids_de_scripts(scripts):
    """PIDs de procesos pythonw/python cuyo commandline contiene alguno de
    `scripts` (ej. 'widget.pyw'). Vía WMI, mismo patrón que backend_watchdog."""
    pids = set()
    try:
        import win32com.client
        wmi = win32com.client.GetObject("winmgmts:")
        for proc in wmi.ExecQuery(
                "SELECT ProcessId, CommandLine FROM Win32_Process "
                "WHERE Name = 'pythonw.exe' OR Name = 'python.exe'"):
            cl = proc.CommandLine or ""
            if any(s in cl for s in scripts):
                pids.add(int(proc.ProcessId))
    except Exception as e:
        log.warning("No pude listar procesos para ocultar sus ventanas: %s", e)
    return pids


def _ocultar_ventanas_de_scripts(scripts):
    """Oculta (SW_HIDE) todas las ventanas top-level visibles de los procesos
    de `scripts`. Devuelve la lista de hwnds ocultados (para restaurarlos).

    POR QUÉ ocultar y no minimizar: el widget (widget.pyw / widget_recargo.pyw)
    es overrideredirect + topmost (sin barra de título), así que 'minimizar' se
    comporta mal; ocultarlo es limpio y garantiza que no tape ni coma clics de
    los diálogos de HybridLite mientras el bot trabaja.
    """
    ocultados = []
    pids = _pids_de_scripts(scripts)
    if not pids:
        return ocultados
    try:
        import win32gui
        import win32process
        import win32con

        def _cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                return
            if pid in pids:
                win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                ocultados.append(hwnd)

        win32gui.EnumWindows(_cb, None)
    except Exception as e:
        log.warning("No pude ocultar ventanas del widget: %s", e)
    if ocultados:
        log.info("Ocultadas %s ventana(s) de %s durante el flujo.", len(ocultados), scripts)
    return ocultados


def _restaurar_ventanas(hwnds):
    """Vuelve a mostrar (SW_SHOW) y re-topmost las ventanas ocultadas."""
    if not hwnds:
        return
    try:
        import win32gui
        import win32con
    except Exception:
        return
    for hwnd in hwnds:
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
        except Exception:
            pass


# ── API pública ─────────────────────────────────────────────────────────────
@contextmanager
def control_seguro(mensaje="BOT ACTIVO — APLICANDO CAMBIOS EN HYBRIDLITE",
                   ocultar_scripts=None):
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

    `ocultar_scripts` (opcional): lista de nombres de script (ej.
    ["widget.pyw"]) cuyas ventanas se OCULTAN al empezar y se restauran al
    salir — el widget del backend es topmost y tapa/come clics de los diálogos
    de HybridLite mientras el bot trabaja.

    `with control_seguro():` sin `as` sigue funcionando igual que antes.
    """
    _abort_flag.clear()
    banner = _Banner(mensaje)
    ventanas_ocultas = []

    # Capa 0 (ver comentario junto a _adquirir_mutex_mouse): serializa el
    # mouse entre listener_writeback y listener_compras ANTES de mostrar el
    # banner o tocar nada más, para que nunca haya dos bots clickeando la
    # pantalla al mismo tiempo.
    mutex_handle = _adquirir_mutex_mouse()

    try:
        banner.iniciar()
        _registrar_hotkey()

        if ocultar_scripts:
            ventanas_ocultas = _ocultar_ventanas_de_scripts(ocultar_scripts)

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
        _restaurar_ventanas(ventanas_ocultas)
        try:
            banner.cerrar()
        except Exception as e:
            log.warning("No se pudo cerrar el banner de seguridad con normalidad: %s", e)
        # Liberar el mutex de mouse AL FINAL de todo (después de restaurar
        # input/ventanas/banner): así el próximo proceso que lo esperaba no
        # arranca a mover el mouse mientras este todavía está en su cleanup.
        _liberar_mutex_mouse(mutex_handle)


# ── demo manual (NO se ejecuta al importar; correr `python safety_control.py`) ──
if __name__ == "__main__":
    # Demo SEGURA: solo banner, ~6 segundos, SIN BlockInput y SIN os._exit,
    # para que el operador pueda probar visualmente el banner y el cambio de
    # texto en caliente (set_texto) a mano.
    print("Demo de safety_control: banner ~6s + ocultar widget (sin bloqueo de input)...")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with control_seguro("DEMO — banner de prueba (sin bloqueo real)",
                        ocultar_scripts=["widget.pyw", "widget_recargo.pyw"]) as banner:
        print("Banner visible arriba + widget oculto. Esperando 3 segundos...")
        time.sleep(3)
        print("Actualizando texto con set_texto()...")
        banner.set_texto("DEMO — set_texto() en caliente funcionando")
        time.sleep(3)
    print(f"Demo terminada (widget restaurado). fue_abortado() = {fue_abortado()}")
