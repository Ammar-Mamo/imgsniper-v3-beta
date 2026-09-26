@echo off
REM ===========================================================================
REM  ImgSniper v3 Beta - dependency installer
REM
REM  Installs ONLY the 5 packages the code actually imports (see requirements.txt).
REM  The previous version pulled torch/torchvision twice (~2.5 GB wasted: first as
REM  CUDA wheels from PyPI, then replaced by CPU wheels) plus easyocr -- all for
REM  OCR/vision features that are stubs in this project.
REM ===========================================================================
echo ========================================
echo    ImgSniper v3 Beta - Installation
echo ========================================
echo.

echo [1/2] Checking Python version...
python -c "import sys; sys.exit(0 if sys.version_info ^>= (3, 8) else 1)"
if errorlevel 1 (
    echo [ERROR] Python 3.8 or newer is required: https://python.org
    pause
    exit /b 1
)

echo [2/2] Installing dependencies...
pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo [ERROR] Installation failed. Try: python -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo.
echo Installation completed successfully.
echo.
echo To run the program:
echo    python main.py
echo.
pause
