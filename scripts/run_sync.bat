@echo off
:: ============================================================
:: run_sync.bat — Sincronizador Hybrid on Cloud
:: Ejecuta sync.py una sola vez y muestra el resultado
:: ============================================================
title Hybrid on Cloud - Sincronizacion

echo.
echo ============================================================
echo   SINCRONIZADOR - Hybrid on Cloud
echo ============================================================
echo.

:: Cambiar al directorio del script
cd /d "%~dp0"

:: Verificar que Python esté disponible
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no encontrado en PATH.
    echo         Instalar Python o verificar la variable PATH.
    pause
    exit /b 1
)

echo [1] Ejecutando diagnostico de conexion...
python test_conexion.py
echo.

echo [2] Iniciando sincronizacion...
python sync.py once
echo.

echo ============================================================
echo   Sincronizacion completada. Presiona cualquier tecla.
echo ============================================================
pause
