@echo off
setlocal

if not exist venv\Scripts\activate.bat (
    echo ERROR: venv not found. Activate or recreate it first.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat

if not exist jre7\jre\bin\java.exe (
    echo.
    echo ERROR: jre7\jre\bin\java.exe not found.
    echo Make sure jre7 is in place before building.
    pause
    exit /b 1
)

pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

echo Cleaning previous build artifacts...
if exist build rmdir /S /Q build
if exist dist rmdir /S /Q dist
if exist IPMILauncher.spec del /Q IPMILauncher.spec

echo Running PyInstaller (this takes a minute)...
pyinstaller --noconfirm --windowed --name IPMILauncher main.py
if errorlevel 1 (
    echo.
    echo Build FAILED.
    pause
    exit /b 1
)

echo Copying jre7 next to the .exe...
xcopy /E /I /Y /Q jre7 dist\IPMILauncher\jre7 >nul

echo.
echo ============================================================================
echo  Build complete.
echo  Portable app:  dist\IPMILauncher\IPMILauncher.exe
echo  Distribute:    zip up the entire dist\IPMILauncher\ folder.
echo ============================================================================
echo.
pause