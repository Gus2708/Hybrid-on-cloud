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
    # Helper para el widget antiguo
    def run_all():
        subprocess.run([sys.executable, "sync.py", "once"])
        subprocess.run([sys.executable, "sync_ventas.py", "once"])
    
    threading.Thread(target=run_all).start()
    return jsonify({"status": "success", "message": "Sincronización completa iniciada"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
