import os
import time
import sys
import glob
from contextlib import contextmanager

LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sync.lock")

# ─── Limpieza al arrancar (post-apagón) ─────────────────────────────────────
def clear_stale_locks():
    """Elimina locks huérfanos y archivos .tmp colgados de sincronizaciones abortadas."""
    base = os.path.dirname(os.path.abspath(__file__))
    for f in ["sync.lock"]:
        p = os.path.join(base, f)
        if os.path.exists(p):
            try:
                with open(p) as fh:
                    pid_str = fh.read().strip()
                if pid_str and pid_str.isdigit():
                    old_pid = int(pid_str)
                    if not pid_exists(old_pid):
                        os.remove(p)
                        print(f"[LOCK] Lock huérfano (PID {old_pid}) limpiado en inicio.")
                else:
                    os.remove(p)
            except Exception:
                # Si el lock no se puede leer/borrar (p.ej. bloqueado por otro
                # proceso), no reventar el import: acquire_lock lo reintentará.
                try: os.remove(p)
                except Exception: pass
    for tmp in glob.glob(os.path.join(base, "*.tmp")):
        try:
            if time.time() - os.path.getmtime(tmp) > 60:
                os.remove(tmp)
        except: pass

clear_stale_locks()

def pid_exists(pid):
    """Verifica si un proceso sigue vivo en Windows/Linux de forma silenciosa."""
    if not pid or pid <= 0: return False
    
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # PROCESS_QUERY_LIMITED_INFORMATION (0x1000)
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                exit_code = ctypes.c_ulong()
                res = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                kernel32.CloseHandle(handle)
                # 259 es STILL_ACTIVE
                return bool(res and exit_code.value == 259)
            else:
                err = kernel32.GetLastError()
                # 5 es ERROR_ACCESS_DENIED. Si da acceso denegado, el proceso está vivo
                if err == 5:
                    return True
                return False
        except:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
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
                if os.path.exists(LOCK_FILE):
                    with open(LOCK_FILE, "r") as f:
                        content = f.read().strip()
                        if content:
                            old_pid = int(content)
                            if not pid_exists(old_pid):
                                print(f"[LOCK] Detectado lock huérfano (PID {old_pid}). Limpiando...")
                                try: os.remove(LOCK_FILE)
                                except: pass
                                continue
            except: pass
            
            time.sleep(2) # Aumentado de 1 a 2 para reducir spam
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

def safe_replace(src, dst, max_retries=5, delay=0.1):
    """Reemplaza un archivo con reintentos para evitar bloqueos concurrentes en Windows (WinError 32)."""
    for attempt in range(1, max_retries + 1):
        try:
            if os.path.exists(dst):
                os.replace(src, dst)
            else:
                os.rename(src, dst)
            return True
        except (PermissionError, FileExistsError):
            if attempt < max_retries:
                time.sleep(delay)
            else:
                raise
        except Exception:
            if attempt < max_retries:
                time.sleep(delay)
            else:
                raise
    return False

