"""
network_util.py — Diagnóstico de conectividad y protecciones contra fallos de red.
Usado por monitor, sync, widget y app para decidir si operar o esperar.
"""
import os
import time
import sys
import socket
import threading
import urllib.request
import urllib.error
import json

try:
    from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY
except ImportError:
    SUPABASE_REST_URL = ""
    SUPABASE_ANON_KEY = ""


_DRIVE_CACHE = {}
_PROBE_IN_FLIGHT = set()
_PROBE_LOCK = threading.Lock()


def _probe_drive(drive: str) -> bool:
    """Sondeo real del disco. Puede bloquear largo rato si la unidad SMB está caída."""
    try:
        if not os.path.exists(drive):
            return False
        next(os.scandir(drive), None)
        return True
    except Exception:
        return False


def check_drive(path: str, timeout: float = 2.0) -> bool:
    """Verifica si un directorio/unidad de red responde con caché de corto plazo.

    El sondeo corre en un hilo aparte con timeout duro: os.path.exists sobre una
    unidad SMB caída puede bloquear 30-60s y congelaba monitor/app/sync.
    Si el sondeo no responde en `timeout` segundos se considera caída.
    """
    if not path: return False

    drive = os.path.splitdrive(path)[0] or path
    now = time.time()

    # Caché de 10 segundos para evitar bloqueos seguidos
    if drive in _DRIVE_CACHE:
        cached_val, ts = _DRIVE_CACHE[drive]
        if now - ts < 10:
            return cached_val

    # Si ya hay un sondeo colgado para esta unidad, no apilar más hilos
    with _PROBE_LOCK:
        if drive in _PROBE_IN_FLIGHT:
            return _DRIVE_CACHE.get(drive, (False, now))[0]
        _PROBE_IN_FLIGHT.add(drive)

    result = {"ok": False}

    def _worker():
        try:
            result["ok"] = _probe_drive(drive)
        finally:
            with _PROBE_LOCK:
                _PROBE_IN_FLIGHT.discard(drive)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)
    ok = result["ok"] and not t.is_alive()
    _DRIVE_CACHE[drive] = (ok, now)
    return ok



def wait_for_drive(path: str, timeout: float = 60.0, interval: float = 3.0) -> bool:
    """Espera bloqueante hasta que la unidad esté disponible."""
    start = time.time()
    while time.time() - start < timeout:
        if check_drive(path):
            elapsed = time.time() - start
            if elapsed > 1:
                print(f"[NET] Drive {os.path.splitdrive(path)[0]} reconectado tras {elapsed:.0f}s")
            return True
        time.sleep(interval)
    return False


def check_supabase() -> dict:
    """Verifica conectividad con Supabase. Devuelve {'ok': bool, 'detail': str, 'latency': float}."""
    if not SUPABASE_REST_URL or not SUPABASE_ANON_KEY:
        return {"ok": False, "detail": "Sin configuración", "latency": 0}
    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/productos?limit=1"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    }
    before = time.time()
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            latency = (time.time() - before) * 1000
            return {"ok": resp.getcode() == 200, "detail": f"HTTP {resp.getcode()}", "latency": round(latency, 1)}
    except urllib.error.HTTPError as e:
        return {"ok": False, "detail": f"HTTP {e.code}", "latency": 0}
    except Exception as e:
        return {"ok": False, "detail": str(e)[:80], "latency": 0}


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def format_elapsed(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def check_waha() -> dict:
    """Verifica el estado de la sesión default en WAHA.
    Retorna {'ok': bool, 'status': str, 'detail': str}.
    """
    env_path = r"C:\Proyect\whatsapp-agent\.env"
    api_key = ""
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("WAHA_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass

    if not api_key:
        api_key = "REDACTED-API-KEY"

    url = "http://localhost:3000/api/sessions/default"
    headers = {
        "X-Api-Key": api_key,
        "Content-Type": "application/json"
    }
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode())
            status = data.get("status", "UNKNOWN")
            ok = (status == "WORKING")
            return {"ok": ok, "status": status, "detail": f"Status: {status}"}
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {"ok": False, "status": "UNAUTHORIZED", "detail": "API Key inválida"}
        return {"ok": False, "status": "ERROR", "detail": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "status": "OFFLINE", "detail": "Servidor offline / puerto cerrado"}

