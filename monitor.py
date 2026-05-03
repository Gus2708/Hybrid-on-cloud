import os
import sys
import time
import subprocess
import threading
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Intentar cargar rutas desde config
try:
    from config import RUTA_INVENTARIO, RUTA_PRECIOS, RUTA_EXISTENCIA
except ImportError:
    RUTA_INVENTARIO = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TInventario.dat'
    RUTA_PRECIOS    = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TCostoPrecioInv.Dat'
    RUTA_EXISTENCIA = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TExistenciaInv.Dat'

# Archivos críticos a vigilar
CRITICAL_FILES = {
    os.path.basename(RUTA_INVENTARIO).lower(),
    os.path.basename(RUTA_PRECIOS).lower(),
    os.path.basename(RUTA_EXISTENCIA).lower()
}

WATCH_DIR = os.path.dirname(RUTA_INVENTARIO)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SYNC_SCRIPT = os.path.join(BASE_DIR, "sync.py")

class SyncTriggerHandler(FileSystemEventHandler):
    def __init__(self):
        self.last_trigger = 0
        self.debounce_seconds = 2
        self.timer = None

    def on_modified(self, event):
        if event.is_directory:
            return
        
        filename = os.path.basename(event.src_path).lower()
        if filename in CRITICAL_FILES:
            self.schedule_sync(filename)

    def schedule_sync(self, reason):
        if self.timer:
            self.timer.cancel()
        
        self.timer = threading.Timer(self.debounce_seconds, self.run_sync, [reason])
        self.timer.start()

    def run_sync(self, reason):
        log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] Cambio detectado en: {reason}. Sincronizando..."
        print(log_msg)
        with open(os.path.join(BASE_DIR, "monitor.log"), "a") as f:
            f.write(log_msg + "\n")
        
        try:
            # Ejecutar sync.py como subproceso para independencia
            result = subprocess.run([sys.executable, SYNC_SCRIPT, "once"], capture_output=True, text=True)
            if result.returncode == 0:
                print("[MONITOR] -> Sincronización exitosa.")
                with open(os.path.join(BASE_DIR, "monitor.log"), "a") as f:
                    f.write(f"[{datetime.now().strftime('%H:%M:%S')}] OK: Sincronización exitosa.\n")
            else:
                print(f"[MONITOR] ! Error en sincronización: {result.stderr}")
                with open(os.path.join(BASE_DIR, "monitor.log"), "a") as f:
                    f.write(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: {result.stderr[:200]}\n")
        except Exception as e:
            print(f"[MONITOR] ! Fallo al ejecutar sync.py: {e}")


def start_monitor():
    if not os.path.exists(WATCH_DIR):
        print(f"[MONITOR] Error: El directorio {WATCH_DIR} no existe.")
        return

    print(f"[MONITOR] Vigilando cambios en: {WATCH_DIR}")
    print(f"[MONITOR] Archivos críticos: {', '.join(CRITICAL_FILES)}")
    
    event_handler = SyncTriggerHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCH_DIR, recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    start_monitor()
