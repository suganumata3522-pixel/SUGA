@echo off
REM ===================================================================
REM  SUGA.exe build script  (ASCII only to avoid encoding issues)
REM  Requires: Python 3.11+ and Node.js 20+
REM ===================================================================
setlocal
cd /d "%~dp0.."
echo.
echo ====== SUGA.exe build start ======
echo.

REM --- Find a working Python command (python or py) ---
set PYEXE=
echo [check] Trying "python" ...
python --version
if not errorlevel 1 set PYEXE=python
if not defined PYEXE (
  echo [check] "python" not usable. Trying "py" ...
  py --version
  if not errorlevel 1 set PYEXE=py
)
if not defined PYEXE goto err_python
echo [check] Using Python command: %PYEXE%
echo.

echo [check] Node.js version:
node --version
if errorlevel 1 goto err_node
echo.

echo [1/4] Building frontend ...
cd frontend
call npm install
if errorlevel 1 goto err_npm_install
call npm run build
if errorlevel 1 goto err_npm_build
cd ..
echo.

echo [2/4] Copying frontend to backend\app\static ...
if exist backend\app\static rmdir /s /q backend\app\static
xcopy /e /i /q frontend\dist backend\app\static
if errorlevel 1 goto err_copy
echo.

echo [3/4] Installing Python deps and PyInstaller ...
cd backend
%PYEXE% -m pip install -e .
if errorlevel 1 goto err_pip
%PYEXE% -m pip install pyinstaller
if errorlevel 1 goto err_pyinstaller_install
echo.

echo [4/4] Building SUGA.exe with PyInstaller ...
%PYEXE% -m PyInstaller suga.spec --noconfirm --clean
if errorlevel 1 goto err_pyinstaller_build
cd ..
echo.

if not exist backend\dist\SUGA.exe goto err_no_exe

echo ===================================================================
echo  SUCCESS: backend\dist\SUGA.exe was created.
echo  Close this window and double-click SUGA.exe to run.
echo ===================================================================
pause
exit /b 0

:err_python
echo.
echo [ERROR] Python is not usable from the command line.
echo.
echo   How to fix:
echo   1. Install Python 3.11 or newer from  https://www.python.org/downloads/
echo   2. On the FIRST screen of the installer, turn ON the checkbox
echo      "Add python.exe to PATH"  (it is at the bottom).
echo   3. Finish the install, then RESTART this computer.
echo   4. Run this build_exe.bat again.
echo.
goto end_error
:err_node
echo.
echo [ERROR] Node.js not found. Install Node.js 20+ from https://nodejs.org/
goto end_error
:err_npm_install
cd ..
echo [ERROR] npm install failed.
goto end_error
:err_npm_build
cd ..
echo [ERROR] npm run build failed.
goto end_error
:err_copy
echo [ERROR] Failed to copy frontend to backend\app\static.
goto end_error
:err_pip
cd ..
echo [ERROR] pip install -e . failed.
goto end_error
:err_pyinstaller_install
cd ..
echo [ERROR] pip install pyinstaller failed.
goto end_error
:err_pyinstaller_build
cd ..
echo [ERROR] PyInstaller build failed.
goto end_error
:err_no_exe
echo [ERROR] Build finished but backend\dist\SUGA.exe was not found.
goto end_error

:end_error
echo.
echo ===================================================================
echo  BUILD FAILED.
echo  Select all text in this window (right-click - Select All - Enter)
echo  and send it to the developer.
echo ===================================================================
pause
exit /b 1
