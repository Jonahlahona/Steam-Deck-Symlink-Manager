#!/bin/bash
# --- WSL Compilation Script for Steam Deck Symlink Manager ---
set -e

echo "=========================================================="
echo "      Steam Deck Symlink Manager - WSL Linux Builder"
echo "=========================================================="
echo ""

# 1. Check if running in Linux/WSL
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    echo "ERROR: This script must be run inside your WSL Linux terminal!"
    echo "Please open WSL (e.g., Ubuntu) and run: ./build.sh"
    exit 1
fi

# 2. Install Ubuntu/Debian system dependencies (pip, venv, TK engine)
echo "[1/4] Checking and installing Linux system dependencies..."
echo "This may request your WSL sudo password to install python3-venv and python3-tk..."
# sudo apt-get update -y
# sudo apt-get install -y python3 python3-pip python3-venv python3-tk

# 3. Create isolated python virtual environment
echo ""
echo "[2/4] Setting up clean virtual compilation environment..."
if [ -d "build_venv" ]; then
    echo "Existing virtual environment found. Refreshing..."
    rm -rf build_venv
fi
python3 -m venv build_venv
source build_venv/bin/activate

# 4. Install compilation packages
echo ""
echo "[3/4] Fetching Python modules (customtkinter & pyinstaller) inside virtual environment..."
pip install --upgrade pip
pip install customtkinter pyinstaller pillow

# 5. Compile binary using PyInstaller
echo ""
echo "[4/4] Starting compilation with PyInstaller (Packaging TK/TCL and CustomTkinter resources)..."

# Detect Python version to find site-packages directory path inside venv
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
CTK_DIR="build_venv/lib/python${PYTHON_VERSION}/site-packages/customtkinter"

if [ ! -d "$CTK_DIR" ]; then
    echo "ERROR: CustomTkinter directory not found at $CTK_DIR"
    exit 1
fi

echo "Found CustomTkinter at: $CTK_DIR"
echo "Running PyInstaller compiler..."

pyinstaller --onefile --noconsole \
    --name="Steam-Deck-Symlink-Manager" \
    --add-data "${CTK_DIR}:customtkinter" \
    --add-data "assets/icon_small.png:assets" \
    --add-data "assets/icon_large.png:assets" \
    --hidden-import PIL \
    --hidden-import PIL._tkinter_finder \
    src/main.py

echo ""
echo "=========================================================="
echo "                 BUILD COMPLETE SUCCESS!"
echo "=========================================================="
echo "Your standalone Linux executable is located at:"
echo "👉 dist/Steam-Deck-Symlink-Manager"
echo ""
echo "To deploy to your Steam Deck:"
echo "1. Copy 'dist/Steam-Deck-Symlink-Manager' to your Steam Deck"
echo "   (using USB, Warpinator, SSH, or OneDrive)."
echo "2. On your Steam Deck, switch to Desktop Mode."
echo "3. Double-click the file to open and enjoy the Steam Deck symlink manager!"
echo "=========================================================="
