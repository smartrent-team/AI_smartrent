@echo off
title SmartRent AI Service
cd /d "%~dp0"

echo.
echo  ================================
echo   SmartRent AI Service
echo  ================================
echo.

:: Kich hoat venv
if not exist "venv\Scripts\activate.bat" (
    echo  [ERROR] Khong tim thay venv. Chay: python -m venv venv
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

:: Kiem tra uvicorn
where uvicorn >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Khong tim thay uvicorn. Chay: pip install -r requirements.txt
    pause
    exit /b 1
)

echo  Starting FastAPI on http://localhost:8000
echo  Docs: http://localhost:8000/docs
echo.

uvicorn main:app --host 0.0.0.0 --port 8000 --reload

pause
