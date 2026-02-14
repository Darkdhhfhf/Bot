@echo off
setlocal

REM Build a portable Windows console app using PyInstaller.

if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

REM Create a single-folder build for better antivirus compatibility.
pyinstaller --name BotSender --console --onefile app.py

echo.
echo Build complete. See dist\BotSender.exe
endlocal
