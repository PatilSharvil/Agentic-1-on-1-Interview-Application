@echo off
title Interview App - Demo Launcher
echo ============================================
echo   Interview Application - Demo Launcher
echo ============================================
echo.

set "ROOT=%~dp0"
set "BIN=%ROOT%bin"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"

:: Free ports 8000 and 5173
echo [1/4] Freeing ports 8000 and 5173...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173') do taskkill /PID %%a /F >nul 2>&1
timeout /t 2 /nobreak >nul

:: Start backend
echo [2/4] Starting backend (port 8000)...
start "Backend" /min cmd /c "cd /d "%BACKEND%" && python -m uvicorn app.main:app --port 8000"
timeout /t 5 /nobreak >nul

:: Start frontend
echo [3/4] Starting frontend (port 5173)...
start "Frontend" /min cmd /c "cd /d "%FRONTEND%" && npm run dev"
timeout /t 8 /nobreak >nul

:: Start cloudflared tunnel
echo [4/4] Starting Cloudflare Tunnel...
echo.
echo ============================================
echo   Public URL will appear below.
echo   Share this URL with your demo audience.
echo   Press Ctrl+C to stop the tunnel.
echo ============================================
echo.
"%BIN%\cloudflared.exe" tunnel --url http://localhost:5173

:: Cleanup on exit
echo.
echo Stopping backend and frontend...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173') do taskkill /PID %%a /F >nul 2>&1
echo Done.
pause