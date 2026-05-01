@echo off
setlocal

echo ============================================================
echo  IPMI Launcher - Build Script
echo ============================================================
echo.

:: --- Python check ---
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.11+ and make sure it is on your PATH.
    pause
    exit /b 1
)

:: --- venv setup ---
if not exist venv\Scripts\activate.bat (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)
call venv\Scripts\activate.bat

:: --- Install dependencies ---
echo Installing dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)

:: --- JRE check / auto-detect ---
if not exist jre7\jre\bin\java.exe (
    echo jre7\ not found, looking for Oracle JDK 7u80 installation...
    set JDK_DEFAULT=C:\Program Files\Java\jdk1.7.0_80
    if exist "%JDK_DEFAULT%\jre\bin\java.exe" (
        echo Found JDK at %JDK_DEFAULT%, copying to jre7\...
        xcopy /E /I /Y /Q "%JDK_DEFAULT%" jre7 >nul
        echo Done.
    ) else (
        echo.
        echo ERROR: jre7\ not found and JDK 7u80 not detected at default path.
        echo.
        echo Please do one of the following:
        echo   1. Install JDK 7u80 from:
        echo      https://www.oracle.com/java/technologies/javase/javase7-archive-downloads.html
        echo      Then re-run this script - it will copy it automatically.
        echo.
        echo   2. Manually copy your JDK 7u80 folder next to this script and rename it jre7\
        echo      so that jre7\jre\bin\java.exe exists.
        echo.
        pause
        exit /b 1
    )
)

:: --- Clean previous build ---
echo Cleaning previous build...
if exist build rmdir /S /Q build
if exist dist rmdir /S /Q dist
if exist IPMILauncher.spec del /Q IPMILauncher.spec

:: --- PyInstaller ---
echo Building executable (this takes a minute)...
pyinstaller --noconfirm --windowed --name IPMILauncher main.py
if errorlevel 1 (
    echo.
    echo ERROR: Build failed.
    pause
    exit /b 1
)

:: --- Copy JRE ---
echo Copying jre7 into dist...
xcopy /E /I /Y /Q jre7 dist\IPMILauncher\jre7 >nul

echo.
echo ============================================================
echo  Build complete!
echo.
echo  Executable:  dist\IPMILauncher\IPMILauncher.exe
echo.
echo  To create a release zip:
echo    1. Delete dist\IPMILauncher\jre7\ (cannot redistribute JDK)
echo    2. Zip the dist\IPMILauncher\ folder
echo    3. Upload to GitHub Releases
echo    4. Users place their own jre7\ folder inside before running
echo ============================================================
echo.
pause
