from flask import Flask, jsonify, request
import os
import sys
import json
import time

# 🛡️ SILENCIO ABSOLUTO
if sys.executable.lower().endswith("pythonw.exe"):
    try:
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")
    except: pass

import threading
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# --- Configuración y Estado ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_SOURCE_PATH = os.path.join(BASE_DIR, "MAESTRO_ACTUAL.csv")

_LOCAL_CACHE = []
_LAST_LOAD_TIME = 0

def _load_inventory_if_needed():
    global _LOCAL_CACHE, _LAST_LOAD_TIME
    if not os.path.exists(CSV_SOURCE_PATH):
        _LOCAL_CACHE = []
        return
    
    mtime = os.path.getmtime(CSV_SOURCE_PATH)
    if mtime > _LAST_LOAD_TIME:
        try:
            import csv
            with open(CSV_SOURCE_PATH, mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                _LOCAL_CACHE = list(reader)
                _LAST_LOAD_TIME = mtime
        except Exception as e:
            print(f"Error cargando inventario: {e}")

def _enrich(item):
    try:
        costo = float(item.get("COSTO", 0) or 0)
        precio = float(item.get("PRECIO_VENTA", 0) or 0)
        item["costo"] = costo
        item["precio_venta"] = precio
        item["existencia"] = float(item.get("EXISTENCIA", 0) or 0)
        item["codigo_interno"] = item.get("CODIGO_INTERNO", "")
        item["descripcion"] = item.get("DESCRIPCION", "")
        item["codigo_barras"] = item.get("CODIGO_BARRAS", "")
        item["unidad"] = item.get("UNIDAD", "")
    except: pass
    return item

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "app": "El Serrucho Backend",
        "status": "running",
        "endpoints": [
            "/api/v1/productos",
            "/api/v1/sync/inventory",
            "/api/v1/sync/sales",
            "/api/v1/sync/run",
            "/api/v1/sync/force"
        ]
    })

@app.route("/api/v1/productos", methods=["GET"])
def listar_productos():
    _load_inventory_if_needed()
    q = request.args.get("q", "").strip().upper()
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))

    if not q:
        encontrados = _LOCAL_CACHE
    else:
        encontrados = [
            p for p in _LOCAL_CACHE 
            if q in p.get("CODIGO_INTERNO", "").upper() or q in p.get("DESCRIPCION", "").upper() or q in p.get("CODIGO_BARRAS", "").upper()
        ]

    total = len(encontrados)
    pagina = encontrados[offset : offset + limit]

    return jsonify({
        "total": total,
        "results": [_enrich(p) for p in pagina]
    })

@app.route("/api/v1/sync/inventory", methods=["POST", "GET"])
def sync_inventory():
    try:
        from lock_util import acquire_lock
        with acquire_lock(timeout=10):
            import sync
            import importlib
            importlib.reload(sync)
            sync.sync_incremental()
        return jsonify({"status": "success", "message": "Inventario sincronizado"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/v1/sync/sales", methods=["POST", "GET"])
def sync_sales():
    try:
        from lock_util import acquire_lock
        with acquire_lock(timeout=10):
            import sync_ventas
            import importlib
            importlib.reload(sync_ventas)
            sync_ventas.sync_incremental()
        return jsonify({"status": "success", "message": "Ventas sincronizadas"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/v1/sync/run", methods=["POST", "GET"])
def trigger_sync_all():
    def run_all():
        try:
            from lock_util import acquire_lock
            with acquire_lock(timeout=10):
                import sync
                import sync_ventas
                import importlib
                importlib.reload(sync)
                importlib.reload(sync_ventas)
                sync.sync_incremental()
                sync_ventas.sync_incremental()
        except: pass
    
    threading.Thread(target=run_all, daemon=True).start()
    return jsonify({"status": "success", "message": "Sincronización completa iniciada"})

@app.route("/api/v1/sync/force", methods=["POST", "GET"])
def trigger_sync_force():
    def run_force():
        try:
            from lock_util import acquire_lock
            with acquire_lock(timeout=10):
                import sync
                import sync_ventas
                import importlib
                importlib.reload(sync)
                importlib.reload(sync_ventas)
                sync.sync_incremental(force=True)
                sync_ventas.sync_incremental()
        except: pass
    
    threading.Thread(target=run_force, daemon=True).start()
    return jsonify({"status": "success", "message": "Re-extracción forzada iniciada"})

_COUNT_CACHE = {}

@app.route("/api/v1/sync/status", methods=["GET"])
def sync_status():
    """Verifica integridad: compara conteos locales vs nube con caché de disco."""
    import csv
    import urllib.request
    global _COUNT_CACHE
    
    try:
        from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY
    except ImportError:
        return jsonify({"status": "error", "message": "Config no disponible"}), 500
    
    headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}", "Prefer": "count=exact"}
    
    def count_csv_smart(path):
        full = os.path.join(BASE_DIR, path)
        if not os.path.exists(full): return 0
        mtime = os.path.getmtime(full)
        # Si el archivo no cambió, devolver caché
        if path in _COUNT_CACHE and _COUNT_CACHE[path]["mtime"] == mtime:
            return _COUNT_CACHE[path]["count"]
        
        # Contar filas (optimizado)
        try:
            with open(full, 'rb') as f:
                count = sum(1 for line in f) - 1 # Restar cabecera
            _COUNT_CACHE[path] = {"count": max(0, count), "mtime": mtime}
            return _COUNT_CACHE[path]["count"]
        except: return 0
    
    def count_supabase(table):
        try:
            url = SUPABASE_REST_URL.rstrip('/') + "/rest/v1/" + table + "?select=count"
            req = urllib.request.Request(url, headers=headers, method="HEAD")
            with urllib.request.urlopen(req, timeout=10) as resp:
                cr = resp.headers.get("content-range", "*/0")
                return int(cr.split("/")[-1])
        except: return -1
    
    entities = {
        "productos": {"csv": "MAESTRO_ACTUAL.csv", "table": "productos"},
        "ventas": {"csv": "VENTAS_CABECERA.csv", "table": "ventas"},
        "detalle": {"csv": "VENTAS_DETALLE.csv", "table": "ventas_detalle"},
        "clientes": {"csv": "MAESTRO_CLIENTES.csv", "table": "clientes"},
    }
    
    result = {}
    all_ok = True
    for key, cfg in entities.items():
        local = count_csv_smart(cfg["csv"])
        cloud = count_supabase(cfg["table"])
        ok = (local == cloud) if cloud >= 0 else False
        if not ok: all_ok = False
        result[key] = {"local": local, "cloud": cloud, "ok": ok}
    
    from lock_util import is_locked
    locked = is_locked()
    
    last_mon = "--/-- --:--"
    try:
        mon_path = os.path.join(BASE_DIR, "last_monitor.json")
        if os.path.exists(mon_path):
            with open(mon_path, "r") as f:
                last_mon = json.load(f).get("last_check", last_mon)
    except: pass

    return jsonify({
        "status": "ok" if all_ok else "mismatch", 
        "entities": result,
        "is_syncing": locked,
        "last_monitor": last_mon
    })

@app.route("/health", methods=["GET"])
def health():
    """Endpoint de diagnóstico completo: drive, Supabase, monitor, sincronización."""
    try:
        from network_util import check_drive, check_supabase, get_local_ip
    except ImportError:
        return jsonify({"status": "error", "detail": "network_util no disponible"}), 500
    
    from config import RUTA_INVENTARIO
    
    drive = check_drive(RUTA_INVENTARIO)
    supabase = check_supabase()
    ip = get_local_ip()
    
    mon_path = os.path.join(BASE_DIR, "last_monitor.json")
    monitor_alive = False
    last_mon = "--/-- --:--"
    try:
        if os.path.exists(mon_path):
            with open(mon_path) as f:
                d = json.load(f)
                age = time.time() - d.get("timestamp", 0)
                monitor_alive = age < 120
                last_mon = d.get("last_check", last_mon)
    except: pass
    
    from lock_util import is_locked
    locked = is_locked()
    
    checks = {
        "drive_h": {"ok": drive, "path": RUTA_INVENTARIO},
        "supabase": supabase,
        "monitor": {"ok": monitor_alive, "last_seen": last_mon},
        "is_syncing": locked,
    }
    all_ok = all(v.get("ok", False) if isinstance(v, dict) else True for v in checks.values())
    
    return jsonify({
        "status": "ok" if all_ok else "degraded",
        "app": "El Serrucho Backend",
        "ip": ip,
        "checks": checks,
    })

if __name__ == "__main__":
    import socket
    port = 5000
    # Si el puerto está ocupado (restart rápido), probar puertos siguientes
    for attempt in range(5):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('0.0.0.0', port + attempt))
            s.close()
            app.run(host="0.0.0.0", port=port + attempt, debug=False)
            break
        except OSError:
            if attempt < 4:
                print(f"[APP] Puerto {port + attempt} ocupado, probando {port + attempt + 1}...")
                continue
            else:
                print(f"[APP] No se pudo encontrar puerto libre en rango {port}-{port+4}. Abortando.")
                sys.exit(1)
