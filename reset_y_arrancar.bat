@echo off
title El Serrucho - Reset y Arranque
echo ============================================================
echo   RESET COMPLETO - El Serrucho Backend
echo ============================================================
echo.
echo [1/3] Matando TODOS los procesos python de esta carpeta...
echo.
powershell -Command ^
  "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe'\" ^| Where-Object { $_.CommandLine -like '*backend serrucho*' } ^| ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Output (""Matado PID "" + $_.ProcessId) }"
echo.
echo [2/3] Limpiando archivos temporales y locks...
del /F /Q "C:\Proyect\backend serrucho\sync.lock" 2>nul
del /F /Q "C:\Proyect\backend serrucho\watchdog.lock" 2>nul
del /F /Q "C:\Proyect\backend serrucho\start_backend.lock" 2>nul
del /F /Q "C:\Proyect\backend serrucho\*.tmp" 2>nul
echo.
echo [3/3] Iniciando servicios...
wscript "C:\Proyect\backend serrucho\start_backend.vbs"
echo.
echo [OK] Servicios iniciados. El monitor debe aparecer en pantalla.
echo      Si aun ves congelamiento, ejecuta: taskkill /f /im pythonw.exe
echo.
pause
