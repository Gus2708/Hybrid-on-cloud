import threading
import time
import os
import sys
from pathlib import Path

# Detección de entorno congelado (Nuitka/PyInstaller)
IS_FROZEN = getattr(sys, 'frozen', False) or '__compiled__' in globals()

if IS_FROZEN:
    base_dir = Path(sys.executable).parent.absolute()
else:
    base_dir = Path(__file__).parent.absolute()

sys.path.insert(0, str(base_dir))
os.chdir(str(base_dir)) # Asegurar que el directorio de trabajo es el del ejecutable

from security import verify_license
from updater import check_for_updates, trigger_update

def run_api():
    from app import app, _init_tasa
    import os
    # Asegurarnos de que Flask no use el reloader si estamos en un hilo
    _init_tasa()
    port = int(os.environ.get("PORT", 5000))
    print(f"[LAUNCHER] Iniciando API en puerto {port}...")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def run_monitor():
    from monitor import start_monitor
    print("[LAUNCHER] Iniciando Monitor de archivos...")
    start_monitor()

def run_widget():
    import tkinter as tk
    from widget import HybridCloudWidget
    print("[LAUNCHER] Iniciando Interfaz Visual...")
    root = tk.Tk()
    app_ui = HybridCloudWidget(root)
    root.mainloop()

def run_remote_listener():
    from remote_listener import start_remote_listener
    print("[LAUNCHER] Iniciando Listener de Comandos Supabase...")
    start_remote_listener()

if __name__ == "__main__":
    # Verificar licencia antes de iniciar
    verify_license()
    
    # Verificar actualizaciones
    new_v, url = check_for_updates()
    if new_v:
        trigger_update(new_v, url)
    
    # Iniciar API en un hilo
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    
    # Iniciar Monitor en un hilo
    monitor_thread = threading.Thread(target=run_monitor, daemon=True)
    monitor_thread.start()

    # Iniciar Listener Remoto en un hilo
    remote_thread = threading.Thread(target=run_remote_listener, daemon=True)
    remote_thread.start()
    
    # Iniciar Widget en el hilo principal
    run_widget()
