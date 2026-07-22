"""
realinput.py — Input REAL de hardware (SendInput) para HybridLiteOS.

La app rechaza el input sintético de pywinauto (PostMessage) en los disparadores
de carga de datos (la búsqueda responde "Database name is missing"). Con input a
nivel de driver (SendInput / SetCursorPos+mouse_event) la app se comporta igual
que con un humano. Este módulo provee clics y tecleo reales.

OJO: mueve el cursor y teclea de verdad. No uses el equipo mientras corre.
"""
import time
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

# ── constantes ───────────────────────────────────────────────────────────────
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

VK = {
    "ENTER": 0x0D, "TAB": 0x09, "ESC": 0x1B, "BACKSPACE": 0x08,
    "DELETE": 0x2E, "HOME": 0x24, "END": 0x23, "DOWN": 0x28, "UP": 0x26,
    "SPACE": 0x20, "DECIMAL": 0x6E,
}
for i in range(12):
    VK[f"F{i+1}"] = 0x70 + i
VK_NUMPAD = {str(d): 0x60 + d for d in range(10)}   # 0x60..0x69 = NUMPAD0..9
VK_DECIMAL = 0x6E                                    # tecla '.' del teclado numérico


# ── estructuras SendInput ────────────────────────────────────────────────────
ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]


def _send(*inputs):
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    user32.SendInput(n, arr, ctypes.sizeof(INPUT))


# ── teclado ──────────────────────────────────────────────────────────────────
def _key_input(vk=0, scan=0, flags=0):
    return INPUT(type=INPUT_KEYBOARD,
                 u=_INPUTunion(ki=KEYBDINPUT(vk, scan, flags, 0, 0)))


def press_vk(vk, hold=0.015):
    # hold/trailing recortados (0.02/0.03 -> 0.015/0.02): esto multiplica en cada
    # tecla (incluye los 32 borrados de clear_hard). Sigue dando margen a que el OS
    # registre el keyup. NO afecta a type_code (que mantiene su per_char lento).
    _send(_key_input(vk=vk, flags=0))
    time.sleep(hold)
    _send(_key_input(vk=vk, flags=KEYEVENTF_KEYUP))
    time.sleep(0.02)


def press(name, hold=0.02):
    press_vk(VK[name], hold)


def press_shift(key, hold=0.02):
    """SHIFT + tecla de texto (p.ej. press_shift('4') -> '$' en layout latam),
    con input real (mismo patrón SHIFT down/up que select_all_field()). `key`
    es un caracter simple de la fila superior de números (VK == ord(mayúscula))."""
    vk = ord(key.upper())
    _send(_key_input(vk=0x10))                      # SHIFT down
    press_vk(vk, hold)
    _send(_key_input(vk=0x10, flags=KEYEVENTF_KEYUP))  # SHIFT up
    time.sleep(0.03)


def type_text(text, per_char=0.02):
    """Teclea texto como UNICODE (independiente del layout). Ideal para nombres/textos.
    per_char recortado 0.05->0.02 (el hold down/up de 0.01 se mantiene)."""
    for ch in text:
        code = ord(ch)
        _send(_key_input(scan=code, flags=KEYEVENTF_UNICODE))
        time.sleep(0.01)
        _send(_key_input(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        time.sleep(per_char)


def clear_field():
    """Selecciona todo (Ctrl+A) y borra, con input real."""
    # Ctrl down + A + Ctrl up
    _send(_key_input(vk=0x11))                      # CTRL down
    press_vk(0x41)                                  # A
    _send(_key_input(vk=0x11, flags=KEYEVENTF_KEYUP))  # CTRL up
    time.sleep(0.05)
    press("DELETE")


def select_all_field():
    """Selecciona todo con Home + Shift+End (más fiable que Ctrl+A en campos VCL).
    Deja el texto seleccionado para que el siguiente tecleo lo reemplace."""
    press("HOME")
    time.sleep(0.03)
    _send(_key_input(vk=0x10))                      # SHIFT down
    press("END")
    _send(_key_input(vk=0x10, flags=KEYEVENTF_KEYUP))  # SHIFT up
    time.sleep(0.03)


def clear_hard(n=16):
    """Borra el contenido del campo enfocado: END + N backspaces (+ DELETE hacia
    adelante). Fiable en THybridEditNumber (el select-all a veces no reemplaza)."""
    press("END")
    for _ in range(n):
        press_vk(VK["BACKSPACE"], hold=0.01)
    press("HOME")
    for _ in range(n):
        press_vk(VK["DELETE"], hold=0.01)
    time.sleep(0.03)


def type_number(value):
    """Teclea un número por el TECLADO NUMÉRICO (dígitos + tecla decimal), tal como
    lo hace el usuario. La app ignora la coma/punto enviados como texto Unicode;
    la tecla VK_DECIMAL sí produce el separador que el campo acepta.
    Acepta el separador como '.' o ',' en la cadena de entrada."""
    for ch in str(value):
        if ch.isdigit():
            press_vk(VK_NUMPAD[ch], hold=0.015)
        elif ch in ".,":
            press_vk(VK_DECIMAL, hold=0.015)
        # cualquier otro carácter se ignora
        time.sleep(0.015)


VK_SUBTRACT = 0x6D    # tecla '-' del teclado numérico


def type_code(value, per_char=0.08):
    """Teclea un CÓDIGO de producto por el numérico: dígitos por NUMPAD y el guion
    por la tecla '-' del numérico (como hace el usuario en la grilla/búsqueda).
    Las letras u otros caracteres se envían por Unicode.

    IMPORTANTE: se teclea moderadamente lento (per_char ~0.08s). Si se teclea
    demasiado rápido (<0.04s), el autocompletado/lookup de código de la app se
    dispara a mitad y trunca el código (o abre una búsqueda que bloquea)."""
    for ch in str(value):
        if ch.isdigit():
            press_vk(VK_NUMPAD[ch], hold=0.03)
        elif ch == "-":
            press_vk(VK_SUBTRACT, hold=0.03)
        elif ch in ".,":
            press_vk(VK_DECIMAL, hold=0.03)
        else:
            type_text(ch, per_char=0.03)   # letras (p.ej. ZA021)
        time.sleep(per_char)


# ── mouse ────────────────────────────────────────────────────────────────────
def move(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.03)


def click(x, y, double=False):
    # paddings recortados (0.06/0.03/0.12 -> 0.04/0.02/0.07): el down/up mantiene un
    # margen mínimo para que la app registre el clic real; el trailing baja de 0.12 a
    # 0.07 (los flujos ya tienen sus propias esperas explícitas tras cada clic).
    move(x, y)
    time.sleep(0.04)
    _send(INPUT(type=INPUT_MOUSE, u=_INPUTunion(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0))))
    time.sleep(0.02)
    _send(INPUT(type=INPUT_MOUSE, u=_INPUTunion(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0))))
    if double:
        time.sleep(0.04)
        _send(INPUT(type=INPUT_MOUSE, u=_INPUTunion(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0))))
        time.sleep(0.02)
        _send(INPUT(type=INPUT_MOUSE, u=_INPUTunion(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0))))
    time.sleep(0.07)


def click_rect(rect, double=False, fx=0.5, fy=0.5):
    """Clic en un punto relativo dentro de un rect (L,T,R,B) de pywinauto/win32."""
    L, T, R, B = rect
    x = L + (R - L) * fx
    y = T + (B - T) * fy
    click(x, y, double=double)
    return (int(x), int(y))
