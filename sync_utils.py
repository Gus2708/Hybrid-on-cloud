"""
sync_utils.py — Utilidades compartidas entre sync.py y sync_ventas.py.
"""
import sys
import subprocess


def set_priority_low():
    """Establece prioridad baja para no impactar el rendimiento de Windows."""
    if sys.platform == "win32":
        try:
            import win32api, win32process, win32con
            pid = win32api.GetCurrentProcessId()
            handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, True, pid)
            win32process.SetPriorityClass(handle, win32process.BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:
            pass


def _kill_proc(proc):
    """Mata un proceso forzadamente en Windows."""
    try:
        if proc.poll() is None:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=5,
            )
            proc.wait(timeout=5)
    except Exception:
        pass


def safe_decimal(val) -> float:
    """Convierte un valor (incluyendo formato venezolano '1.500,50' y prefijo 'Bs.') a float."""
    if val is None:
        return 0.0
    s = str(val).replace("Bs.", "").replace(" ", "").strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def exponential_backoff(attempt: int) -> float:
    """Calcula delay de backoff exponencial con techo de 15 segundos."""
    return min(1.5 ** attempt, 15.0)
