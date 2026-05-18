@echo off
REM ============================================
REM   Cline OS Command Center V2.0 Launcher
REM   桌面快捷方式入口点
REM ============================================

cd /d "%~dp0"

echo ============================================
echo   Cline OS Command Center V2.0
echo   Starting...
echo ============================================

REM 检测 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+.
    pause
    exit /b 1
)

REM 创建虚拟环境（如不存在）
if not exist "projects\command_center\venv" (
    echo [INFO] Creating virtual environment...
    python -m venv projects\command_center\venv
    call projects\command_center\venv\Scripts\activate.bat
    echo [INFO] Installing dependencies...
    pip install -r projects\command_center\requirements.txt
    pip install python-dotenv pdfplumber 2>nul
) else (
    call projects\command_center\venv\Scripts\activate.bat
)

echo [INFO] Starting Command Center...
python -m projects.command_center.app

if errorlevel 1 (
    echo.
    echo [ERROR] Application crashed. Check logs above.
    pause
)

call deactivate