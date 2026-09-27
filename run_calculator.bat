@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 -m sam_calculator %*) else (python -m sam_calculator %*)
if errorlevel 1 (
  echo.
  echo SAM Calculator stopped with an error ^(see above^). Is Python 3.9+ installed and on PATH?
  pause
)
