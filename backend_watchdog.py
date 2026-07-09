import os
import sys
import time
import json
import socket
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
_MUTEX_HANDLE = None

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
        else:
            err = ctypes.windll.kernel32.GetLastError()
            # 5 es ERROR_ACCESS_DENIED. Si da acceso denegado, el proceso está vivo
            if err == 5:
                return True
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

    # 3. Último recurso: PowerShell (con $_ sin escapar puesto que está en doble llave)
    try:
        ps_cmd = f"Get-CimInstance Win32_Process | Where-Object {{ $_.Name -like 'python*' -and $_.CommandLine -like '*{script_name}*' }} | Select-Object -ExpandProperty ProcessId"
        cmd = f"powershell -NoProfile -Command \"{ps_cmd}\""
        output = subprocess.check_output(cmd, shell=True, creationflags=0x08000000).decode().strip()
        if output:
            return [int(pid) for pid in output.splitlines() if pid.strip().isdigit()]
    except: pass

    return []


_MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB

def _rotate_log():
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > _MAX_LOG_BYTES:
            bak = LOG_FILE + ".1"
            if os.path.exists(bak): os.remove(bak)
            os.rename(LOG_FILE, bak)
    except: pass

def log(msg):

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[WATCHDOG] {ts} {msg}")
    try:
        _rotate_log()
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except: pass

# ─── Protección de instancia única ────────────────────────────────────────────
def _cleanup():
    try:
        if os.path.exists(LOCK_FILE): os.remove(LOCK_FILE)
    except: pass

def ensure_single_instance():
    """Instancia única vía mutex con nombre de Windows.

    El mutex no puede borrarse como un archivo (un `git checkout` o un
    `atexit` ajeno eliminaban watchdog.lock y permitían 2-3 watchdogs en
    paralelo, cada uno lanzando su propio app.py). El lock file se mantiene
    solo como informativo del PID, y su cleanup se registra ÚNICAMENTE si
    esta instancia ganó el mutex: antes, la instancia perdedora borraba al
    salir el lock de la instancia viva.
    """
    global _MUTEX_HANDLE
    try:
        kernel32 = ctypes.windll.kernel32
        _MUTEX_HANDLE = kernel32.CreateMutexW(None, False, "Local\\SerruchoBackendWatchdog")
        if _MUTEX_HANDLE:
            if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                sys.exit(0)
            try:
                with open(LOCK_FILE, "w") as f:
                    f.write(str(os.getpid()))
                atexit.register(_cleanup)
            except: pass
            return
    except SystemExit:
        raise
    except: pass

    # Fallback a lock por archivo si el mutex no pudo crearse
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE, "r") as f:
                content = f.read().strip()
            if content.isdigit() and is_alive(int(content)):
                sys.exit(0)
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        atexit.register(_cleanup)
    except: pass

ensure_single_instance()

# Cada entrada: (script, nombre) o (script, nombre, opts). opts puede traer:
#   "subdir": subcarpeta (relativa a BASE_DIR) donde vive el script; también su cwd.
#   "env":    variables de entorno extra SOLO para ese proceso (no tocan el resto
#             ni el .env).
SCRIPTS = [
    ("app.py",              "API Flask"),
    ("monitor.py",          "Monitor archivos"),
    ("remote_listener.py",  "Listener remoto"),
    ("widget.pyw",          "Widget UI"),
    ("listener_writeback.py", "Write-back stock", {
        "subdir": "hybrid_writeback",
        # HYBRID_WRITE_ENABLED=1 -> aplica los ajustes de verdad en HybridLite.
        # Se pasa SOLO a este proceso (no al .env) para que correr el script a
        # mano siga siendo preview seguro por defecto. Sin HYBRID_WRITE_WINDOW =
        # sin restricción horaria (procesa a cualquier hora).
        "env": {"HYBRID_WRITE_ENABLED": "1"},
    }),
]

# ─── Detección de procesos colgados (vivos pero congelados) ──────────────────
_APP_PORT_FAILS = 0
_HUNG_KILL_TS = {}
_HUNG_KILL_COOLDOWN = 180  # no matar el mismo script por "colgado" más de 1 vez cada 3 min

API_PORT = 5000

def kill_pid(pid):
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=10, creationflags=0x08000000)
    except: pass

def _api_responds():
    """La API debe responder HTTP; un connect TCP no basta (un socket zombi
    acepta conexiones en el backlog sin servir nada)."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{API_PORT}/", timeout=5) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False

def pids_listening_on_port(port):
    """PIDs con socket LISTENING en el puerto local dado (vía netstat)."""
    pids = set()
    try:
        out = subprocess.check_output(["netstat", "-ano", "-p", "TCP"],
                                      creationflags=0x08000000, timeout=15)
        for line in out.decode("ascii", errors="ignore").splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] == "TCP" and parts[1].endswith(f":{port}"):
                state, pid_str = parts[3].upper(), parts[4]
                if ("LISTEN" in state or "ESCUCHA" in state) and pid_str.isdigit() and int(pid_str) > 0:
                    pids.add(int(pid_str))
    except: pass
    return pids

def _is_python_pid(pid):
    wmi_service = get_wmi()
    if wmi_service:
        try:
            for proc in wmi_service.ExecQuery(f"SELECT Name FROM Win32_Process WHERE ProcessId = {pid}"):
                return str(proc.Name).lower().startswith("python")
        except: pass
    return False

def free_api_port():
    """Mata los procesos python zombis que retienen el puerto de la API.

    Antes, al detectar la API colgada se mataba found_pids[0] — que solía ser
    el app.py recién lanzado — y el zombi dueño del puerto sobrevivía,
    provocando reinicios en bucle cada 30s. Aquí se mata al dueño real.
    """
    if _api_responds():
        return  # alguien sirve correctamente en el puerto; no tocar
    for pid in pids_listening_on_port(API_PORT):
        if pid == os.getpid():
            continue
        if _is_python_pid(pid):
            log(f"[PORT] Liberando puerto {API_PORT}: matando PID {pid} que lo retiene sin responder...")
            kill_pid(pid)

def is_hung(script):
    """Detecta si un proceso vivo dejó de responder (colgado en red/SMB, etc.)."""
    global _APP_PORT_FAILS
    if script == "monitor.py":
        # monitor.py escribe heartbeat en last_monitor.json cada ~30s;
        # si lleva >10 min sin latir, está congelado aunque el PID exista
        try:
            p = os.path.join(BASE_DIR, "last_monitor.json")
            if os.path.exists(p):
                with open(p) as f:
                    ts = json.load(f).get("timestamp", 0)
                if ts and time.time() - ts > 600:
                    return True
        except: pass
        return False
    if script == "app.py":
        if _api_responds():
            _APP_PORT_FAILS = 0
            return False
        _APP_PORT_FAILS += 1
        return _APP_PORT_FAILS >= 4  # ~1 minuto sin responder
    return False

log("=== Watchdog robusto iniciado ===")

while True:
    now = time.time()

    for entry in SCRIPTS:
        script, name = entry[0], entry[1]
        opts = entry[2] if len(entry) > 2 else {}
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
                # Nunca debe haber dos instancias del mismo script: los
                # duplicados de app.py se roban el puerto entre sí y la API
                # deja de responder aunque los procesos sigan vivos.
                for extra in found_pids[1:]:
                    log(f"[DUP] Instancia duplicada de {name} ({script}, PID {extra}). Matando...")
                    kill_pid(extra)
                _PID_MAP[script] = pid
                alive = True

        # 2b. Si está vivo pero congelado, matarlo para que se reinicie limpio
        if alive and now - _HUNG_KILL_TS.get(script, 0) > _HUNG_KILL_COOLDOWN and is_hung(script):
            log(f"[HUNG] {name} ({script}) vivo pero sin responder. Matando PID {pid} para reiniciar...")
            kill_pid(pid)
            if script == "app.py":
                for extra in find_pids_by_script_name(script):
                    kill_pid(extra)
                free_api_port()
            _HUNG_KILL_TS[script] = now
            _PID_MAP.pop(script, None)
            alive = False

        # 3. Si sigue sin aparecer, reiniciar (respetando cooldown)
        if not alive:
            if script == "app.py" and _api_responds():
                # Hay una API sana atendiendo el puerto aunque no se detecte
                # por línea de comandos; lanzar otra solo crearía un duplicado
                # que moriría al no poder enlazarse.
                continue

            last_restart = _RESTART_COOLDOWN.get(script, 0)
            if now - last_restart < 30:
                continue # Cooldown de 30s para no saturar si crashea al inicio

            log(f"[RESTART] {name} ({script}) no detectado. Iniciando...")
            try:
                if script == "app.py":
                    free_api_port()  # garantizar que el puerto esté libre antes de enlazar
                subdir = opts.get("subdir")
                work_dir = os.path.join(BASE_DIR, subdir) if subdir else BASE_DIR
                script_path = os.path.join(work_dir, script)
                pythonw = sys.executable.replace("python.exe", "pythonw.exe")
                if not os.path.exists(pythonw): pythonw = sys.executable

                # Entorno extra por-proceso (p. ej. HYBRID_WRITE_ENABLED del listener).
                # env=None hereda el entorno del watchdog, como el resto de scripts.
                proc_env = {**os.environ, **opts["env"]} if opts.get("env") else None

                # Usar rutas absolutas para mayor claridad en el futuro
                proc = subprocess.Popen(
                    [pythonw, script_path],
                    cwd=work_dir,
                    creationflags=0x08000000,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=proc_env
                )
                _PID_MAP[script] = proc.pid
                _RESTART_COOLDOWN[script] = now
                if script == "app.py":
                    _APP_PORT_FAILS = 0  # darle tiempo a Flask de levantar
                log(f"[OK] {name} iniciado (PID {proc.pid}).")
            except Exception as e:
                log(f"[ERROR] No se pudo iniciar {name}: {e}")
                _RESTART_COOLDOWN[script] = now # Marcar cooldown incluso si falla

    time.sleep(15)

