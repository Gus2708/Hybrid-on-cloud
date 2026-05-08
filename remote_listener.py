import time
import json
import urllib.request
import urllib.error
import os
import datetime

# --- CONFIGURACIÓN ---
# Recomendado: Usar SERVICE_ROLE_KEY para saltar RLS en este script de backend.
try:
    from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY
    # Si tienes la SERVICE_ROLE_KEY, úsala aquí:
    # SUPABASE_KEY = getattr(config, 'SUPABASE_SERVICE_KEY', SUPABASE_ANON_KEY)
    SUPABASE_KEY = SUPABASE_ANON_KEY 
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
    # Solo buscamos los que están en 'pendiente'
    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/comandos_remotos?status=eq.pendiente&select=id,comando"
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
            return True
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
    
    # Timeout de 60 segundos porque el sync puede tardar
    req = urllib.request.Request(url, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            res_data = response.read().decode()
            log(f"Respuesta local: {res_data[:100]}...")
            return True
    except urllib.error.URLError as e:
        log(f"Error de conexión local (¿Está Flask corriendo?): {e.reason}")
        return False
    except Exception as e:
        log(f"Error ejecutando sync local: {e}")
        return False

log("=== Iniciando Listener de Comandos Remotos v2 ===")
log(f"Conectado a: {SUPABASE_REST_URL}")

while True:
    try:
        cmds = get_pending_commands()
        if cmds:
            log(f"Detectados {len(cmds)} comandos pendientes.")
            
        for c in cmds:
            cmd_id = c['id']
            comando = c['comando']
            
            log(f"--- Procesando: {comando} (ID: {cmd_id}) ---")
            
            # 1. Marcar como ejecutando
            if not update_command_status(cmd_id, "ejecutando"):
                log(f"Saltando comando {cmd_id} por error al actualizar estado.")
                continue
            
            # 2. Ejecutar localmente
            success = execute_local_sync(comando)
            
            # 3. Marcar resultado final
            final_status = "completado" if success else "error_local"
            update_command_status(cmd_id, final_status)
            log(f"Resultado final: {final_status}")
            
    except Exception as e:
        log(f"Error en el bucle principal: {e}")
        
    time.sleep(10)

