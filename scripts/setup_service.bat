@echo off
setlocal enabledelayedexpansion

echo ======================================================
echo CONFIGURADOR DE SERVICIO - HYBRID ON CLOUD
echo ======================================================

set SERVICE_NAME=HybridToCloudAPI
set APP_DIR=%~dp0
set APP_EXE=%APP_DIR%dist\HybridToCloud\HybridToCloud.exe
set NSSM_EXE=%APP_DIR%assets\nssm.exe

if not exist "%APP_EXE%" (
    echo [ERROR] No se encuentra el ejecutable en %APP_EXE%
    echo Primero debe ejecutar build_app.py
    pause
    exit /b 1
)

if not exist "%NSSM_EXE%" (
    echo [INFO] Descargando NSSM...
    powershell -Command "Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' -OutFile 'nssm.zip'"
    powershell -Command "Expand-Archive -Path 'nssm.zip' -DestinationPath 'nssm_temp' -Force"
    copy "nssm_temp\nssm-2.24\win64\nssm.exe" "%NSSM_EXE%"
    del nssm.zip
    rmdir /s /q nssm_temp
)

echo [INFO] Instalando servicio %SERVICE_NAME%...
"%NSSM_EXE%" install %SERVICE_NAME% "%APP_EXE%"
"%NSSM_EXE%" set %SERVICE_NAME% AppDirectory "%APP_DIR%dist\HybridToCloud"
"%NSSM_EXE%" set %SERVICE_NAME% Description "Backend API para Hybrid to Cloud"
"%NSSM_EXE%" set %SERVICE_NAME% Start SERVICE_AUTO_START

echo [INFO] Iniciando servicio...
"%NSSM_EXE%" start %SERVICE_NAME%

echo [OK] Servicio configurado y ejecutandose.
pause
