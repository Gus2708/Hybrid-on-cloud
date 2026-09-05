"""
tunnel_heartbeat.py — Gestión de túneles Cloudflare (quick tunnel) para el CRM.

Levanta un quick tunnel de cloudflared por cada servicio local (n8n y WAHA),
captura la URL pública actual de cada uno y la publica en Supabase (tabla
tunnel_config) para que el CRM de empleados pueda alcanzar n8n/WAHA desde la
nube sin necesidad de un dominio fijo.

Comportamiento:
  * Lanza un proceso `cloudflared tunnel --url <local>` por servicio.
  * Lee el log de cada proceso y extrae la URL `https://*.trycloudflare.com`.
  * Cuando una URL cambia (o arranca), la hace upsert en Supabase.
  * Hace heartbeat periódico (updated_at) para que el CRM detecte túneles vivos.
  * Si un proceso muere, lo reinicia automáticamente y publica su nueva URL.
  * Registra errores en last_error y marca tunnel_state = 'running' | 'error' | 'down'.

API REST local (opcional, para debug del widget/dashboard):
  GET  /tunnel/status  -> estado actual de cada túnel.
  GET  /tunnel/urls    -> las URLs vigentes (para ver desde el dashboard).
"""
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent

# ─── Configuración (leer desde entorno o .env a través de config) ────────────
CLOUDFLARED_BIN = os.environ.get(
    "CLOUDFLARED_BIN",
    r"C:\Users\OFICINA\AppData\Local\Microsoft\WindowsApps\cloudflared.exe",
)
if not os.path.exists(CLOUDFLARED_BIN):
    # Fallback: buscar en PATH
    import shutil
    CLOUDFLARED_BIN = shutil.which("cloudflared") or "cloudflared"

# Servicios a exponer: {servicio: puerto local}
SERVICIOS = {}
for _serv, _port in [("n8n", 5678), ("waha", 3000)]:
    if os.environ.get(f"TUNNEL_{_serv.upper()}_PORT"):
        try:
            _port = int(os.environ[f"TUNNEL_{_serv.upper()}_PORT"])
        except ValueError:
            pass
    if os.environ.get(f"TUNNEL_{_serv.upper()}_ENABLED", "1") == "1":
        SERVICIOS[_serv] = _port

HEARTBEAT_INTERVAL = float(os.environ.get("TUNNEL_HEARTBEAT_INTERVAL", "30"))  # segundos
RESTART_DELAY = float(os.environ.get("TUNNEL_RESTART_DELAY", "5"))
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

URL_RE = re.compile(r"https://([a-z0-9-]+)\.trycloudflare\.com")

# Estado en memoria del sistema
_state = {
    "servicios": {},          # servicio -> dict con: proc, log_path, url, pid
    "lock": threading.Lock(),
}

# ─── Supabase: usar el mismo helper del backend ──────────────────────────────
try:
    from supabase_rest import build_write_headers
except Exception:
    build_write_headers = None

try:
    from config import SUPABASE_REST_URL as _REST, SUPABASE_ANON_KEY as _ANON, SUPABASE_SERVICE_KEY as _SERV
except Exception:
    _REST = ""
    _ANON = ""
    _SERV = ""

REST_URL = os.environ.get("SUPABASE_REST_URL", _REST) or ""
ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", _ANON) or ""


def _write_headers(extra_prefer=None):
    """Headers de escritura: usa build_write_headers si existe, si no los arma solos."""
    if build_write_headers is not None:
        try:
            return build_write_headers(extra_prefer)
        except Exception:
            pass
    write_key = os.environ.get("SUPABASE_SERVICE_KEY", _SERV) or ANON_KEY
    return {
        "apikey": ANON_KEY,
        "Authorization": f"Bearer {write_key}",
        "Content-Type": "application/json",
        "Prefer": extra_prefer or "return=minimal,resolution=merge-duplicates",
    }


def _http(method, url, headers, body=None, timeout=15):
    """Petición HTTP con urllib (sin dependencias)."""
    import urllib.request
    import urllib.error

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, str(e)


def supabase_ready():
    return bool(REST_URL and ANON_KEY)


def upsert_tunnel(servicio, url, tunnel_state, last_error=None):
    """Upsert de una fila en tunnel_config. Retorna True/False."""
    if not supabase_ready():
        return False
    body = {
        "servicio": servicio,
        "url": url or None,
        "tunnel_state": tunnel_state,
        "last_error": last_error,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        url = f"{REST_URL.rstrip('/')}/rest/v1/tunnel_config?on_conflict=servicio"
        headers = _write_headers(extra_prefer="return=minimal,resolution=merge-duplicates")
        code, text = _http("POST", url, headers, body=body)
        return code is not None and 200 <= code < 300
    except Exception:
        return False


def _read_url_from_log(log_path):
    """Extrae la URL vigente de un log de cloudflared."""
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = URL_RE.search(line)
                if m:
                    # Tomar la primera aparición estable (trycloudflare)
                    return "https://" + m.group(1) + ".trycloudflare.com"
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return None


def _spawn(servicio, port):
    """Lanza un proceso cloudflared para un servicio. Retorna una tupla."""
    log_path = LOG_DIR / f"tunnel_{servicio}.log"
    # Rotar log viejo para no leer URLs obsoletas
    if log_path.exists():
        try:
            log_path.rename(LOG_DIR / f"tunnel_{servicio}.log.old")
        except Exception:
            try:
                log_path.unlink()
            except Exception:
                pass

    logf = open(log_path, "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [
                CLOUDFLARED_BIN,
                "tunnel",
                "--url", f"http://localhost:{port}",
                "--no-autoupdate",
                "--loglevel", "info",
                "--logfile", str(log_path),
            ],
            stdout=logf,
            stderr=logf,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as e:
        logf.close()
        raise e
    return proc, log_path


def _monitor_died(proc):
    """Devuelve True si el proceso terminó (poll != None)."""
    return proc.poll() is not None


def _ensure_running(servicio, port):
    """Asegura que el túnel del servicio esté corriendo y retorna url (o None)."""
    with _state["lock"]:
        binfo = _state["servicios"].get(servicio)

        # Si el proceso murió, limpiar
        if binfo and binfo.get("proc") and _monitor_died(binfo["proc"]):
            binfo["proc"] = None
            binfo["url"] = None

        # Lanzar si no hay proceso vivo
        if not binfo or not binfo.get("proc"):
            try:
                proc, log_path = _spawn(servicio, port)
                binfo = {"proc": proc, "log_path": log_path, "url": None, "pid": proc.pid}
                _state["servicios"][servicio] = binfo
                print(f"[TUNNEL] {servicio} lanzado (pid {proc.pid})")
            except Exception as e:
                _state["servicios"][servicio] = {"proc": None, "log_path": None, "url": None,
                                                 "error": str(e)}
                return None

        # Leer URL del log
        url = _read_url_from_log(binfo["log_path"]) if binfo.get("log_path") else None
        binfo["url"] = url
        return url


def run_loop():
    """Bucle principal: mantiene túneles y hace heartbeat a Supabase."""
    print("[TUNNEL] Heartbeat iniciado. Servicios:", ", ".join(SERVICIOS) or "(ninguno)")
    if not supabase_ready():
        print("[TUNNEL] ADVERTENCIA: Supabase no configurado. Solo se publicará el estado local.")

    while True:
        known_urls = {}
        try:
            for servicio, port in SERVICIOS.items():
                url = _ensure_running(servicio, port)
                binfo = _state["servicios"].get(servicio, {})
                dead = binfo.get("proc") and _monitor_died(binfo["proc"])
                state = "error" if binfo.get("error") else ("down" if not url or dead else "running")
                last_error = binfo.get("error")
                known_urls[servicio] = {"url": url, "state": state}

                if url:
                    upsert_tunnel(servicio, url, state, last_error)
                else:
                    # No URL aún: marcar estado sin URL
                    if supabase_ready():
                        upsert_tunnel(servicio, None, state,
                                      "Esperando URL del túnel (aún no disponible)" if not dead else "proceso caído")

            # Heartbeat: refrescar updated_at de los servicios con URL
            for servicio, info in known_urls.items():
                if info["url"]:
                    upsert_tunnel(servicio, info["url"], info["state"], None)

        except Exception as e:
            print(f"[TUNNEL] Error en bucle: {e}")
            for servicio in SERVICIOS:
                upsert_tunnel(servicio,
                              _state["servicios"].get(servicio, {}).get("url"),
                              "error", str(e))

        time.sleep(HEARTBEAT_INTERVAL)


def _status_payload():
    out = {"servicios": {}}
    for servicio, port in SERVICIOS.items():
        binfo = _state["servicios"].get(servicio, {})
        proc = binfo.get("proc")
        dead = proc and _monitor_died(proc)
        url = binfo.get("url")
        state = binfo.get("error", "down" if (not url or dead) else "running")
        out["servicios"][servicio] = {
            "local_port": port,
            "url": url,
            "state": state,
            "pid": binfo.get("pid"),
            "running": bool(proc and not dead),
        }
    out["supabase_ready"] = supabase_ready()
    return out


def _fetch_tunnel_config():
    """Lee el estado vigente de los túneles desde Supabase (fuente de verdad).

    Como el heartbeat corre como proceso separado, el modulo importado desde
    app.py no comparte memoria con el; por eso leemos de la tabla.
    """
    rows = {}
    if not supabase_ready():
        return rows
    try:
        import urllib.request
        url = f"{REST_URL.rstrip('/')}/rest/v1/tunnel_config?select=servicio,url,tunnel_state,updated_at,last_error&order=servicio"
        req = urllib.request.Request(url, headers={
            "apikey": ANON_KEY,
            "Authorization": f"Bearer {ANON_KEY}",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        for row in data:
            rows[row.get("servicio")] = row
    except Exception:
        pass
    return rows


def status():
    cfg = _fetch_tunnel_config()
    if cfg:
        out = {"servicios": {}}
        for servicio, port in SERVICIOS.items():
            row = cfg.get(servicio) or {}
            out["servicios"][servicio] = {
                "local_port": port,
                "url": row.get("url"),
                "state": row.get("tunnel_state", "desconocido"),
                "pid": None,
                "running": row.get("tunnel_state") == "running" and bool(row.get("url")),
                "last_error": row.get("last_error"),
                "updated_at": row.get("updated_at"),
            }
        out["supabase_ready"] = True
        return out
    return _status_payload()


def urls():
    cfg = _fetch_tunnel_config()
    if cfg:
        return {s: (cfg.get(s) or {}).get("url") for s in SERVICIOS}
    return {s: v["url"] for s, v in _status_payload()["servicios"].items()}


if __name__ == "__main__":
    try:
        run_loop()
    except KeyboardInterrupt:
        # Terminar procesos hijos al cerrar
        for servicio, binfo in _state["servicios"].items():
            proc = binfo.get("proc")
            if proc and not _monitor_died(proc):
                try:
                    proc.terminate()
                except Exception:
                    pass
        print("\n[TUNNEL] Detenido.")
        sys.exit(0)
