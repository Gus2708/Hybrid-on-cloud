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
    from config import RUTA_INVENTARIO, RUTA_PRECIOS, RUTA_EXISTENCIA, RUTA_VENTAS_CABECERA, RUTA_VENTAS_DETALLE, RUTA_CLIENTES, RUTA_PROVEEDORES
except ImportError:
    RUTA_INVENTARIO = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TInventario.dat'
    RUTA_PRECIOS    = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TCostoPrecioInv.Dat'
    RUTA_EXISTENCIA = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TExistenciaInv.Dat'
    RUTA_VENTAS_CABECERA = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TTransaccionvta.dat'
    RUTA_VENTAS_DETALLE  = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TDetalleVta.dat'
    RUTA_CLIENTES        = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TClientes.dat'
    RUTA_PROVEEDORES     = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TProveedores.Dat'

# Archivos críticos a vigilar
CRITICAL_FILES = {
    os.path.basename(RUTA_INVENTARIO).lower(): "inventario",
    os.path.basename(RUTA_PRECIOS).lower(): "inventario",
    os.path.basename(RUTA_EXISTENCIA).lower(): "inventario",
    os.path.basename(RUTA_VENTAS_CABECERA).lower(): "ventas",
    os.path.basename(RUTA_VENTAS_DETALLE).lower(): "ventas",
    os.path.basename(RUTA_CLIENTES).lower(): "ventas",
    os.path.basename(RUTA_PROVEEDORES).lower(): "proveedores"
}

WATCH_DIR = os.path.dirname(RUTA_INVENTARIO)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class SyncTriggerHandler(FileSystemEventHandler):
    def __init__(self):
        # Tiempos de debounce específicos por tipo
        self.debounce_seconds = {
            "inventario": 3.0,
            "ventas": 1.5,
            "proveedores": 2.0
        }
        # Tiempos de cooldown mínimos específicos por tipo (en segundos)
        self.min_interval = {
            "inventario": 15.0,
            "ventas": 5.0,
            "proveedores": 15.0
        }
        self.last_sync_time = {"inventario": 0.0, "ventas": 0.0, "proveedores": 0.0}
        self.timers = {"inventario": None, "ventas": None, "proveedores": None}
        self.pending_syncs = {"inventario": False, "ventas": False, "proveedores": False}
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
                        ok = sync_ventas.sync_incremental() is not False
                    elif sync_type == "proveedores":
                        import sync_proveedores
                        import importlib
                        importlib.reload(sync_proveedores)
                        ok = sync_proveedores.main() == 0
                    else:
                        import sync
                        import importlib
                        importlib.reload(sync)
                        ok = sync.sync_incremental() is not False

                if ok:
                    self.last_sync_time[sync_type] = time.time()
                    log_monitor(f"OK: Sincronización {sync_type} finalizada.")
                else:
                    # No actualizar last_sync_time: el self-heal periódico reintentará
                    log_monitor(f"WARN: Sincronización {sync_type} incompleta (¿sin conexión?). Se reintentará automáticamente.")
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

RATE_REFRESH_INTERVAL = 15 * 60  # 15 minutos

def rate_refresh_worker():
    """Thread daemon que actualiza tasas BCV y Binance en Supabase cada 15 minutos."""
    log_monitor("Rate refresh thread iniciado (intervalo: 15 min).")
    while True:
        try:
            from rates_service import RatesService
            service = RatesService()
            rates = service.get_all_rates()
            if service.save_to_db(rates):
                log_monitor(f"Tasas actualizadas: BCV={rates.get('bcv_usd', 0):.2f}, Binance={rates.get('binance_p2p', 0):.2f}")
            else:
                log_monitor("Error al guardar tasas en Supabase.")
        except Exception as e:
            log_monitor(f"Error en rate refresh: {e}")
        time.sleep(RATE_REFRESH_INTERVAL)


def start_rate_refresh_thread():
    """Inicia el thread de actualización de tasas como daemon."""
    t = threading.Thread(target=rate_refresh_worker, daemon=True, name="rate-refresh")
    t.start()
    return t


_HEAL_INTERVAL = 30 * 60  # re-verificación periódica de integridad (30 min)
_heal_was_ok = True       # para alertar solo en la transición OK → discrepancia


def auto_heal_check(sync_handler: SyncTriggerHandler) -> bool:
    """
    Una pasada de Self-Healing: consulta /sync/status y dispara los syncs
    necesarios. Devuelve True si logró verificar, False si la API no respondió.
    """
    global _heal_was_ok
    for _ in range(3):
        try:
            req = urllib.request.Request("http://localhost:5000/api/v1/sync/status")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            time.sleep(5)  # Esperar a que app.py inicie/responda
            continue

        if data.get("is_syncing"):
            log_monitor("Self-Healing: hay un sync en curso; se verificará en el próximo ciclo.")
            return True

        if data.get("status") == "ok":
            if not _heal_was_ok:
                log_monitor("✅ Self-Healing: Integridad de datos recuperada.")
            _heal_was_ok = True
            return True

        log_monitor("⚠️ Self-Healing: Discrepancias detectadas. Evaluando módulos...")
        first_failure = _heal_was_ok
        _heal_was_ok = False
        entities = data.get("entities", {})

        # Check Inventario/Productos
        if not entities.get("productos", {}).get("ok", True):
            log_monitor("  -> Discrepancia en Inventario. Solicitando sync automático...")
            sync_handler.run_sync("Self-Healing", "inventario")
            if first_failure:
                try:
                    from alert_util import send_alert
                    send_alert("warning", "Self-Healing: Discrepancia en Inventario detectada. Sync automático iniciado.")
                except Exception:
                    pass

        # Check Ventas/Detalles/Clientes
        ventas_ok = entities.get("ventas", {}).get("ok", True)
        detalle_ok = entities.get("detalle", {}).get("ok", True)
        clientes_ok = entities.get("clientes", {}).get("ok", True)

        if not (ventas_ok and detalle_ok and clientes_ok):
            log_monitor("  -> Discrepancia en Ventas/Clientes. Solicitando sync automático...")
            sync_handler.run_sync("Self-Healing", "ventas")
            if first_failure:
                try:
                    from alert_util import send_alert
                    send_alert("warning", "Self-Healing: Discrepancia en Ventas/Clientes detectada. Sync automático iniciado.")
                except Exception:
                    pass

        return True
    return False


def self_heal_worker(sync_handler: SyncTriggerHandler, heal_event: threading.Event):
    """
    Thread daemon: verifica integridad al arrancar y luego cada 30 minutos
    (o inmediatamente cuando heal_event se activa, p.ej. al reconectar H:).
    Esto garantiza que un sync fallido por corte de internet/red se reintente
    solo, sin esperar un nuevo cambio en los .DAT ni reiniciar la PC.
    """
    time.sleep(30)  # dar tiempo a que app.py levante
    log_monitor(f"Self-Healing periódico iniciado (cada {_HEAL_INTERVAL // 60} min).")
    while True:
        try:
            if check_drive(WATCH_DIR):
                if not auto_heal_check(sync_handler):
                    log_monitor("⚠️ Self-Healing: No se pudo contactar a la API de estado para verificar.")
            else:
                log_monitor("Self-Healing: Unidad H: no disponible; se reintentará en el próximo ciclo.")
        except Exception as e:
            log_monitor(f"Error en self-heal: {repr(e)}")
        heal_event.wait(timeout=_HEAL_INTERVAL)
        heal_event.clear()

def start_monitor():
    log_monitor(f"Iniciando monitoreo en: {WATCH_DIR}")
    _drive_was_offline = False
    last_heartbeat = 0

    # Handler persistente: sobrevive a reconexiones de H: y conserva cooldowns/timers
    event_handler = SyncTriggerHandler()
    heal_event = threading.Event()
    threading.Thread(target=self_heal_worker, args=(event_handler, heal_event),
                     daemon=True, name="self-heal").start()
    start_rate_refresh_thread()

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
                log_monitor("✅ Unidad H: RECONECTADA. Verificando integridad...")
                _drive_was_offline = False
                heal_event.set()  # disparar self-heal inmediato tras la reconexión

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
