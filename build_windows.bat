@echo off
setlocal EnableExtensions
title PokerAssistant - build eseguibile Windows
cd /d "%~dp0"

echo ================================================
echo  PokerAssistant - build eseguibile standalone
echo  Cartella: %~dp0
echo ================================================

if not exist "poker-assistant.spec" goto err_spec
if not exist "requirements.txt" goto err_req
if not exist "models\poker_best.pt" goto err_model
where py >nul 2>nul
if errorlevel 1 goto err_py
goto ok

:err_spec
echo.
echo [ERRORE] Non trovo poker-assistant.spec in:
echo   %~dp0
echo Controlla che il file esista e si chiami ESATTAMENTE "poker-assistant.spec"
echo (se si chiama poker-assistant.spec.txt, rinominalo).
pause
exit /b 1

:err_req
echo.
echo [ERRORE] Non trovo requirements.txt in:
echo   %~dp0
pause
exit /b 1

:err_model
echo.
echo [ERRORE] Non trovo models\poker_best.pt (il modello YOLO).
echo Copia anche la cartella "models" dal progetto.
pause
exit /b 1

:err_py
echo.
echo [ERRORE] Python non trovato. Il comando "py" non esiste.
echo Installa Python 3.10-3.12 a 64 bit da https://www.python.org/downloads/
echo ATTENZIONE: durante l'installazione spunta la casella "Add Python to PATH".
pause
exit /b 1

:ok
if not exist .venv-win (
  echo [1/4] Creo l'ambiente virtuale...
  py -3 -m venv .venv-win
  if errorlevel 1 goto fail
) else (
  echo [1/4] Ambiente virtuale gia' presente: .venv-win
)

echo [2/4] Installo le dipendenze (alcuni minuti)...
".venv-win\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
echo   - torch CPU 2.6.0 (versione stabile con PyInstaller: evita WinError 1114)
".venv-win\Scripts\python.exe" -m pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto fail
".venv-win\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv-win\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 goto fail

echo [3/4] Compilo l'eseguibile standalone (3-5 minuti)...
".venv-win\Scripts\pyinstaller.exe" "poker-assistant.spec" --noconfirm
if errorlevel 1 goto fail

echo [4/4] FATTO!
echo.
echo Eseguibile:  %CD%\dist\PokerAssistant\PokerAssistant.exe
echo Config e log:  %APPDATA%\PokerAssistant
echo.
echo Copia la cartella dist\PokerAssistant dove vuoi e crea un collegamento.
pause
exit /b 0

:fail
echo.
echo [ERRORE] Qualcosa e' andato storto, vedi il messaggio sopra.
echo  - Problema di rete? Riprova piu' tardi.
echo  - Antivirus? Disattiva Windows Defender per la build.
echo  - Per sapere il motivo esatto: apri CMD, poi trascina questo bat dentro e premi Invio.
pause
exit /b 1