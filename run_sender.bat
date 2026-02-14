@echo off
setlocal

REM Run from source (requires venv and dependencies).

if not exist .venv (
  echo Virtual environment not found. Run build_windows.bat first or create venv.
  exit /b 1
)

call .venv\Scripts\activate.bat

if not exist message.txt (
  echo Create message.txt with your message text.
  echo Example: Hello, world!> message.txt
)

python app.py --text-file message.txt

endlocal
