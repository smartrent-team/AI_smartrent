#!/bin/bash

# Di chuyen vao thu muc chua script nay
cd "$(dirname "$0")"

echo ""
echo " ================================"
echo "  SmartRent AI Service"
echo " ================================"
echo ""

# Kiem tra venv
if [ ! -f "venv/bin/activate" ]; then
    echo " [ERROR] Khong tim thay venv. Chay: python3 -m venv venv"
    exit 1
fi

# Kich hoat venv
source venv/bin/activate

# Kiem tra uvicorn
if ! command -v uvicorn &> /dev/null; then
    echo " [ERROR] Khong tim thay uvicorn. Chay: pip install -r requirements.txt"
    exit 1
fi

echo " Starting FastAPI on http://localhost:8000"
echo " Docs: http://localhost:8000/docs"
echo ""

uvicorn main:app --host 0.0.0.0 --port 8000 --reload
