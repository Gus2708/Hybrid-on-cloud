import os
import subprocess
import sys
import shutil

def build():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(base_dir)
    print("======================================================")
    print("INICIANDO COMPILACIÓN PROFESIONAL CON NUITKA")
    print("======================================================")
    
    # Asegurar que Nuitka esté instalado
    try:
        import nuitka
    except ImportError:
        print("[INFO] Instalando Nuitka y dependencias...")
        subprocess.run([sys.executable, "-m", "pip", "install", "nuitka", "zstandard"], check=True)

    # Limpiar compilaciones previas
    if os.path.exists("build_nuitka"): shutil.rmtree("build_nuitka")
    if os.path.exists("launcher.dist"): shutil.rmtree("launcher.dist")
    
    command = [
        sys.executable, "-m", "nuitka",
        "--onefile",
        "--windows-console-mode=disable",
        "--assume-yes-for-downloads",
        "--windows-icon-from-ico=assets/icon.ico",
        "--company-name=Hybrid to Cloud",
        "--product-name=Hybrid to Cloud",
        "--file-version=1.0.0.0",
        "--product-version=1.0.0.0",
        "--file-description=Hybrid to Cloud Client",
        "--copyright=Copyright © 2024 Hybrid to Cloud",
        "--include-data-dir=assets=assets",
        "--include-data-dir=sql=sql",
        "--plugin-enable=tk-inter",
        "--include-package=keyring",
        "--follow-imports",
        "--output-dir=build_nuitka",
        "launcher.py"
    ]
    
    print(f"[EXEC] {' '.join(command)}")
    
    try:
        subprocess.run(command, check=True)
        
        # Mover resultado a carpeta final
        dist_path = "dist/HybridToCloud_Nuitka"
        if os.path.exists(dist_path): shutil.rmtree(dist_path)
        os.makedirs("dist", exist_ok=True)
        
        # Nuitka pone el resultado en build_nuitka/launcher.dist
        src = os.path.join("build_nuitka", "launcher.dist")
        if os.path.exists(src):
            shutil.move(src, dist_path)
            
            # Renombrar ejecutable a HybridToCloud.exe
            old_exe = os.path.join(dist_path, "launcher.exe")
            new_exe = os.path.join(base_dir, "widget.exe")
            if os.path.exists(old_exe):
                if os.path.exists(new_exe): os.remove(new_exe)
                shutil.copy(old_exe, new_exe)
                
            print("\n" + "="*50)
            print("¡COMPILACIÓN NUITKA COMPLETADA!")
            print(f"Ubicación: {new_exe}")
            print("="*50)
            print("\nNOTA: Nuitka es mucho más seguro y rápido que PyInstaller.")
            print("Ahora use este ejecutable en su script de Inno Setup.")
        else:
            print("[ERROR] No se encontró la carpeta de salida de Nuitka.")
            
    except subprocess.CalledProcessError as e:
        print(f"Error durante la compilación con Nuitka: {e}")

if __name__ == "__main__":
    build()
