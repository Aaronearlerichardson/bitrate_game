@echo off
REM Launches the prebuilt Hex-o-Spell binary for native Windows.
REM Mirrors run.sh: detects arch, execs dist\bitrate_game-windows-<arch>.exe.
REM Does NOT create a venv. Build the binary with: python scripts\build.py

setlocal
cd /d "%~dp0"

REM --- Detect arch ---
set "ARCH=x86_64"
if /I "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "ARCH=arm64"
if /I "%PROCESSOR_ARCHITEW6432%"=="ARM64" set "ARCH=arm64"

set "EXE_NAME=bitrate_game-windows-%ARCH%.exe"
set "ONEFILE=dist\%EXE_NAME%"
set "BUNDLE=dist\bitrate_game-windows-%ARCH%\%EXE_NAME%"

if exist "%ONEFILE%" (
    set "EXE=%ONEFILE%"
) else if exist "%BUNDLE%" (
    set "EXE=%BUNDLE%"
) else (
    echo No prebuilt binary for windows-%ARCH%.
    echo Expected one of:
    echo   %ONEFILE%
    echo   %BUNDLE%
    echo Build it first:
    echo   python scripts\build.py
    exit /b 1
)

"%EXE%" %*
endlocal
