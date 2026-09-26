@echo off
setlocal
cd /d "%~dp0"
set "ESBUILD=frontend\node_modules\@esbuild\win32-x64\esbuild.exe"

if not exist "%ESBUILD%" goto no_builder

echo [UI] Building interface...
"%ESBUILD%" frontend\src\main.jsx --bundle --outfile=ui\react\app.js --minify --jsx=automatic --platform=browser --target=es2022 --legal-comments=eof
if errorlevel 1 goto build_failed

echo [UI] Interface updated.
endlocal
exit /b 0

:no_builder
echo [UI] esbuild.exe not found. Using bundled interface.
endlocal
exit /b 0

:build_failed
echo [UI] Interface build failed.
endlocal
exit /b 1
