import time
import json
import urllib.request
import urllib.error
import os

try:
    from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY
except ImportError:
    print("Error: Configuración de Supabase no encontrada.")
    exit(1)

HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    "Content-Type": "application/json"
}

def get_pending_commands():
    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/comandos_remotos?status=eq.pendiente&select=*"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except:
        return []

def update_command_status(cmd_id, status):
    url = f"{SUPABASE_REST_URL.rstrip('/')}/rest/v1/comandos_remotos?id=eq.{cmd_id}"
    data = json.dumps({"status": status}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="PATCH")
    try:
        with urllib.request.urlopen(req) as resp:
            return True
    except:
        return False

def trigger_local_sync():
    """Llama al servidor local Flask para iniciar la sincronización."""
    try:
        urllib.request.urlopen("http://localhost:5000/api/v1/sync/run", timeout=5)
        return True
    except:
        return False

def main_loop():
    print("[REMOTE LISTENER] Iniciado. Vigilando comandos desde la Nube...")
    while True:
        try:
            cmds = get_pending_commands()
            for cmd in cmds:
                cmd_id = cmd["id"]
                cmd_name = cmd["comando"]
                
                if cmd_name == "sync_all":
                    print(f"  -> Comando recibido: {cmd_name}. Avisando al Widget...")
                    if update_command_status(cmd_id, "ejecutando"):
                        if trigger_local_sync():
                            print("     [OK] Sincronización iniciada localmente.")
                            update_command_status(cmd_id, "completado")
                        else:
                            print("     [ERROR] El servidor local (App.py) no responde.")
                            update_command_status(cmd_id, "error_local")
            
        except Exception as e:
            print(f"[ERROR] En loop remoto: {e}")
            
        time.sleep(10) # Revisar cada 10 segundos para no saturar

if __name__ == "__main__":
    main_loop()
