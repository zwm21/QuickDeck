@echo off
setlocal
chcp 65001 >nul

echo =========================================
echo   QuickDeck Build Script
echo =========================================
echo.

REM ---- Check python ----
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found in PATH.
    echo Please install Python 3.x and add it to PATH.
    goto :fail
)

REM ---- Ensure dependencies ----
echo [1/4] Checking dependencies...

python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo    Installing PyInstaller ...
    python -m pip install pyinstaller
    if errorlevel 1 goto :fail
)

python -m pip show pywin32 >nul 2>&1
if errorlevel 1 (
    echo    Installing pywin32 ...
    python -m pip install pywin32
    if errorlevel 1 goto :fail
)

python -m pip show Pillow >nul 2>&1
if errorlevel 1 (
    echo    Installing Pillow ...
    python -m pip install Pillow
    if errorlevel 1 goto :fail
)

REM ---- Clean previous build output ----
echo [2/4] Cleaning old build output ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist QuickDeck.spec del /q QuickDeck.spec

REM ---- Verify font file ----
if not exist "HYWenHei-65W.ttf" (
    echo [ERROR] HYWenHei-65W.ttf not found in current directory.
    goto :fail
)

REM ---- Run PyInstaller (single line, no caret line-continuation) ----
echo [3/4] Packaging ... this may take 1-3 minutes.
python -m PyInstaller --noconfirm --clean --onefile --windowed --name QuickDeck --add-data "HYWenHei-65W.ttf;." --hidden-import win32com --hidden-import win32com.client --hidden-import win32gui --hidden-import win32ui --hidden-import win32con main.py
if errorlevel 1 goto :fail

REM ---- Done ----
echo [4/4] Done.
echo.
if exist "dist\QuickDeck.exe" (
    echo Output: %CD%\dist\QuickDeck.exe
) else (
    echo [WARN] dist\QuickDeck.exe not found. Check the log above.
)

REM ---- Remove intermediate build folder ----
if exist build (
    echo Removing build folder ...
    rmdir /s /q build
)

echo.
pause
endlocal
exit /b 0

:fail
echo.
echo *** Build failed. Check the messages above. ***
echo.
pause
endlocal
exit /b 1
