@echo off
REM Windows 上で SUGA.exe を作成するワンタイムビルドスクリプト。
REM 必要環境: Python 3.11+ / Node.js 20+ がインストール済みであること。
cd /d "%~dp0.."

echo [1/4] フロントエンドをビルド...
cd frontend
call npm install
call npm run build
cd ..

echo [2/4] フロントを backend\app\static へ配置...
if exist backend\app\static rmdir /s /q backend\app\static
xcopy /e /i /q frontend\dist backend\app\static

echo [3/4] Python 依存と PyInstaller をインストール...
cd backend
python -m pip install -e .
python -m pip install pyinstaller

echo [4/4] SUGA.exe をビルド...
pyinstaller suga.spec

echo.
echo 完了: backend\dist\SUGA.exe が生成されました
echo この exe を配布してください（ダブルクリックで起動します）
pause
