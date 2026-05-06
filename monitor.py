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
        self.debounce_seconds = 2
        self.timer = None

    def on_modified(self, event):
        if event.is_directory:
            return
        
        filename = os.path.basename(event.src_path).lower()
        if filename in CRITICAL_FILES:
            self.schedule_sync(filename)

    def schedule_sync(self, filename):
        if self.timer:
            self.timer.cancel()
        
        sync_type = CRITICAL_FILES.get(filename, "inventario")
        self.timer = threading.Timer(self.debounce_seconds, self.run_sync, [filename, sync_type])
        self.timer.start()

    def run_sync(self, reason, sync_type):
        log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] Cambio detectado en: {reason}. Sincronizando {sync_type}..."
        print(log_msg)
        with open(os.path.join(BASE_DIR, "monitor.log"), "a") as f:
            f.write(log_msg + "\n")
        
        try:
            script_to_run = SYNC_VENTAS_SCRIPT if sync_type == "ventas" else SYNC_SCRIPT
            result = subprocess.run([sys.executable, script_to_run, "once"], capture_output=True, text=True)
            if result.returncode == 0:
                print(f"[MONITOR] -> Sincronización de {sync_type} exitosa.")
                with open(os.path.join(BASE_DIR, "monitor.log"), "a") as f:
                    f.write(f"[{datetime.now().strftime('%H:%M:%S')}] OK: Sincronización de {sync_type} exitosa.\n")
            else:
                print(f"[MONITOR] ! Error en sincronización de {sync_type}: {result.stderr}")
                with open(os.path.join(BASE_DIR, "monitor.log"), "a") as f:
                    f.write(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: {result.stderr[:200]}\n")
        except Exception as e:
            print(f"[MONITOR] ! Fallo al ejecutar {script_to_run}: {e}")


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
