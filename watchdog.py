import os
import sys
import time
import subprocess
import datetime
import ctypes
import atexit

if sys.executable.lower().endswith("pythonw.exe"):
    try:
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")
    except: pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "watchdog.log")
LOCK_FILE = os.path.join(BASE_DIR, "watchdog.lock")

# ─── Protección de instancia única ────────────────────────────────────────
def ensure_single_instance():
    """Crea un lock con PID; si otro watchdog ya corre, sale."""
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE, "r") as f:
                old_pid = int(f.read().strip())
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, old_pid)
            if h:
                ec = ctypes.c_ulong()
                ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(ec))
                ctypes.windll.kernel32.CloseHandle(h)
                if ok and ec.value == 259:
                    sys.exit(0)
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
    except: pass

def _cleanup():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except: pass

atexit.register(_cleanup)

ensure_single_instance()

SCRIPTS = [
    ("app.py",              "API Flask"),
    ("monitor.py",          "Monitor archivos"),
    ("remote_listener.py",  "Listener remoto"),
    ("widget.pyw",          "Widget UI"),
]

_PID_CACHE = {}

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[WATCHDOG] {ts} {msg}")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except: pass

def find_pids_by_cmdline_wmi(substring):
    """Retorna lista de PIDs cuyo CommandLine contenga substring usando WMI."""
    pids = []
    try:
        import win32com.client
        wmi = win32com.client.GetObject("winmgmts:{impersonationLevel=impersonate}!\\\\.\\root\\cimv2")
        # Escapar backslashes y caracteres especiales para WQL LIKE
        escaped = substring.replace("\\", "\\\\").replace("'", "\\'")
        query = f"SELECT ProcessId FROM Win32_Process WHERE CommandLine LIKE '%{escaped}%'"
        processes = wmi.ExecQuery(query)
        for proc in processes:
            pids.append(proc.ProcessId)
    except:
        pass
    return pids

def is_alive(pid):
    try:
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if h:
            ec = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(ec))
            ctypes.windll.kernel32.CloseHandle(h)
            return ok and ec.value == 259
        return False
    except: return False

log("=== Watchdog iniciado ===")

while True:
    # Limpiar PID cache de procesos muertos
    dead_pids = [pid for pid in _PID_CACHE if not is_alive(pid)]
    for pid in dead_pids:
        del _PID_CACHE[pid]

    for script, name in SCRIPTS:
        script_path = os.path.join(BASE_DIR, script)
        norm_path = script_path.replace("/", "\\").lower()

        # Buscar PIDs activos con el command line correcto
        pids = find_pids_by_cmdline_wmi(norm_path)
        alive = any(is_alive(pid) for pid in pids) if pids else False

        if not alive:
            log(f"[RESTART] {name} ({script}) no responde. Iniciando...")
            try:
                pythonw = sys.executable.replace("python.exe", "pythonw.exe")
                if not os.path.exists(pythonw):
                    pythonw = sys.executable
                proc = subprocess.Popen(
                    [pythonw, script_path],
                    cwd=BASE_DIR,
                    creationflags=0x08000000,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                _PID_CACHE[proc.pid] = script
                log(f"[OK] {name} reiniciado (PID {proc.pid}).")
            except Exception as e:
                log(f"[ERROR] No se pudo reiniciar {name}: {e}")

    time.sleep(15)
