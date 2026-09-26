#!/bin/bash

# ImgSniper - Advanced Image Processing Tool
# أداة معالجة الصور المتقدمة

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "========================================"
echo "  🖼️  ImgSniper - Image Processing Tool"
echo "  أداة معالجة الصور المتقدمة"
echo "========================================"
echo -e "${NC}"

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    if ! command -v python &> /dev/null; then
        echo -e "${RED}❌ Python غير مثبت على النظام${NC}"
        echo "يرجى تثبيت Python 3.8 أو أحدث من: https://python.org"
        exit 1
    else
        PYTHON_CMD="python"
    fi
else
    PYTHON_CMD="python3"
fi

# Check Python version
PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
echo -e "${GREEN}✅ Python $PYTHON_VERSION مثبت${NC}"

# Check if pip is available
if ! command -v pip3 &> /dev/null; then
    if ! command -v pip &> /dev/null; then
        echo -e "${RED}❌ pip غير متوفر${NC}"
        exit 1
    else
        PIP_CMD="pip"
    fi
else
    PIP_CMD="pip3"
fi

# Check if required packages are installed
echo -e "${YELLOW}🔍 فحص المكتبات المطلوبة...${NC}"
$PYTHON_CMD -c "import rich, PIL, imagehash" 2>/dev/null
if [ $? -ne 0 ]; then
    echo -e "${YELLOW}📦 تثبيت المكتبات المطلوبة...${NC}"
    $PIP_CMD install -r ../requirements.txt
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ فشل في تثبيت المكتبات${NC}"
        echo "يرجى تشغيل: $PIP_CMD install -r requirements.txt"
        exit 1
    fi
fi

echo -e "${GREEN}✅ جميع المكتبات مثبتة بنجاح${NC}"
echo
echo -e "${BLUE}🚀 تشغيل ImgSniper...${NC}"
echo

# Make sure the script has execute permissions
chmod +x "$0"

# Run the main application
cd ..
$PYTHON_CMD main.py

echo
echo -e "${GREEN}👋 شكراً لاستخدام ImgSniper${NC}"