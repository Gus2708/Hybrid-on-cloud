"""
network_util.py — Diagnóstico de conectividad y protecciones contra fallos de red.
Usado por monitor, sync, widget y app para decidir si operar o esperar.
"""
import os
import time
import sys
import socket
import urllib.request
import urllib.error
import json

try:
    from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY
except ImportError:
    SUPABASE_REST_URL = ""
    SUPABASE_ANON_KEY = ""


def check_drive(path: str, timeout: float = 3.0) -> bool:
    """Verifica si un directorio/unidad de red responde."""
    if not path:
        return False
    try:
        drive = os.path.splitdrive(path)[0] or path
        if not os.path.exists(drive):
            return False
        before = time.time()
        next(os.scandir(drive), None)
        elapsed = time.time() - before
        if elapsed > timeout:
            print(f"[NET] Drive {drive} lento: {elapsed:.1f}s")
        return elapsed < 30.0
    except (PermissionError, OSError):
        return False
    except Exception:
        return False


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
        with urllib.request.urlopen(req, timeout=10) as resp:
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
