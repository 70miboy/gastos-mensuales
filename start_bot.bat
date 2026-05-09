@echo off
cd /d "C:\Users\Tomi\Documents\GASTOS MENSUALES"

echo =========================================
echo   Bot de Gastos - Telegram
echo =========================================
echo.

REM Eliminar lockfile si existe de un cierre forzado
if exist telegram_bot.lock (
    echo 🧹 Limpiando lockfile anterior...
    del /f telegram_bot.lock 2>nul
    timeout /t 1 /nobreak >nul
)

REM Verificar si hay instancias previas y matarlas
echo 🔍 Verificando instancias previas...
taskkill /F /FI "WINDOWTITLE eq Bot de Gastos*" 2>nul
taskkill /F /IM python.exe /FI "STATUS eq RUNNING" 2>nul
timeout /t 2 /nobreak >nul

echo 🚀 Iniciando bot...
echo    Presiona Ctrl+C para detener
echo    No cierres con la X sin detener primero
echo.

REM Iniciar con título específico para poder identificar la ventana
title Bot de Gastos - Telegram
python telegram_bot.py

echo.
echo ⚠ El bot se detuvo.
pause
