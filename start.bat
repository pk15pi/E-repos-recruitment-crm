@echo off
setlocal
cd /d "%~dp0"
title Sable launcher

echo ======================================
echo  Starting Sable recruitment CRM
echo ======================================
echo.

netstat -ano | findstr /C:":43123 " | findstr /C:"LISTENING" >nul
if not errorlevel 1 (
  echo [error] Port 43123 is already in use.
  echo Close the previous "Sable UI" window, then run this file again.
  pause
  exit /b 1
)
netstat -ano | findstr /C:":43124 " | findstr /C:"LISTENING" >nul
if not errorlevel 1 (
  echo [error] Port 43124 is already in use.
  echo Close the previous "Sable API" window, then run this file again.
  pause
  exit /b 1
)

if not exist ".env" (
  if exist ".env.example" (
    copy ".env.example" ".env" >nul
    echo [setup] Created .env from .env.example
  ) else (
    echo [error] Missing .env and .env.example
    pause
    exit /b 1
  )
)

if not exist "be\.venv\Scripts\python.exe" (
  echo [error] Backend virtualenv not found at be\.venv
  echo Create it with:
  echo   cd be
  echo   python -m venv .venv
  echo   .venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
  pause
  exit /b 1
)

if not exist "fe\node_modules" (
  echo [setup] Installing frontend dependencies...
  pushd "fe"
  call npm install
  if errorlevel 1 (
    popd
    echo [error] npm install failed.
    pause
    exit /b 1
  )
  popd
)

set "storage_services="
findstr /B /I /C:"STORAGE_BACKEND=minio" ".env" >nul 2>&1
if not errorlevel 1 set "storage_services= minio"
if not defined storage_services (
  findstr /B /I /C:"STORAGE_BACKEND=s3" ".env" >nul 2>&1
  if not errorlevel 1 set "storage_services= minio"
)

where docker >nul 2>&1
if not errorlevel 1 (
  docker compose up -d postgres redis%storage_services% >nul 2>&1
  if errorlevel 1 (
    echo [warn] Could not start Postgres/Redis with docker compose. Start them manually.
  ) else (
    echo [ok] Postgres and Redis are running.
    if defined storage_services echo [ok] MinIO console http://127.0.0.1:9001
    ping -n 5 127.0.0.1 >nul
  )
) else (
  echo [warn] Docker not found. Make sure Postgres and Redis are running.
  if defined storage_services echo [warn] MinIO is selected in .env but Docker is unavailable.
)

echo [setup] Applying database migrations...
pushd "be"
".venv\Scripts\python.exe" manage.py migrate --noinput >"%TEMP%\sable-migrate.log" 2>&1
if errorlevel 1 (
  type "%TEMP%\sable-migrate.log"
  echo [error] Migrations failed. Check DATABASE_URL in .env and that Postgres is running.
  popd
  pause
  exit /b 1
)
popd

echo.
echo [start] API     http://127.0.0.1:43124
echo [start] Worker  Celery
echo [start] UI      http://127.0.0.1:43123
echo.

start "Sable API" /D "%~dp0be" cmd /k ".venv\Scripts\python.exe manage.py runserver 127.0.0.1:43124"
start "Sable Worker" /D "%~dp0be" cmd /k ".venv\Scripts\python.exe -m celery -A config worker --loglevel=info --pool=solo"
start "Sable UI" /D "%~dp0fe" cmd /k "npm run dev"

echo [wait] Waiting for the API to answer...
set /a api_tries=0
:wait_api
where curl >nul 2>&1
if errorlevel 1 goto :wait_ui
curl -sf -m 2 -o nul http://127.0.0.1:43124/api/v1/health/ 2>nul
if not errorlevel 1 goto :wait_ui
set /a api_tries+=1
if %api_tries% geq 30 goto :wait_ui
ping -n 2 127.0.0.1 >nul
goto :wait_api

:wait_ui
if %api_tries% geq 30 (
  echo [warn] The API did not answer in time. Check the "Sable API" window for errors.
)
echo [wait] Waiting for the UI to answer...
set /a ui_tries=0
:wait_ui_loop
where curl >nul 2>&1
if errorlevel 1 goto :open_ui
curl -sf -m 2 -o nul http://127.0.0.1:43123/ 2>nul
if not errorlevel 1 goto :open_ui
set /a ui_tries+=1
if %ui_tries% geq 30 goto :open_ui
ping -n 2 127.0.0.1 >nul
goto :wait_ui_loop

:open_ui
if %ui_tries% geq 30 (
  echo [warn] The UI did not answer in time. Check the "Sable UI" window for errors.
)
start "" "http://127.0.0.1:43123"

echo Sable is starting in three windows. Close those windows to stop it.
endlocal
