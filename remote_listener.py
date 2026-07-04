import os
import sys

if sys.executable.lower().endswith("pythonw.exe"):
    try:
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")
    except: pass

import time
import json
import urllib.request
import urllib.error
import threading
import subprocess
import datetime

LOG_FILE = "sync_remote.log"
_MAX_LOG_BYTES = 5 * 1024 * 1024

def _rotate_log(log_path: str):
    try:
        if os.path.exists(log_path) and os.path.getsize(log_path) > _MAX_LOG_BYTES:
            bak = log_path + ".1"
            if os.path.exists(bak): os.remove(bak)
            os.rename(log_path, bak)
    except: pass

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_message = message.encode('ascii', 'replace').decode('ascii')
    formatted_message = f"[{timestamp}] {safe_message}"
    print(formatted_message)
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(base_dir, LOG_FILE)
        _rotate_log(log_path)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        print(f"Error escribiendo en log: {e}")

try:
    import config
    SUPABASE_REST_URL = config.SUPABASE_REST_URL
    # Usar explícitamente ANON_KEY para las cabeceras de la API REST
    SUPABASE_ANON_KEY = config.SUPABASE_ANON_KEY
except ImportError:
    print("Error: Archivo 'config.py' no encontrado o incompleto.")
    exit(1)

log("=== Iniciando Listener de Comandos Remotos v2.4 ===")
log(f"Conectado a: {SUPABASE_REST_URL}")

# HEADERS de escritura (PATCH de status en comandos_remotos): usa
# SUPABASE_SERVICE_KEY si está configurada (vía build_write_headers en
# supabase_rest.py), si no cae al comportamiento actual con la anon key.
# try/except porque este listener debe seguir funcionando aunque falle el
# import (p.ej. supabase_rest.py roto o ausente).
try:
    from supabase_rest import build_write_headers
    HEADERS = build_write_headers(extra_prefer="return=minimal")
except Exception:
    HEADERS = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }

_consec_net_fails = 0

def get_pending_commands():
    global _consec_net_fails
    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/comandos_remotos?status=in.(pendiente,ejecutando)&select=id,comando,status"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            if _consec_net_fails >= 3:
                log("Conexión con Supabase recuperada.")
            _consec_net_fails = 0
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            log("Error 401: No autorizado. Verifica: 1) ANON_KEY vigente 2) RLS en 'comandos_remotos' permita SELECT para anon")
        elif e.code == 404:
            log("Error 404: No se encontro la tabla 'comandos_remotos'.")
        else:
            try:
                body = e.read().decode('utf-8')
            except:
                body = ""
            log(f"HTTP Error al buscar comandos: {e.code} - {body or e.reason}")
        return []
    except Exception as e:
        # Sin internet este error se repite cada 10s: loguear las primeras
        # veces y luego 1 de cada 30 (~5 min) para no inflar el log
        _consec_net_fails += 1
        if _consec_net_fails <= 3 or _consec_net_fails % 30 == 0:
            log(f"Error de red buscando comandos ({_consec_net_fails} seguidos): {repr(e)}")
        return []

def update_command_status(cmd_id, status):
    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/comandos_remotos?id=eq.{cmd_id}"
    data = json.dumps({
        "status": status,
        "ejecutado_en": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }).encode('utf-8')

    req = urllib.request.Request(url, data=data, headers=HEADERS, method="PATCH")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return True
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode('utf-8')
        except:
            body = ""
        detail = body or e.reason
        if e.code == 401:
            log(f"401 Unauthorized actualizando {cmd_id} a '{status}'. "
                f"Verificar: 1) ANON_KEY vigente en Supabase Dashboard 2) RLS en tabla 'comandos_remotos' permita UPDATE para anon")
        else:
            log(f"Error HTTP {e.code} actualizando {cmd_id} a '{status}': {detail}")
        return False
    except Exception as e:
        log(f"Error actualizando estado de comando {cmd_id} a '{status}': {repr(e)}")
        return False

def execute_local_sync(comando):
    import subprocess
    import sys

    scripts = {
        "sync_inventory": "sync.py",
        "sync_sales": "sync_ventas.py",
        "sync_all": "sync_ventas.py"
    }

    script_name = scripts.get(comando)
    if not script_name:
        log(f"Comando desconocido: {comando}")
        return False

    try:
        log(f"Ejecutando script internamente: {script_name}...")
        from lock_util import acquire_lock

        ok = True
        with acquire_lock(timeout=30):
            if comando == "sync_all":
                import sync
                import sync_ventas
                import importlib
                importlib.reload(sync)
                importlib.reload(sync_ventas)
                ok = sync.sync_incremental() is not False
                ok = (sync_ventas.sync_incremental() is not False) and ok
            elif comando == "sync_inventory":
                import sync
                import importlib
                importlib.reload(sync)
                ok = sync.sync_incremental() is not False
            elif comando == "sync_sales":
                import sync_ventas
                import importlib
                importlib.reload(sync_ventas)
                ok = sync_ventas.sync_incremental() is not False
            else:
                exe = sys.executable
                creation_flags = 0x08000000
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                if exe.lower().endswith("python.exe"):
                    pw = exe.lower().replace("python.exe", "pythonw.exe")
                    if os.path.exists(pw): exe = pw
                subprocess.run([exe, script_name, "once"], check=True, creationflags=creation_flags, startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if ok:
            log(f"Script {script_name} finalizado con exito.")
        else:
            log(f"Script {script_name} termino con errores (¿sin conexion o unidad H: caida?).")
        return ok
    except subprocess.CalledProcessError as e:
        log(f"Error ejecutando script {script_name}: {repr(e)}")
        return False
    except Exception as e:
        log(f"Error inesperado ejecutando localmente: {repr(e)}")
        return False


_COMMAND_TIMEOUT = 1800  # 30 minutos máximo
_HEARTBEAT_INTERVAL = 60

_last_heartbeat_ts = 0

while True:
    try:
        cmds = get_pending_commands()
        if cmds:
            log(f"Detectados {len(cmds)} comandos a procesar.")

        for c in cmds:
            cmd_id = c['id']
            comando = c['comando']
            status_actual = c.get('status', 'pendiente')

            log(f"--- Procesando: {comando} (ID: {cmd_id}, Status: {status_actual}) ---")

            # 🛡️ Timeout: si lleva >30 min en 'ejecutando', marcarlo como error
            if status_actual == 'ejecutando':
                try:
                    status_url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/comandos_remotos?id=eq.{cmd_id}&select=ejecutado_en"
                    req = urllib.request.Request(status_url, headers=HEADERS, method="GET")
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        rows = json.loads(resp.read().decode())
                        if rows and rows[0].get("ejecutado_en"):
                            started = datetime.datetime.fromisoformat(rows[0]["ejecutado_en"].replace("Z", "+00:00"))
                            elapsed = (datetime.datetime.now(datetime.timezone.utc) - started).total_seconds()
                            if elapsed > _COMMAND_TIMEOUT:
                                log(f"[TIMEOUT] Comando {cmd_id} lleva {elapsed:.0f}s en ejecutando (> {_COMMAND_TIMEOUT}s). Marcando como error...")
                                update_command_status(cmd_id, "error_local")
                except Exception as e:
                    log(f"Error verificando timeout de {cmd_id}: {e}")
                
                # ─── CRÍTICO: Si está en ejecución y no ha vencido el timeout, saltamos para dejar que continúe ───
                continue

            try:
                if status_actual == 'pendiente':
                    if not update_command_status(cmd_id, "ejecutando"):
                        log(f"Saltando comando {cmd_id} por error al actualizar estado a 'ejecutando'.")
                        continue

                success = execute_local_sync(comando)
                final_status = "completado" if success else "error_local"

            except Exception as e:
                log(f"Error procesando comando {cmd_id} ({comando}): {repr(e)}")
                final_status = "error_local"

            try:
                if update_command_status(cmd_id, final_status):
                    log(f"Resultado final: {final_status} (Actualizado en Nube)")
                else:
                    log(f"ADVERTENCIA: No se pudo actualizar resultado '{final_status}' en la nube.")
            except Exception as e:
                log(f"Error critico actualizando estado final de {cmd_id}: {repr(e)}")

        # ─── Heartbeat ───────────────────────────────────────────────────
        if time.time() - _last_heartbeat_ts > _HEARTBEAT_INTERVAL:
            try:
                hb_url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/comandos_remotos?id=eq.-1&select=id"
                req = urllib.request.Request(hb_url, headers=HEADERS, method="GET")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    _last_heartbeat_ts = time.time()
                    log(f"[HEARTBEAT] Listener vivo — {datetime.datetime.now().strftime('%H:%M:%S')}")
            except Exception:
                pass

    except Exception as e:
        log(f"Error en el bucle principal: {repr(e)}")

    time.sleep(10)

