import sys
import os
import time
import json

# 🛡️ SILENCIO ABSOLUTO
# Si el script corre bajo pythonw.exe, redirigimos las salidas a NUL para 
# evitar que Windows intente asignar una consola para el output.
if sys.executable.lower().endswith("pythonw.exe"):
    try:
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")
    except: pass

import subprocess
import threading
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

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
SYNC_SCRIPT = os.path.join(BASE_DIR, "sync.py")
SYNC_VENTAS_SCRIPT = os.path.join(BASE_DIR, "sync_ventas.py")

class SyncTriggerHandler(FileSystemEventHandler):
    def __init__(self):
        self.last_trigger = 0
        self.last_sync_time = {"inventario": 0, "ventas": 0}
        self.debounce_seconds = 5
        self.min_interval = 120
        self.timer = None

    def on_modified(self, event):
        if event.is_directory:
            return
        
        filename = os.path.basename(event.src_path).lower()
        if filename in CRITICAL_FILES:
            self.schedule_sync(filename)

    def schedule_sync(self, filename):
        now = time.time()
        sync_type = CRITICAL_FILES.get(filename, "inventario")

        min_remaining = self.min_interval - (now - self.last_sync_time.get(sync_type, 0))
        if min_remaining > 0:
            print(f"[MONITOR] Ignorando cambio en {filename}: cooldown de {sync_type} ({min_remaining:.0f}s restantes)")
            return

        if self.timer:
            self.timer.cancel()
        
        self.timer = threading.Timer(self.debounce_seconds, self.run_sync, [filename, sync_type])
        self.timer.start()

    def run_sync(self, reason, sync_type):
        log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] Cambio detectado en: {reason}. Sincronizando {sync_type} (Directo)..."
        print(log_msg)
        
        try:
            with open(os.path.join(BASE_DIR, "monitor.log"), "a") as f:
                f.write(log_msg + "\n")
        except: pass
        
        def sync_worker():
            try:
                # Validar que la unidad H: responde antes de sincronizar
                if not os.path.exists(WATCH_DIR):
                    err = f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: Unidad H: no accesible. Cancelando sync {sync_type}.\n"
                    print(f"[MONITOR] {err}")
                    with open(os.path.join(BASE_DIR, "monitor.log"), "a") as f:
                        f.write(err)
                    return

                from lock_util import acquire_lock
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
                msg = f"[{datetime.now().strftime('%H:%M:%S')}] OK: Sincronización {sync_type} finalizada.\n"
                print(f"[MONITOR] {msg}")
                with open(os.path.join(BASE_DIR, "monitor.log"), "a") as f:
                    f.write(msg)
            except Exception as e:
                err = f"[{datetime.now().strftime('%H:%M:%S')}] ERROR en sync directo ({sync_type}): {e}\n"
                print(f"[MONITOR] {err}")
                with open(os.path.join(BASE_DIR, "monitor.log"), "a") as f:
                    f.write(err)

        threading.Thread(target=sync_worker, daemon=True).start()


_MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB

def _rotate_log(log_path: str):
    """Si el log supera _MAX_LOG_BYTES, lo rota guardando el anterior como .1"""
    try:
        if os.path.exists(log_path) and os.path.getsize(log_path) > _MAX_LOG_BYTES:
            bak = log_path + ".1"
            if os.path.exists(bak):
                os.remove(bak)
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
    if not os.path.exists(WATCH_DIR):
        log_monitor(f"Error: El directorio {WATCH_DIR} no existe.")
        return

    log_monitor(f"Vigilando cambios en: {WATCH_DIR}")
    
    _drive_was_offline = False
    
    while True:
        try:
            event_handler = SyncTriggerHandler()
            observer = Observer()
            observer.schedule(event_handler, WATCH_DIR, recursive=False)
            observer.start()
            
            log_monitor("Observador iniciado correctamente.")
            
            last_heartbeat = 0
            last_drive_check = 0
            drive_check_interval = 30
            
            while True:
                now = time.time()
                
                # ─── Health check de la unidad H: cada 30s ────────────────
                if now - last_drive_check > drive_check_interval:
                    last_drive_check = now
                    try:
                        drive_ok = os.path.exists(WATCH_DIR)
                    except:
                        drive_ok = False
                    
                    if not drive_ok:
                        if not _drive_was_offline:
                            log_monitor(f"⚠️ Unidad H: NO RESPONDE ({WATCH_DIR})")
                            _drive_was_offline = True
                    else:
                        if _drive_was_offline:
                            log_monitor(f"✅ Unidad H: RECONECTADA.")
                            _drive_was_offline = False
                
                if now - last_heartbeat > 30:
                    try:
                        with open(os.path.join(BASE_DIR, "last_monitor.json"), "w") as f:
                            json.dump({"last_check": datetime.now().strftime("%d/%m %H:%M:%S"), "timestamp": now}, f)
                        last_heartbeat = now
                    except: pass
                
                # Verificar si el observador sigue vivo
                if not observer.is_alive():
                    log_monitor("ADVERTENCIA: El observador de archivos murio. Reiniciando...")
                    break
                
                time.sleep(1)
                
        except Exception as e:
            log_monitor(f"Error en el bucle del monitor: {repr(e)}")
            time.sleep(5) # Esperar antes de reintentar todo
        finally:
            try:
                observer.stop()
                observer.join()
            except: pass

if __name__ == "__main__":
    try:
        start_monitor()
    except Exception as e:
        # Esto solo si falla el bucle infinito externo
        with open(os.path.join(BASE_DIR, "monitor_fatal.log"), "a") as f:
            f.write(f"[{datetime.now()}] FATAL: {repr(e)}\n")

