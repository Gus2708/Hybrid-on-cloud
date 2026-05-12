import sys
import os
import time
import json
import subprocess
import threading
from datetime import datetime
from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler
from network_util import check_drive

# 🛡️ SILENCIO ABSOLUTO en modo pythonw
if sys.executable.lower().endswith("pythonw.exe"):
    try:
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")
    except: pass

# Intentar cargar rutas desde config
try:
    from config import RUTA_INVENTARIO, RUTA_PRECIOS, RUTA_EXISTENCIA, RUTA_VENTAS_CABECERA, RUTA_VENTAS_DETALLE, RUTA_CLIENTES
except ImportError:
    RUTA_INVENTARIO = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TInventario.dat'
    RUTA_PRECIOS    = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TCostoPrecioInv.Dat'
    RUTA_EXISTENCIA = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TExistenciaInv.Dat'
    RUTA_VENTAS_CABECERA = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TTransaccionvta.dat'
    RUTA_VENTAS_DETALLE  = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TDetalleVta.dat'
    RUTA_CLIENTES        = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TClientes.dat'

# Archivos críticos a vigilar
CRITICAL_FILES = {
    os.path.basename(RUTA_INVENTARIO).lower(): "inventario",
    os.path.basename(RUTA_PRECIOS).lower(): "inventario",
    os.path.basename(RUTA_EXISTENCIA).lower(): "inventario",
    os.path.basename(RUTA_VENTAS_CABECERA).lower(): "ventas",
    os.path.basename(RUTA_VENTAS_DETALLE).lower(): "ventas",
    os.path.basename(RUTA_CLIENTES).lower(): "ventas"
}

WATCH_DIR = os.path.dirname(RUTA_INVENTARIO)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class SyncTriggerHandler(FileSystemEventHandler):
    def __init__(self):
        self.last_sync_time = {"inventario": 0, "ventas": 0}
        self.debounce_seconds = 5
        self.min_interval = 120
        self.timer = None

    def on_modified(self, event):
        if event.is_directory: return
        filename = os.path.basename(event.src_path).lower()
        if filename in CRITICAL_FILES:
            self.schedule_sync(filename)

    def schedule_sync(self, filename):
        now = time.time()
        sync_type = CRITICAL_FILES.get(filename, "inventario")

        min_remaining = self.min_interval - (now - self.last_sync_time.get(sync_type, 0))
        if min_remaining > 0:
            return

        if self.timer: self.timer.cancel()
        self.timer = threading.Timer(self.debounce_seconds, self.run_sync, [filename, sync_type])
        self.timer.start()

    def run_sync(self, reason, sync_type):
        log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] Cambio en: {reason}. Sync {sync_type}..."
        log_monitor(log_msg)
        
        def sync_worker():
            try:
                from lock_util import acquire_lock
                if not check_drive(WATCH_DIR):
                    log_monitor(f"ERROR: Unidad H: no accesible para sync {sync_type}")
                    return

                with acquire_lock(timeout=60):
                    if sync_type == "ventas":
                        import sync_ventas
                        import importlib
                        importlib.reload(sync_ventas)
                        sync_ventas.sync_incremental()
                    else:
                        import sync
                        import importlib
                        importlib.reload(sync)
                        sync.sync_incremental()
                
                self.last_sync_time[sync_type] = time.time()
                log_monitor(f"OK: Sincronización {sync_type} finalizada.")
            except Exception as e:
                log_monitor(f"ERROR en sync ({sync_type}): {e}")

        threading.Thread(target=sync_worker, daemon=True).start()

_MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB

def _rotate_log(log_path: str):
    try:
        if os.path.exists(log_path) and os.path.getsize(log_path) > _MAX_LOG_BYTES:
            bak = log_path + ".1"
            if os.path.exists(bak): os.remove(bak)
            os.rename(log_path, bak)
    except: pass

def log_monitor(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_message = message.encode('ascii', 'replace').decode('ascii')
    print(f"[MONITOR] {safe_message}")
    try:
        log_path = os.path.join(BASE_DIR, "monitor.log")
        _rotate_log(log_path)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except: pass

def start_monitor():
    log_monitor(f"Iniciando monitoreo en: {WATCH_DIR}")
    _drive_was_offline = False
    last_heartbeat = 0
    
    while True:
        now = time.time()
        
        # ─── Heartbeat GLOBAL (para que la UI sepa que el monitor está VIVO) ──
        if now - last_heartbeat > 30:
            try:
                with open(os.path.join(BASE_DIR, "last_monitor.json"), "w") as f:
                    json.dump({
                        "last_check": datetime.now().strftime("%d/%m %H:%M:%S"), 
                        "timestamp": now,
                        "drive_online": check_drive(WATCH_DIR)
                    }, f)
                last_heartbeat = now
            except: pass

        try:
            # Validar directorio inicial (sin bloquear indefinidamente)
            if not check_drive(WATCH_DIR):
                if not _drive_was_offline:
                    log_monitor(f"⚠️ Unidad H: NO DISPONIBLE. Esperando reconexión...")
                    _drive_was_offline = True
                time.sleep(10)
                continue
            
            if _drive_was_offline:
                log_monitor("✅ Unidad H: RECONECTADA.")
                _drive_was_offline = False

            event_handler = SyncTriggerHandler()
            observer = Observer()
            observer.schedule(event_handler, WATCH_DIR, recursive=False)
            observer.start()
            log_monitor("Observador de archivos activo (Polling).")
            
            last_drive_check = 0
            
            while True:
                now = time.time()
                
                # Heartbeat interno
                if now - last_heartbeat > 30:
                    try:
                        with open(os.path.join(BASE_DIR, "last_monitor.json"), "w") as f:
                            json.dump({"last_check": datetime.now().strftime("%d/%m %H:%M:%S"), "timestamp": now, "drive_online": True}, f)
                        last_heartbeat = now
                    except: pass

                # Check de unidad cada 30s
                if now - last_drive_check > 30:
                    last_drive_check = now
                    try:
                        if not check_drive(WATCH_DIR):
                            log_monitor(f"⚠️ Unidad H: se ha desconectado.")
                            break 
                    except:
                        break
                
                if not observer.is_alive(): break
                time.sleep(1)
                
        except Exception as e:
            log_monitor(f"Error en monitor: {repr(e)}")
            time.sleep(5)
        finally:
            try:
                observer.stop()
                observer.join(timeout=2)
            except: pass

if __name__ == "__main__":
    try:
        start_monitor()
    except Exception as e:
        try:
            with open(os.path.join(BASE_DIR, "monitor_fatal.log"), "a") as f:
                f.write(f"[{datetime.now()}] FATAL: {repr(e)}\n")
        except: pass
