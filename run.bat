@echo off
REM Launches the Hex-o-Spell bit-rate game on native Windows.
REM Mirrors run.sh: creates a venv, installs deps, runs the game.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv || python -m venv .venv
)

set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip install --quiet --upgrade pip
"%PY%" -m pip install --quiet -r envs\requirements.txt

set "PYTHONPATH=src"
"%PY%" -m bitrate_game.main %*
endlocal
