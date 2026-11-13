import os
import time
import sys
import glob
from contextlib import contextmanager

LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sync.lock")

def pid_exists(pid):
    """Check if a process is still alive on Windows/Linux silently."""
    if not pid or pid <= 0:
        return False
    
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
                # 259 is STILL_ACTIVE
                return bool(res and exit_code.value == 259)
            else:
                err = kernel32.GetLastError()
                # 5 is ERROR_ACCESS_DENIED. If access is denied, process is alive
                if err == 5:
                    return True
                return False
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

# ─── Startup cleanup (post-crash recovery) ───────────────────────────────────
def clear_stale_locks():
    """Remove orphan locks and stale .tmp files from aborted sync runs."""
    base = os.path.dirname(LOCK_FILE)
    lock_candidates = {LOCK_FILE, os.path.join(base, "sync.lock")}
    for p in lock_candidates:
        if os.path.exists(p):
            try:
                with open(p) as fh:
                    pid_str = fh.read().strip()
                if pid_str and pid_str.isdigit():
                    old_pid = int(pid_str)
                    if not pid_exists(old_pid):
                        try:
                            os.remove(p)
                            print(f"[LOCK] Orphan lock (PID {old_pid}) cleaned at startup.")
                        except OSError:
                            pass
                    else:
                        # Process is alive, do NOT remove p!
                        pass
                else:
                    # Empty or non-digit lock file is invalid, remove safely
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            except Exception:
                # If reading or opening the lock fails, do not blindly delete it, just pass.
                pass
    for tmp in glob.glob(os.path.join(base, "*.tmp")):
        try:
            if time.time() - os.path.getmtime(tmp) > 60:
                os.remove(tmp)
        except Exception:
            pass

clear_stale_locks()


@contextmanager
def acquire_lock(timeout=120):
    start_time = time.time()
    acquired = False
    
    while time.time() - start_time < timeout:
        try:
            # Attempt to create the lock
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, 'w') as f:
                f.write(str(os.getpid()))
            acquired = True
            break
        except FileExistsError:
            # Verify if lock is orphaned (process died)
            try:
                if os.path.exists(LOCK_FILE):
                    with open(LOCK_FILE, "r") as f:
                        content = f.read().strip()
                        if content:
                            old_pid = int(content)
                            if not pid_exists(old_pid):
                                print(f"[LOCK] Orphan lock detected (PID {old_pid}). Cleaning...")
                                try: os.remove(LOCK_FILE)
                                except: pass
                                continue
            except Exception:
                pass
            
            time.sleep(2) # Increased from 1s to 2s to reduce spin spam
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
    except Exception:
        return False

def safe_replace(src, dst, max_retries=5, delay=0.1):
    """Replace a file with retries to avoid concurrent locks on Windows (WinError 32)."""
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

