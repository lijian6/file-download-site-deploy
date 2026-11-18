@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
rem ---------------------------------------------------------------
rem Windows launcher for scan.py (Baota Windows panel / IIS / Nginx)
rem Usage:  scan.bat "C:\wwwroot\your-site"
rem It auto-detects Python: PATH > py launcher > Baota bundled Python.
rem Keep this file OUTSIDE the website root (e.g. C:\BtSoft\panel\).
rem ---------------------------------------------------------------

set "PYCMD="
where python >nul 2>&1 && set "PYCMD=python"
if not defined PYCMD (
    where py >nul 2>&1 && set "PYCMD=py -3"
)
if not defined PYCMD (
    if exist "C:\BtSoft\panel\python\python.exe" set PYCMD="C:\BtSoft\panel\python\python.exe"
)
if not defined PYCMD (
    if exist "C:\BtSoft\python\python.exe" set PYCMD="C:\BtSoft\python\python.exe"
)
rem Last resort: Baota Windows panel ships its own Python somewhere under C:\BtSoft
if not defined PYCMD (
    for /f "delims=" %%P in ('dir /s /b C:\BtSoft\python.exe 2^>nul') do (
        if not defined PYCMD set PYCMD="%%P"
    )
)
if not defined PYCMD (
    echo [ERROR] Python not found on this server.
    echo Try: 1^) install Python 3, or 2^) tell me the Baota bundled python.exe path.
    echo Diagnose: dir /s /b C:\BtSoft\*python.exe
    exit /b 1
)

set "SITE=%~1"
if "%SITE%"=="" (
    echo.
    echo Usage:  scan.bat "C:\wwwroot\your-site"
    echo Example: scan.bat "C:\wwwroot\files.tmp"
    echo.
    echo The site root is the folder that contains index.html.
    echo You can find it in Baota panel: Website -^> your site -^> Settings -^> Basic.
    exit /b 1
)

if not exist "%SITE%\index.html" (
    echo [WARN] "%SITE%\index.html" not found. Are you sure this is the site root?
)

echo [scan] Python : %PYCMD%
echo [scan] Site   : %SITE%
echo.
%PYCMD% "%~dp0scan.py" "%SITE%"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo [OK] list.json generated. Refresh the page with Ctrl+F5.
) else (
    echo [FAILED] exit code %RC%. Copy the messages above and send them back.
)
exit /b %RC%
