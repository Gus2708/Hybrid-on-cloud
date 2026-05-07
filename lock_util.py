import os
import time
import sys
from contextlib import contextmanager

LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sync.lock")

def pid_exists(pid):
    """Verifica si un proceso sigue vivo en Windows/Linux."""
    if pid <= 0: return False
    try:
        import subprocess
        if sys.platform == "win32":
            # Tasklist es nativo en Windows
            output = subprocess.check_output(["tasklist", "/FI", f"PID eq {pid}"], text=True)
            return str(pid) in output
        else:
            os.kill(pid, 0)
            return True
    except:
        return False

@contextmanager
def acquire_lock(timeout=120):
    start_time = time.time()
    acquired = False
    
    while time.time() - start_time < timeout:
        try:
            # Intentar crear el lock
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, 'w') as f:
                f.write(str(os.getpid()))
            acquired = True
            break
        except FileExistsError:
            # Verificar si el lock es "huérfano" (el proceso murió)
            try:
                with open(LOCK_FILE, "r") as f:
                    old_pid = int(f.read().strip())
                if not pid_exists(old_pid):
                    print(f"[LOCK] Detectado lock huérfano (PID {old_pid}). Limpiando...")
                    try: os.remove(LOCK_FILE)
                    except: pass
                    continue # Reintentar crear inmediatamente
            except: pass
            
            time.sleep(1)
            continue
            
    if not acquired:
        raise TimeoutError(f"No se pudo adquirir el bloqueo de sincronización después de {timeout}s.")
        
    try:
        yield
    finally:
        if acquired:
            try: os.remove(LOCK_FILE)
            except: pass

def is_locked():
    if not os.path.exists(LOCK_FILE): return False
    try:
        with open(LOCK_FILE, "r") as f:
            old_pid = int(f.read().strip())
        return pid_exists(old_pid)
    except:
        return False
