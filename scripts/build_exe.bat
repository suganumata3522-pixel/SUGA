@echo off
REM ===================================================================
REM  SUGA.exe ビルドスクリプト
REM  必要環境: Python 3.11+ / Node.js 20+
REM  途中でエラーが出たら、その時点で止まり原因を表示します。
REM ===================================================================
setlocal
cd /d "%~dp0.."
echo.
echo ====== SUGA.exe ビルド開始 ======
echo.

REM --- 前提チェック ---
echo [確認] Python ...
python --version
if errorlevel 1 (
  echo.
  echo [エラー] Python が見つかりません。Python 3.11+ をインストールし、
  echo          インストール時に「Add Python to PATH」にチェックしてください。
  goto error
)
echo [確認] Node.js ...
node --version
if errorlevel 1 (
  echo.
  echo [エラー] Node.js が見つかりません。Node.js 20+ をインストールしてください。
  goto error
)
echo.

echo [1/4] フロントエンドをビルド...
cd frontend
call npm install
if errorlevel 1 ( cd .. & echo [エラー] npm install に失敗 & goto error )
call npm run build
if errorlevel 1 ( cd .. & echo [エラー] npm run build に失敗 & goto error )
cd ..
echo.

echo [2/4] フロントを backend\app\static へ配置...
if exist backend\app\static rmdir /s /q backend\app\static
xcopy /e /i /q frontend\dist backend\app\static
if errorlevel 1 ( echo [エラー] フロントの配置に失敗 & goto error )
echo.

echo [3/4] Python 依存と PyInstaller をインストール...
cd backend
python -m pip install -e .
if errorlevel 1 ( cd .. & echo [エラー] pip install -e . に失敗 & goto error )
python -m pip install pyinstaller
if errorlevel 1 ( cd .. & echo [エラー] pyinstaller のインストールに失敗 & goto error )
echo.

echo [4/4] SUGA.exe をビルド...
REM pyinstaller コマンドが PATH に無くても動くよう python -m で呼ぶ
python -m PyInstaller suga.spec --noconfirm --clean
if errorlevel 1 ( cd .. & echo [エラー] PyInstaller のビルドに失敗 & goto error )
cd ..
echo.

if not exist backend\dist\SUGA.exe (
  echo [エラー] ビルドは進みましたが backend\dist\SUGA.exe が見つかりません。
  goto error
)

echo ===================================================================
echo  完了: backend\dist\SUGA.exe が生成されました
echo  このウィンドウを閉じて、SUGA.exe をダブルクリックしてください。
echo ===================================================================
pause
exit /b 0

:error
echo.
echo ===================================================================
echo  ビルドに失敗しました。
echo  この黒い画面の文字を全て選択してコピーし、開発担当へ送ってください。
echo  （ウィンドウ内で右クリック→すべて選択→Enter でコピーできます）
echo ===================================================================
pause
exit /b 1
