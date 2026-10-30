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

try:
    from config import CORS_ORIGINS
except ImportError:
    CORS_ORIGINS = ["http://localhost:5000", "http://127.0.0.1:5000"]
CORS(app, origins=CORS_ORIGINS, supports_credentials=False)

def _require_sync_key():
    """Verifica X-API-Key para endpoints de sync. Retorna None si OK, Response si rechazado."""
    try:
        from config import SYNC_API_KEY
    except ImportError:
        return None
    if not SYNC_API_KEY:
        return None  # Sin key configurada → modo desarrollo, sin restricción
    if request.headers.get("X-API-Key", "") != SYNC_API_KEY:
        return jsonify({"status": "error", "message": "API key inválida o ausente"}), 401
    return None

# --- Configuración y Estado ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_SOURCE_PATH = os.path.join(BASE_DIR, "MAESTRO_ACTUAL.csv")

_LOCAL_CACHE = []
_LAST_LOAD_TIME = 0
_CACHE_LOCK = threading.Lock()  # Waitress sirve con varios hilos: evita cargas concurrentes del CSV

def _load_inventory_if_needed():
    global _LOCAL_CACHE, _LAST_LOAD_TIME
    with _CACHE_LOCK:
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
        item["referencia"] = item.get("REFERENCIA", "")
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
    try:
        limit = max(0, int(request.args.get("limit", 50)))
        offset = max(0, int(request.args.get("offset", 0)))
    except (ValueError, TypeError):
        limit, offset = 50, 0

    if not q:
        encontrados = _LOCAL_CACHE
    else:
        encontrados = [
            p for p in _LOCAL_CACHE 
            if q in p.get("CODIGO_INTERNO", "").upper() or q in p.get("DESCRIPCION", "").upper() or q in p.get("CODIGO_BARRAS", "").upper() or q in p.get("REFERENCIA", "").upper()
        ]

    total = len(encontrados)
    pagina = encontrados[offset : offset + limit]

    return jsonify({
        "total": total,
        "results": [_enrich(p) for p in pagina]
    })

_RATES_CACHE = {"data": None, "ts": 0.0}
_RATES_CACHE_TTL = 120.0  # 2 minutos

@app.route("/api/v1/rates", methods=["GET"])
def get_rates():
    """Devuelve las tasas de cambio vigentes con caché local en memoria."""
    global _RATES_CACHE
    now = time.time()
    if _RATES_CACHE["data"] and (now - _RATES_CACHE["ts"]) < _RATES_CACHE_TTL:
        return jsonify(_RATES_CACHE["data"])
    try:
        from rates_service import RatesService
        service = RatesService()
        rates = service.get_all_rates()
        if rates:
            _RATES_CACHE = {"data": rates, "ts": now}
            return jsonify(rates)
    except Exception as e:
        if _RATES_CACHE["data"]:
            return jsonify(_RATES_CACHE["data"])
        return jsonify({"error": str(e)}), 500
    return jsonify(_RATES_CACHE["data"] or {})

@app.route("/api/v1/sync/inventory", methods=["POST", "GET"])
def sync_inventory():
    auth_err = _require_sync_key()
    if auth_err:
        return auth_err
    try:
        from lock_util import acquire_lock
        from flask import request
        force = bool(request.args.get("force"))
        import sync
        with acquire_lock(timeout=10):
            sync.sync_incremental(force=force)
        invalidate_supabase_count_cache()
        return jsonify({"status": "success", "message": "Inventario sincronizado"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/v1/sync/sales", methods=["POST", "GET"])
def sync_sales():
    auth_err = _require_sync_key()
    if auth_err:
        return auth_err
    try:
        from lock_util import acquire_lock
        from flask import request
        force = bool(request.args.get("force"))
        import sync_ventas
        with acquire_lock(timeout=10):
            sync_ventas.sync_incremental(force=force)
        invalidate_supabase_count_cache()
        return jsonify({"status": "success", "message": "Ventas sincronizadas"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/v1/sync/run", methods=["POST", "GET"])
def trigger_sync_all():
    auth_err = _require_sync_key()
    if auth_err:
        return auth_err
    def run_all():
        try:
            from lock_util import acquire_lock
            import sync
            import sync_ventas
            with acquire_lock(timeout=45):
                sync.sync_incremental(force=True)
                sync_ventas.sync_incremental(force=True)
            invalidate_supabase_count_cache()
        except Exception as e:
            print(f"[APP] Error en sync/run: {e}")

    threading.Thread(target=run_all, daemon=True).start()
    return jsonify({"status": "success", "message": "Sincronización completa iniciada"})

@app.route("/api/v1/sync/force", methods=["POST", "GET"])
def trigger_sync_force():
    auth_err = _require_sync_key()
    if auth_err:
        return auth_err
    def run_force():
        try:
            from lock_util import acquire_lock
            import sync
            import sync_ventas
            with acquire_lock(timeout=45):
                sync.sync_incremental(force=True)
                sync_ventas.sync_incremental(force=True)
            invalidate_supabase_count_cache()
        except Exception as e:
            print(f"[APP] Error en sync/force: {e}")

    threading.Thread(target=run_force, daemon=True).start()
    return jsonify({"status": "success", "message": "Re-extracción forzada iniciada"})

_COUNT_CACHE = {}
_SUPABASE_COUNT_CACHE = {}
_SUPABASE_COUNT_CACHE_TTL = 30.0  # reducido de 300s a 30s para evitar falsas discrepancias prolongadas

def invalidate_supabase_count_cache():
    global _SUPABASE_COUNT_CACHE
    _SUPABASE_COUNT_CACHE.clear()

def _get_latest_sync_mtime():
    latest = 0.0
    for f in ["last_sync.json", "ventas_last_sync.json"]:
        p = os.path.join(BASE_DIR, f)
        if os.path.exists(p):
            try:
                mt = os.path.getmtime(p)
                if mt > latest:
                    latest = mt
            except Exception:
                pass
    return latest

@app.route("/api/v1/sync/status", methods=["GET"])
def sync_status():
    """Verifica integridad: compara conteos locales vs nube con caché de disco."""
    import csv
    import urllib.request
    from flask import request
    global _COUNT_CACHE, _SUPABASE_COUNT_CACHE
    
    try:
        from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY
    except ImportError:
        return jsonify({"status": "error", "message": "Config no disponible"}), 500
    
    headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}", "Prefer": "count=exact"}
    force_fresh = bool(request.args.get("fresh"))
    latest_sync_mtime = _get_latest_sync_mtime()
    
    # ⚡ Verificación rápida de conectividad TCP a Supabase (evita bloqueos de 40s si la red/VPN falla)
    supabase_reachable = False
    try:
        from urllib.parse import urlparse
        import socket
        parsed_url = urlparse(SUPABASE_REST_URL)
        host = parsed_url.hostname
        port = parsed_url.port or (443 if parsed_url.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=1.5):
            supabase_reachable = True
    except Exception:
        supabase_reachable = False

    def count_csv_smart(path):
        full = os.path.join(BASE_DIR, path)
        if not os.path.exists(full):
            return _COUNT_CACHE.get(path, {}).get("count", 0)
        try:
            mtime = os.path.getmtime(full)
            # Si el archivo no cambió, devolver caché
            if path in _COUNT_CACHE and _COUNT_CACHE[path]["mtime"] == mtime:
                return _COUNT_CACHE[path]["count"]
            
            # Contar filas (optimizado)
            with open(full, 'rb') as f:
                count = sum(1 for line in f) - 1 # Restar cabecera
            _COUNT_CACHE[path] = {"count": max(0, count), "mtime": mtime}
            return _COUNT_CACHE[path]["count"]
        except Exception:
            return _COUNT_CACHE.get(path, {}).get("count", 0)
    
    def count_detalle_valid():
        """Cuenta líneas de detalle cuyo producto existe en el maestro (las demás no se suben por FK)."""
        det = os.path.join(BASE_DIR, "VENTAS_DETALLE.csv")
        mae = os.path.join(BASE_DIR, "MAESTRO_ACTUAL.csv")
        if not (os.path.exists(det) and os.path.exists(mae)):
            return count_csv_smart("VENTAS_DETALLE.csv")
        try:
            from sync_utils import count_valid_detail_rows
            key = (os.path.getmtime(det), os.path.getmtime(mae))
            cached = _COUNT_CACHE.get("detalle_valid")
            if cached and cached["mtime"] == key:
                return cached["count"]
            count = count_valid_detail_rows(det, mae)
            _COUNT_CACHE["detalle_valid"] = {"count": count, "mtime": key}
            return count
        except Exception:
            return count_csv_smart("VENTAS_DETALLE.csv")

    def count_supabase(table):
        if not supabase_reachable:
            return -1
        now = time.time()
        cached = _SUPABASE_COUNT_CACHE.get(table)
        if force_fresh:
            cached = None
        elif cached and cached.get("ts", 0) < latest_sync_mtime:
            # Hubo una sincronización en disco posterior al cache -> invalidar
            cached = None
        elif cached and (now - cached["ts"]) < _SUPABASE_COUNT_CACHE_TTL:
            return cached["count"]
        try:
            url = SUPABASE_REST_URL.rstrip('/') + "/rest/v1/" + table + "?select=count"
            req = urllib.request.Request(url, headers=headers, method="HEAD")
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                cr = resp.headers.get("content-range", "*/0")
                val = int(cr.split("/")[-1])
                _SUPABASE_COUNT_CACHE[table] = {"count": val, "ts": now}
                return val
        except:
            if cached:
                return cached["count"]
            return -1
    
    entities = {
        "productos": {"csv": "MAESTRO_ACTUAL.csv", "table": "productos"},
        "ventas": {"csv": "VENTAS_CABECERA.csv", "table": "ventas"},
        "detalle": {"csv": "VENTAS_DETALLE.csv", "table": "ventas_detalle"},
        "clientes": {"csv": "MAESTRO_CLIENTES.csv", "table": "clientes"},
    }
    
    result = {}
    all_ok = True
    for key, cfg in entities.items():
        local = count_detalle_valid() if key == "detalle" else count_csv_smart(cfg["csv"])
        cloud = count_supabase(cfg["table"])
        # Permitir una pequeña tolerancia de hasta 2 registros por registros corruptos u huérfanos omitidos
        ok = (abs(local - cloud) <= 2) if cloud >= 0 else False
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

@app.route("/api/v1/tunnel/status", methods=["GET"])
def tunnel_status():
    """Estado actual de los túneles Cloudflare (n8n/WAHA) para el CRM."""
    try:
        import tunnel_heartbeat
        return jsonify(tunnel_heartbeat.status())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/v1/tunnel/urls", methods=["GET"])
def tunnel_urls():
    """URLs públicas vigentes de los túneles (para que el CRM las use)."""
    try:
        import tunnel_heartbeat
        return jsonify({"status": "ok", "urls": tunnel_heartbeat.urls()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    """Endpoint de diagnóstico completo con timeouts para no bloquear."""
    try:
        from network_util import (
            check_drive,
            check_supabase,
            get_local_ip,
            check_waha,
            check_maxcam,
            check_corpnorte,
        )
    except ImportError:
        return jsonify({"status": "error", "detail": "network_util no disponible"}), 500
    
    from config import RUTA_INVENTARIO
    
    # Ejecutar check_drive en un hilo con timeout para no bloquear Flask
    # si la unidad H: está colgada
    drive = False
    def _check():
        nonlocal drive
        drive = check_drive(RUTA_INVENTARIO)
    t = threading.Thread(target=_check, daemon=True)
    t.start()

    from network_util import run_checks_parallel
    # Los chequeos de red corren en paralelo entre sí y con el sondeo del drive:
    # el total es el más lento (tope ~5s), no la suma.
    parallel = run_checks_parallel({
        "supabase": check_supabase,
        "waha": check_waha,
        "maxcam": check_maxcam,
        "corpnorte": check_corpnorte,
    }, timeout=5)
    t.join(timeout=0.1)
    if t.is_alive():
        drive = False
    supabase = parallel["supabase"]
    waha = parallel["waha"]
    maxcam = parallel["maxcam"]
    corpnorte = parallel["corpnorte"]
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
        "waha": waha,
        "maxcam": maxcam,
        "corpnorte": corpnorte,
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
    port = int(os.environ.get("PORT", 5000))

    def _log_startup(msg):
        print(msg)
        # Con pythonw.exe stdout va a devnull; sin este log los fallos de
        # arranque (puerto ocupado, etc.) eran invisibles.
        try:
            log_path = os.path.join(BASE_DIR, "api_startup.log")
            if os.path.exists(log_path) and os.path.getsize(log_path) > 1024 * 1024:
                os.replace(log_path, log_path + ".1")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except: pass

    listen_sock = None
    max_retries = 6
    retry_delay = 2

    for attempt in range(max_retries):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Enlace EXCLUSIVO. Con SO_REUSEADDR, Windows permite que dos
            # procesos se enlacen al mismo puerto: las conexiones caen en un
            # socket que nunca responde y el widget ve "API local no responde"
            # aunque el puerto acepte conexiones.
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind(('0.0.0.0', port))
            s.listen(128)
            listen_sock = s
            break
        except OSError as e:
            try: s.close()
            except: pass
            if attempt < max_retries - 1:
                _log_startup(f"[APP] Puerto {port} ocupado ({e}). Reintentando en {retry_delay}s (intento {attempt+1}/{max_retries})...")
                time.sleep(retry_delay)
            else:
                _log_startup(f"[APP] No se pudo enlazar al puerto {port} tras {max_retries} intentos. Abortando.")
                sys.exit(1)

    try:
        from waitress import serve
        _log_startup(f"[APP] Sirviendo con Waitress en 0.0.0.0:{port} (8 hilos)")
        # Se le pasa el socket ya enlazado: elimina la carrera entre el test
        # de puerto y el bind interno de waitress.
        serve(app, sockets=[listen_sock], threads=8)
    except ImportError:
        _log_startup("[APP] Waitress no está instalado. Usando servidor de desarrollo de Flask como fallback.")
        listen_sock.close()
        app.run(host="0.0.0.0", port=port, debug=False)
