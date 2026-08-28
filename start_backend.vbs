Set WshShell = CreateObject("WScript.Shell")

' 1. Limpiar procesos viejos (ignora errores si no existen)
WshShell.Run "cmd /c taskkill /F /IM pythonw.exe /T 2>nul", 0, True
WshShell.Run "cmd /c taskkill /F /IM python.exe /T 2>nul", 0, True

' 2. Iniciar la API Flask (Puerto 5000) en segundo plano
WshShell.Run "pythonw app.py", 0, False

' 3. Iniciar el Widget de Escritorio (Visible y con Icono en Tray)
WshShell.Run "pythonw widget.py", 0, False

' 4. Iniciar el Monitor de archivos (Real-time Sync)
WshShell.Run "pythonw monitor.py", 0, False

Set WshShell = Nothing

