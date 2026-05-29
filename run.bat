@echo off
cd /d "%~dp0"
echo === Cotizador SGI - Letras y Anuncios ===
echo.

:: Cerrar servidor anterior en puerto 8080
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8080 " ^| findstr "LISTENING"') do (
    echo Cerrando proceso anterior en puerto 8080...
    taskkill /PID %%a /F >nul 2>&1
)

:: Activar entorno virtual si existe
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

:: Verificar dependencias
python -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Faltan dependencias de Python. Ejecuta:
    echo   pip install fastapi uvicorn python-multipart svgpathtools reportlab numpy
    echo.
    pause
    exit /b 1
)

:: Abrir el navegador despues de 5 segundos (en segundo plano)
start "" cmd /c "timeout /t 5 /nobreak >nul && start """" http://localhost:8080"

echo Servidor iniciando en http://localhost:8080
echo Presiona Ctrl+C para detener el servidor.
echo.
python -m uvicorn main:app --host 0.0.0.0 --port 8080
pause
