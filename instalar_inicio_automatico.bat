@echo off
set "SCRIPT_PATH=%~dp0start_backend.vbs"
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

echo Instalando inicio automatico para El Serrucho...

:: Crear un acceso directo en la carpeta Startup
powershell -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut('%STARTUP_FOLDER%\SerruchoBackend.lnk');$s.TargetPath='wscript.exe';$s.Arguments='\"%SCRIPT_PATH%\"';$s.WorkingDirectory='%~dp0';$s.Save()"

echo.
echo [OK] El servidor se iniciara automaticamente cada vez que enciendas esta PC.
echo [INFO] Para iniciar ahora mismo, ejecuta: start_backend.vbs
echo.
pause
