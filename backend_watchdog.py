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

# --- Globals ---
_PID_MAP = {}
_RESTART_COOLDOWN = {}
_WMI_CACHE = None

def is_alive(pid):
    if not pid: return False
    try:
        # PROCESS_QUERY_LIMITED_INFORMATION (0x1000)
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if h:
            ec = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(ec))
            ctypes.windll.kernel32.CloseHandle(h)
            return ok and ec.value == 259
        return False
    except: return False

def get_wmi():

    """Retorna un objeto WMI cacheado para búsquedas rápidas."""
    global _WMI_CACHE
    if _WMI_CACHE is not None: return _WMI_CACHE
    try:
        import win32com.client
        # CoInitialize no es necesario en hilos principales de scripts simples
        _WMI_CACHE = win32com.client.GetObject("winmgmts:")
        return _WMI_CACHE
    except:
        return None

def find_pids_by_script_name(script_name):
    """Busca PIDs activos cuyo CommandLine contenga el nombre del script."""
    # 1. Intentar vía WMI (más rápido si pywin32 está instalado)
    wmi_service = get_wmi()
    if wmi_service:
        try:
            escaped_name = script_name.replace("'", "''")
            # Filtrar por Name para evitar buscar en procesos que no sean python
            query = f"SELECT ProcessId FROM Win32_Process WHERE Name LIKE 'python%' AND CommandLine LIKE '%{escaped_name}%'"
            processes = wmi_service.ExecQuery(query)
            pids = [proc.ProcessId for proc in processes]
            if pids: return pids
        except: pass

    # 2. Fallback vía WMIC (nativo en Windows, muy fiable)
    try:
        # Escapar caracteres para CMD/WMIC
        cmd = f'wmic process where "name like \'python%\' and commandline like \'%{script_name}%\'" get processid /value'
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, creationflags=0x08000000).decode().strip()
        pids = []
        for line in output.splitlines():
            if "ProcessId=" in line:
                pid_str = line.split("=")[1].strip()
                if pid_str.isdigit(): pids.append(int(pid_str))
        if pids: return pids
    except: pass

    # 3. Último recurso: PowerShell (con escapado de $_)
    try:
        ps_cmd = f"Get-CimInstance Win32_Process | Where-Object {{ \$_.Name -like 'python*' -and \$_.CommandLine -like '*{script_name}*' }} | Select-Object -ExpandProperty ProcessId"
        cmd = f"powershell -NoProfile -Command \"{ps_cmd}\""
        output = subprocess.check_output(cmd, shell=True, creationflags=0x08000000).decode().strip()
        if output:
            return [int(pid) for pid in output.splitlines() if pid.strip().isdigit()]
    except: pass

    return []


def log(msg):

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[WATCHDOG] {ts} {msg}")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except: pass

# ─── Protección de instancia única ────────────────────────────────────────────
def ensure_single_instance():
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE, "r") as f:
                content = f.read().strip()
                if content.isdigit():
                    old_pid = int(content)
                    if is_alive(old_pid):
                        sys.exit(0)
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
    except: pass

def _cleanup():
    try:
        if os.path.exists(LOCK_FILE): os.remove(LOCK_FILE)
    except: pass

atexit.register(_cleanup)
ensure_single_instance()

SCRIPTS = [
    ("app.py",              "API Flask"),
    ("monitor.py",          "Monitor archivos"),
    ("remote_listener.py",  "Listener remoto"),
    ("widget.pyw",          "Widget UI"),
]

log("=== Watchdog robusto iniciado ===")

while True:
    now = time.time()
    
    for script, name in SCRIPTS:
        # 1. Verificar si ya tenemos un PID en caché y si sigue vivo
        pid = _PID_MAP.get(script)
        alive = is_alive(pid)
        
        # 2. Si no está en caché o está muerto, buscar en el sistema (WMI)
        if not alive:
            found_pids = find_pids_by_script_name(script)
            # Filtrar el propio proceso del watchdog si coincide
            found_pids = [p for p in found_pids if p != os.getpid()]
            
            if found_pids:
                pid = found_pids[0]
                _PID_MAP[script] = pid
                alive = True
        
        # 3. Si sigue sin aparecer, reiniciar (respetando cooldown)
        if not alive:
            last_restart = _RESTART_COOLDOWN.get(script, 0)
            if now - last_restart < 30:
                continue # Cooldown de 30s para no saturar si crashea al inicio
            
            log(f"[RESTART] {name} ({script}) no detectado. Iniciando...")
            try:
                script_path = os.path.join(BASE_DIR, script)
                pythonw = sys.executable.replace("python.exe", "pythonw.exe")
                if not os.path.exists(pythonw): pythonw = sys.executable
                
                # Usar rutas absolutas para mayor claridad en el futuro
                proc = subprocess.Popen(
                    [pythonw, script_path],
                    cwd=BASE_DIR,
                    creationflags=0x08000000,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                _PID_MAP[script] = proc.pid
                _RESTART_COOLDOWN[script] = now
                log(f"[OK] {name} iniciado (PID {proc.pid}).")
            except Exception as e:
                log(f"[ERROR] No se pudo iniciar {name}: {e}")
                _RESTART_COOLDOWN[script] = now # Marcar cooldown incluso si falla

    time.sleep(15)

