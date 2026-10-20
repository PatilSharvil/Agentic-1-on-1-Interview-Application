@echo off
title Install Cloudflared
echo ============================================
echo   Cloudflared Installer
echo ============================================
echo.

set "ROOT=%~dp0"
set "BIN=%ROOT%bin"
set "EXE=%BIN%\cloudflared.exe"

if exist "%EXE%" (
    echo Cloudflared is already installed at: %EXE%
    "%EXE%" --version
    echo.
    echo Nothing to do.
    pause
    exit /b 0
)

echo Cloudflared not found. Downloading...
echo.

:: Create bin folder
if not exist "%BIN%" mkdir "%BIN%"

:: Download from GitHub releases (Windows amd64)
set "URL=https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
echo Downloading from: %URL%
echo This may take a minute...
echo.

curl -L -o "%EXE%" "%URL%"

if exist "%EXE%" (
    echo.
    echo Download complete!
    "%EXE%" --version
    echo.
    echo Cloudflared installed successfully at: %EXE%
) else (
    echo.
    echo ERROR: Download failed. Please download manually from:
    echo https://github.com/cloudflare/cloudflared/releases
    echo and place cloudflared.exe in the bin\ folder.
)

pause