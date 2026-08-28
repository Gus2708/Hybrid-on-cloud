import os
import subprocess
import sys

def build():
    print("Iniciando proceso de empaquetado profesional...")
    
    # Comandos de PyInstaller
    # --noconsole: No mostrar ventana de comandos
    # --icon: Usar el icono generado
    # --name: Nombre del ejecutable
    # --add-data: Incluir carpetas necesarias (Sintaxis: origen;destino)
    # --clean: Limpiar cache de pyinstaller
    
    command = [
        "python", "-m", "PyInstaller",
        "--noconsole",
        "--icon=assets/icon.ico",
        "--name=HybridToCloud",
        "--add-data=assets;assets",
        "--add-data=sql;sql",
        "--add-data=.env.example;.",
        "--clean",
        "--noconfirm",
        "launcher.py"
    ]
    
    try:
        # Limpiar carpetas de compilación previa
        import shutil
        if os.path.exists("build"): shutil.rmtree("build")
        if os.path.exists("dist/HybridToCloud"): shutil.rmtree("dist/HybridToCloud")
        
        subprocess.run(command, check=True)
        
        print("\n" + "="*50)
        print("¡EMPAQUETADO BINARIO COMPLETADO!")
        print("Ubicación: dist/HybridToCloud/HybridToCloud.exe")
        print("="*50)
        print("\nPASO SIGUIENTE: Crear el Instalador Profesional")
        print("1. Instale Inno Setup (https://jrsoftware.org/isdl.php)")
        print("2. Abra el archivo 'installer.iss' en Inno Setup")
        print("3. Presione 'Compile' (F9) para generar el instalador final.")
        print("="*50)
        
    except subprocess.CalledProcessError as e:
        print(f"Error durante el empaquetado: {e}")

if __name__ == "__main__":
    build()
