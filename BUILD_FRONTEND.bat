@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "FRONTEND_DIR=%ROOT_DIR%declarator-lm"

if not exist "%FRONTEND_DIR%\package.json" (
  echo [ERROR] package.json not found in "%FRONTEND_DIR%"
  exit /b 1
)

pushd "%FRONTEND_DIR%" >nul
echo Building frontend...
npm run build
set "EXIT_CODE=%ERRORLEVEL%"
popd >nul

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] Build failed with exit code %EXIT_CODE%.
  exit /b %EXIT_CODE%
)

echo.
echo [OK] Frontend build complete.
exit /b 0
