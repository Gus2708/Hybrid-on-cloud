import time
import requests
import threading
from datetime import datetime
import os
import sys

# Importar configuración y logger
try:
    import config
    from logger import logger
except ImportError:
    # Manejar rutas si se corre directamente desde una subcarpeta
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    import config
    from logger import logger

def start_remote_listener():
    """Realiza polling a la tabla comandos_remotos de Supabase para procesar órdenes."""
    
    # URL de la tabla (usamos la config del cliente)
    url = f"{config.SUPABASE_REST_URL.rstrip('/')}/rest/v1/comandos_remotos"
    headers = {
        "apikey": config.SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {config.SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

    logger.info("[REMOTE] Listener de comandos iniciado (Polling cada 10s)")
    
    while True:
        try:
            # 1. Buscar el comando pendiente más antiguo
            query_url = f"{url}?status=eq.pendiente&order=created_at.asc&limit=1"
            resp = requests.get(query_url, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                commands = resp.json()
                if commands:
                    cmd = commands[0]
                    cmd_id = cmd.get("id")
                    comando = cmd.get("comando")
                    
                    logger.info(f"[REMOTE] Comando recibido: {comando} (ID: {cmd_id})")
                    
                    # 2. Marcar como procesando de inmediato para evitar ejecuciones dobles
                    requests.patch(f"{url}?id=eq.{cmd_id}", json={"status": "procesando"}, headers=headers, timeout=5)
                    
                    # 3. Ejecutar la lógica correspondiente
                    success, message = _execute_sync_command(comando)
                    
                    # 4. Actualizar estado final
                    final_status = "completado" if success else "error"
                    requests.patch(f"{url}?id=eq.{cmd_id}", 
                                   json={"status": final_status, "mensaje": message}, 
                                   headers=headers, timeout=5)
                    
                    logger.info(f"[REMOTE] Comando {comando} finalizado como: {final_status}. {message}")
            
        except Exception as e:
            # No queremos que el listener muera por un error de red
            print(f"[REMOTE] Error de conexión o proceso: {e}")
            
        time.sleep(10)

def _execute_sync_command(comando):
    """Ejecuta los comandos de sincronización llamando a la API local."""
    try:
        # El backend Flask corre localmente en el puerto 5000
        base_api = "http://localhost:5000/api/v1/sync"
        
        if comando == "sync_all":
            # Ejecutamos ambos secuencialmente
            logger.info("[REMOTE] Iniciando sync_all (Inventario + Ventas)")
            inv_resp = requests.get(f"{base_api}/inventory", timeout=300)
            sales_resp = requests.get(f"{base_api}/sales", timeout=300)
            
            if inv_resp.status_code == 200 and sales_resp.status_code == 200:
                return True, "Sincronización total completada con éxito"
            return False, f"Fallo parcial: Inv({inv_resp.status_code}) Sales({sales_resp.status_code})"
            
        elif comando == "sync_inventory":
            resp = requests.get(f"{base_api}/inventory", timeout=300)
            return resp.status_code == 200, f"Sync inventario completado (HTTP {resp.status_code})"
            
        elif comando == "sync_sales":
            resp = requests.get(f"{base_api}/sales", timeout=300)
            return resp.status_code == 200, f"Sync ventas completado (HTTP {resp.status_code})"
            
        else:
            return False, f"Comando '{comando}' no reconocido por el backend"
            
    except Exception as e:
        logger.error(f"[REMOTE] Exception durante ejecución: {e}")
        return False, f"Excepción interna: {str(e)}"

if __name__ == "__main__":
    start_remote_listener()
