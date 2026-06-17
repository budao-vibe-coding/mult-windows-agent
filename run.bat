@echo off
title Windows Multi-Agent Desktop App Bootstrapper
echo =======================================================
echo     Windows Multi-Agent Desktop App Bootstrapper
echo =======================================================
echo.

:: 1. 检查 Python 安装状况
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not added to your PATH environment variable.
    echo Please install Python 3.10+ and check 'Add Python to PATH' during installation.
    pause
    exit /b 1
)

:: 2. 检测虚拟环境
if not exist .venv (
    echo [INFO] Creating Python Virtual Environment (.venv)...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: 3. 激活虚拟环境
echo [INFO] Activating virtual environment...
call .venv\Scripts\activate

:: 4. 安装/检查依赖项
echo [INFO] Checking & Installing project dependencies...
:: 如果用户环境需要开启代理，可在下面直接启用代理或在 cmd 预先配置
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [WARNING] Dependency installation finished with some warnings. Proceeding...
)

:: 5. 启动程序
echo [INFO] Starting Windows Multi-Agent Application...
python app\gui.py
if %errorlevel% neq 0 (
    echo [ERROR] Application exited with error code %errorlevel%.
)

pause
