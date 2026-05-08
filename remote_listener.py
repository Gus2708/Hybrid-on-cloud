import time
import json
import urllib.request
import urllib.error
import os
import datetime

# --- CONFIGURACIÓN ---
try:
    import config
    SUPABASE_REST_URL = config.SUPABASE_REST_URL
    # Prioridad: SERVICE_KEY (si existe) -> ANON_KEY
    SUPABASE_KEY = getattr(config, 'SUPABASE_SERVICE_KEY', config.SUPABASE_ANON_KEY)
except ImportError:
    print("Error: Archivo 'config.py' no encontrado o incompleto.")
    exit(1)

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal"
}

LOG_FILE = "sync_remote.log"

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_message = f"[{timestamp}] {message}"
    print(formatted_message)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted_message + "\n")
    except Exception as e:
        print(f"Error escribiendo en log: {e}")

def get_pending_commands():
    # Buscamos 'pendiente' y también 'ejecutando' (por si el script se reinició)
    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/comandos_remotos?status=in.(pendiente,ejecutando)&select=id,comando,status"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            log("Error 401: No autorizado. Verifica las llaves de Supabase y las políticas RLS.")
        elif e.code == 404:
            log("Error 404: No se encontró la tabla 'comandos_remotos'.")
        else:
            log(f"HTTP Error al buscar comandos: {e.code} - {e.reason}")
        return []
    except Exception as e:
        log(f"Error inesperado buscando comandos: {e}")
        return []

def update_command_status(cmd_id, status):
    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/comandos_remotos?id=eq.{cmd_id}"
    data = json.dumps({
        "status": status,
        "ejecutado_en": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }).encode()
    
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="PATCH")
    try:
        with urllib.request.urlopen(req) as response:
            # 204 No Content es lo esperado con return=minimal
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        log(f"Error HTTP {e.code} actualizando {cmd_id} a '{status}': {body or e.reason}")
        return False
    except Exception as e:
        log(f"Error actualizando estado de comando {cmd_id} a '{status}': {e}")
        return False

def execute_local_sync(comando):
    endpoints = {
        "sync_inventory": "/api/v1/sync/inventory",
        "sync_sales": "/api/v1/sync/sales",
        "sync_all": "/api/v1/sync/run"
    }
    
    path = endpoints.get(comando, "/api/v1/sync/run")
    url = f"http://localhost:5000{path}"
    
    log(f"Ejecutando sync local: {url}...")
    
    # Timeout largo porque el sync puede tardar varios segundos/minutos
    req = urllib.request.Request(url, method="POST")
    try:
        # Usamos 120 segundos de timeout para estar seguros
        with urllib.request.urlopen(req, timeout=120) as response:
            res_data = response.read().decode()
            log(f"Respuesta local: {res_data[:200]}...")
            # Si el JSON dice status: success, retornamos True
            try:
                res_json = json.loads(res_data)
                return res_json.get("status") == "success"
            except:
                return True # Asumimos éxito si no hay error de conexión y devolvió algo
    except urllib.error.URLError as e:
        log(f"Error de conexión local (¿Está Flask corriendo?): {e.reason}")
        return False
    except Exception as e:
        log(f"Error ejecutando sync local: {e}")
        return False

log("=== Iniciando Listener de Comandos Remotos v2.1 ===")
log(f"Conectado a: {SUPABASE_REST_URL}")

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
            
            # 1. Marcar como ejecutando (solo si estaba pendiente)
            if status_actual == 'pendiente':
                if not update_command_status(cmd_id, "ejecutando"):
                    log(f"Saltando comando {cmd_id} por error al actualizar estado a 'ejecutando'.")
                    continue
            
            # 2. Ejecutar localmente
            success = execute_local_sync(comando)
            
            # 3. Marcar resultado final
            final_status = "completado" if success else "error_local"
            if update_command_status(cmd_id, final_status):
                log(f"Resultado final: {final_status} (Actualizado en Nube)")
            else:
                log(f"ADVERTENCIA: No se pudo actualizar resultado '{final_status}' en la nube.")
            
    except Exception as e:
        log(f"Error en el bucle principal: {e}")
        
    time.sleep(10)


