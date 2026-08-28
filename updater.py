import requests
import os
import sys
import subprocess
import tkinter as tk
import custom_dialogs
import config
from version import VERSION
from logger import logger

def check_for_updates():
    """Verifica si hay una nueva versión disponible en Supabase."""
    try:
        url = f"{config.LICENSE_SUPABASE_URL}/rest/v1/app_versions?order=created_at.desc&limit=1"
        headers = {
            "apikey": config.LICENSE_SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {config.LICENSE_SUPABASE_ANON_KEY}"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                latest_version = data[0]['version_string']
                download_url = data[0]['download_url']
                
                if latest_version != VERSION:
                    logger.info(f"Nueva versión disponible: {latest_version} (Actual: {VERSION})")
                    return latest_version, download_url
        return None, None
    except Exception as e:
        logger.error(f"Error verificando actualizaciones: {e}")
        return None, None

def trigger_update(new_version, download_url):
    """Muestra un diálogo y gestiona la descarga/actualización."""
    root = tk.Tk()
    root.withdraw()
    
    msg = f"Hay una nueva versión disponible ({new_version}).\n\n¿Desea actualizar ahora?"
    if custom_dialogs.ask_yes_no("Actualización Disponible", msg):
        try:
            # En un entorno real, descargaríamos el instalador y lo ejecutaríamos
            # Aquí simulamos el inicio del proceso
            custom_dialogs.show_info("Actualizador", "Iniciando descarga de la actualización...")
            
            # Ejemplo de descarga y ejecución:
            # resp = requests.get(download_url)
            # with open("update_setup.exe", "wb") as f: f.write(resp.content)
            # subprocess.Popen(["update_setup.exe", "/SILENT"])
            # sys.exit(0)
            
            logger.info(f"Actualización a {new_version} aceptada por el usuario.")
            return True
        except Exception as e:
            logger.error(f"Error durante la actualización: {e}")
            custom_dialogs.show_error("Error", f"No se pudo completar la actualización: {e}")
    return False

if __name__ == "__main__":
    v, url = check_for_updates()
    if v:
        print(f"Update found: {v}")
    else:
        print("No updates found.")
