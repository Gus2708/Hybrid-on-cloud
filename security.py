import subprocess
import hashlib
import os
import sys
import tkinter as tk
import custom_dialogs
import requests
import config
from logger import logger

def get_hwid():
    """Retrieves a unique Hardware ID (UUID) from the Windows system."""
    try:
        cmd = 'wmic csproduct get uuid'
        uuid = subprocess.check_output(cmd, shell=True).decode().split('\n')[1].strip()
        return uuid
    except Exception as e:
        import socket
        return hashlib.sha256(socket.gethostname().encode()).hexdigest()[:32]

def validate_online(hwid, key):
    """Validates the license key against Supabase and returns license data."""
    try:
        url = f"{config.LICENSE_SUPABASE_URL}/rest/v1/licenses?hwid=eq.{hwid}&license_key=eq.{key}&active=eq.true"
        headers = {
            "apikey": config.LICENSE_SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {config.LICENSE_SUPABASE_ANON_KEY}"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if len(data) > 0:
                return data[0]
        return None
    except Exception as e:
        logger.error(f"Error en validación online: {e}")
        return None

def verify_license():
    """Checks if a valid license is present locally or online."""
    import json
    hwid = get_hwid()
    license_path = os.path.join(config.DATA_DIR, "license.json")
    logo_path = os.path.join(config.DATA_DIR, "client_logo.png")
    
    def apply_license_data(data):
        if data.get("business_name"):
            config.BUSINESS_NAME = data["business_name"]
            os.environ["BUSINESS_NAME"] = data["business_name"]

        # Asignación dinámica de la nube (API Cliente)
        if data.get("client_api_url"):
            url = data["client_api_url"].strip()
            config.SUPABASE_URL = url
            config.SUPABASE_REST_URL = url
            os.environ["SUPABASE_URL"] = url
            os.environ["SUPABASE_REST_URL"] = url
            
        if data.get("client_api_key"):
            key = data["client_api_key"].strip()
            config.SUPABASE_ANON_KEY = key
            os.environ["SUPABASE_ANON_KEY"] = key

        if os.path.exists(logo_path):
            config.BRAND_LOGO = logo_path
    
    # 1. Intento de validación local (Cache)
    if os.path.exists(license_path):
        try:
            with open(license_path, 'r') as f:
                data = json.load(f)
            
            # VALIDACIÓN CRÍTICA: ¿El HWID guardado coincide con esta máquina?
            if data.get("hwid") == hwid:
                apply_license_data(data)
                logger.info("Licencia validada localmente (HWID Match).")
                return True
            else:
                logger.warning(f"HWID mismatch: Guardado={data.get('hwid')}, Actual={hwid}. Re-validación requerida.")
        except Exception as e:
            logger.error(f"Error leyendo cache de licencia: {e}")
            pass

    # 2. Si no hay cache, pedir activación
    root = tk.Tk()
    root.withdraw()
    
    msg = f"Activación Requerida\n\nHardware ID: {hwid}\n\nContacte a soporte para su clave."
    custom_dialogs.show_warning("Activación", msg)
    
    user_key = custom_dialogs.ask_string("Activar Producto", "Ingrese su clave de activación:")
    
    if user_key:
        user_key = user_key.strip().upper()
        logger.info(f"Intentando activar con llave: {user_key}")
        
        license_data = validate_online(hwid, user_key)
        if license_data:
            # Descargar logo si existe
            if license_data.get("logo_url"):
                try:
                    img_data = requests.get(license_data["logo_url"], timeout=10).content
                    with open(logo_path, 'wb') as f:
                        f.write(img_data)
                except Exception as e:
                    logger.error(f"Error descargando logo: {e}")
            
            # Guardar JSON
            with open(license_path, 'w') as f:
                json.dump(license_data, f)
                
            apply_license_data(license_data)
            custom_dialogs.show_info("Éxito", "Producto activado online correctamente.")
            return True
        else:
            custom_dialogs.show_error("Error", "Clave inválida o no registrada para este equipo.")
            sys.exit(1)
    
    sys.exit(1)

if __name__ == "__main__":
    print(f"HWID: {get_hwid()}")
