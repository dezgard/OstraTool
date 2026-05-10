@echo off
setlocal
cd /d "%~dp0"

echo Building Ostranauts Save Part Viewer...
echo.

py -m pip install --upgrade pip
py -m pip install pyinstaller rarfile pillow
py -m PyInstaller --onefile --windowed --name OstranautsSavePartViewer OstranautsSavePartViewer.py

echo.
echo Done. EXE should be here:
echo %CD%\dist\OstranautsSavePartViewer.exe
echo.
pause
