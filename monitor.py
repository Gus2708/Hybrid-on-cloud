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
import urllib.request

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
        # Tiempos de debounce específicos por tipo
        self.debounce_seconds = {
            "inventario": 3.0,
            "ventas": 1.5
        }
        # Tiempos de cooldown mínimos específicos por tipo (en segundos)
        self.min_interval = {
            "inventario": 15.0,
            "ventas": 5.0
        }
        self.last_sync_time = {"inventario": 0.0, "ventas": 0.0}
        self.timers = {"inventario": None, "ventas": None}
        self.pending_syncs = {"inventario": False, "ventas": False}
        self.lock = threading.Lock()

    def on_modified(self, event):
        if event.is_directory: return
        filename = os.path.basename(event.src_path).lower()
        if filename in CRITICAL_FILES:
            self.schedule_sync(filename)

    def schedule_sync(self, filename):
        sync_type = CRITICAL_FILES.get(filename, "inventario")
        with self.lock:
            # 1. Si ya hay un timer de debounce corriendo para este tipo, cancelarlo para reiniciarlo (debouncing clásico)
            if self.timers[sync_type] is not None:
                self.timers[sync_type].cancel()
                self.timers[sync_type] = None

            # 2. Calcular el tiempo transcurrido desde el último sync exitoso
            now = time.time()
            time_since_last = now - self.last_sync_time.get(sync_type, 0.0)
            cooldown = self.min_interval.get(sync_type, 15.0)
            base_debounce = self.debounce_seconds.get(sync_type, 3.0)

            # 3. Determinar el delay final del timer
            if time_since_last < cooldown:
                # Si estamos en cooldown, posponemos el sync al momento en que expire el cooldown
                remaining_cooldown = cooldown - time_since_last
                delay = max(base_debounce, remaining_cooldown)
                self.pending_syncs[sync_type] = True
            else:
                delay = base_debounce
                self.pending_syncs[sync_type] = False

            # 4. Programar la ejecución en el timer
            self.timers[sync_type] = threading.Timer(delay, self.trigger_sync, [filename, sync_type])
            self.timers[sync_type].start()

    def trigger_sync(self, reason, sync_type):
        with self.lock:
            self.timers[sync_type] = None
            self.pending_syncs[sync_type] = False
        
        # Ejecutar la sincronización real
        self.run_sync(reason, sync_type)

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

def auto_heal_startup(sync_handler: SyncTriggerHandler):
    """
    Verifica si hay discrepancias al iniciar y ejecuta la sincronización
    rápida por hashes automáticamente (Self-Healing).
    """
    log_monitor("Iniciando rutina de Auto-Healing...")
    # Esperar hasta que app.py esté disponible (máx 30 segs)
    for _ in range(6):
        try:
            req = urllib.request.Request("http://localhost:5000/api/v1/sync/status")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                
                # Chequeamos si el status general es "ok"
                if data.get("status") == "ok":
                    log_monitor("✅ Auto-Healing: Integridad de datos correcta.")
                    return
                
                log_monitor("⚠️ Auto-Healing: Discrepancias detectadas. Evaluando módulos...")
                
                entities = data.get("entities", {})
                
                # Check Inventario/Productos
                prod_ok = entities.get("productos", {}).get("ok", True)
                if not prod_ok:
                    log_monitor("  -> Discrepancia en Inventario. Solicitando sync automático...")
                    sync_handler.run_sync("Auto-Healing Startup", "inventario")
                
                # Check Ventas/Detalles/Clientes
                ventas_ok = entities.get("ventas", {}).get("ok", True)
                detalle_ok = entities.get("detalle", {}).get("ok", True)
                clientes_ok = entities.get("clientes", {}).get("ok", True)
                
                if not (ventas_ok and detalle_ok and clientes_ok):
                    log_monitor("  -> Discrepancia en Ventas/Clientes. Solicitando sync automático...")
                    sync_handler.run_sync("Auto-Healing Startup", "ventas")
                
                return # Salimos del bucle si logramos verificar
        except Exception:
            time.sleep(5) # Esperar a que app.py inicie
    
    log_monitor("⚠️ Auto-Healing: No se pudo contactar a la API de estado para verificar.")

def start_monitor():
    log_monitor(f"Iniciando monitoreo en: {WATCH_DIR}")
    _drive_was_offline = False
    _needs_auto_heal = True
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
                    _needs_auto_heal = True
                time.sleep(10)
                continue
            
            if _drive_was_offline:
                log_monitor("✅ Unidad H: RECONECTADA.")
                _drive_was_offline = False

            event_handler = SyncTriggerHandler()
            
            if _needs_auto_heal:
                threading.Thread(target=auto_heal_startup, args=(event_handler,), daemon=True).start()
                _needs_auto_heal = False

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
