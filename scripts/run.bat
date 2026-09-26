@echo off
chcp 65001 > nul
title ImgSniper - Advanced Image Processing Tool

echo.
echo ========================================
echo   🖼️  ImgSniper - Image Processing Tool
echo   Advanced Image Processing Tool
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python is not installed on your system
    echo please install python 3.8 or newr : https://python.org
    pause
    exit /b 1
)

REM Check if required packages are installed
echo 🔍 Checking the required libraries...
python -c "import rich, PIL, imagehash" >nul 2>&1
if errorlevel 1 (
    echo 📦 Install the required libraries...
    pip install -r ../requirements.txt
    if errorlevel 1 (
        echo ❌ Failed to install libraries
        echo please run : pip install -r requirements.txt
        pause
        exit /b 1
    )
)

echo ✅ All libraries installed successfully
echo.
echo 🚀 runnig ImgSniper...
echo.

REM Run the main application
cd ..
python main.py

echo.
echo 👋 thank you for using ImgSniper
pause