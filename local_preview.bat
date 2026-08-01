@echo off
REM Local dashboard preview - serves this folder at http://localhost:8000
REM Needed while GitHub Pages is unavailable. Close this window to stop.
cd /d "%~dp0"
set PY=C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PY%" (
  echo [ERROR] Python not found at %PY%
  pause
  exit /b 1
)
echo Starting local server on http://localhost:8000 ...
start "" http://localhost:8000/index.html
"%PY%" -m http.server 8000
echo.
echo [server stopped] press any key to close.
pause >nul
