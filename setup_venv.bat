@echo off
echo ========================================
echo Automatic Virtual Environment Setup
echo ========================================

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python and try again
    pause
    exit /b 1
)

echo.
echo Step 1: Checking for existing virtual environment...
if exist "venv" (
    echo ✓ Found existing venv directory - using it
    goto :activate_venv
) else (
    echo Creating new virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
    echo ✓ Virtual environment created successfully
)

:activate_venv
echo.
echo Step 2: Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /b 1
)
echo ✓ Virtual environment activated

echo.
echo Step 3: Upgrading pip, setuptools, and wheel...
python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo WARNING: Failed to upgrade pip tools, continuing anyway...
)

echo.
echo Step 4: Installing PyTorch with CUDA support...
pip install torch==2.7.1+cu118 torchvision==0.22.1+cu118 torchaudio==2.7.1+cu118 --index-url https://download.pytorch.org/whl/cu118
if errorlevel 1 (
    echo.
    echo WARNING: PyTorch CUDA installation failed, trying CPU version...
    pip install torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1
    if errorlevel 1 (
        echo.
        echo ERROR: Failed to install PyTorch
        pause
        exit /b 1
    )
)

echo.
echo Step 5: Installing other dependencies with wheel preference...
pip install --prefer-binary -r requirements.txt
if errorlevel 1 (
    echo.
    echo WARNING: Some dependencies failed to install
    echo Trying alternative installation method...
    pip install --prefer-binary -r requirements.txt -i https://pypi.org/simple
    if errorlevel 1 (
        echo.
        echo ERROR: Failed to install dependencies
        echo You may need to install Python 3.11 for better compatibility
        echo Or install missing build tools (Rust, Visual Studio Build Tools)
        pause
        exit /b 1
    )
)

echo.
echo ========================================
echo Setup Complete!
echo ========================================
echo.
echo To activate this environment in the future:
echo   venv\Scripts\activate
echo.
echo To deactivate:
echo   deactivate
echo.
pause
