from flask import Flask, jsonify, request
import os
import subprocess
import sys
import time
import json
import threading
from datetime import datetime
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
            "/api/v1/sync/sales"
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
    from lock_util import is_locked
    if is_locked():
        return jsonify({"status": "error", "message": "Sincronización en curso"}), 429
    
    res = subprocess.run([sys.executable, "sync.py", "once"], capture_output=True, text=True)
    if res.returncode == 0:
        return jsonify({"status": "success", "message": "Inventario sincronizado"})
    return jsonify({"status": "error", "message": res.stderr}), 500

@app.route("/api/v1/sync/sales", methods=["POST", "GET"])
def sync_sales():
    from lock_util import is_locked
    if is_locked():
        return jsonify({"status": "error", "message": "Sincronización en curso"}), 429
    
    res = subprocess.run([sys.executable, "sync_ventas.py", "once"], capture_output=True, text=True)
    if res.returncode == 0:
        return jsonify({"status": "success", "message": "Ventas sincronizadas"})
    return jsonify({"status": "error", "message": res.stderr}), 500

@app.route("/api/v1/sync/run", methods=["POST", "GET"])
def trigger_sync_all():
    def run_all():
        subprocess.run([sys.executable, "sync.py", "once"])
        subprocess.run([sys.executable, "sync_ventas.py", "once"])
    
    threading.Thread(target=run_all).start()
    return jsonify({"status": "success", "message": "Sincronización completa iniciada"})

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
    
    return jsonify({"status": "ok" if all_ok else "mismatch", "entities": result})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
