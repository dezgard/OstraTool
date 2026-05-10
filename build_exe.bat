@echo off
setlocal
cd /d "%~dp0"

py -m pip install --upgrade pip
py -m pip install pyinstaller rarfile
py -m PyInstaller --onefile --windowed --name OstranautsSavePartViewer OstranautsSavePartViewer.py

echo.
echo Done. EXE should be here:
echo %CD%\dist\OstranautsSavePartViewer.exe
echo.
pause
