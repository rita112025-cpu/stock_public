@echo off
REM 台股資料抓取 GUI 啟動器
REM 本檔僅含 ASCII，避免 cmd.exe 以 Big5 讀取 UTF-8 中文而出錯。
REM 所有中文介面都在 run_gui.py，Python 以 UTF-8 讀取，不受影響。

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo Install Python from python.org and tick "Add Python to PATH".
    pause
    exit /b 1
)

python "%~dp0run_gui.py"
if errorlevel 1 (
    echo.
    echo [ERROR] GUI exited with an error. See the message above.
    pause
)
