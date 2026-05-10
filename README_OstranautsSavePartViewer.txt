Ostranauts Save Part Viewer v1.0
OstraTool by Dezgard

What it does:
- Reads Ostranauts save archives or extracted save folders.
- Finds the player/ship data.
- Lists installed items, floors, walls, conduits, racks, ship systems, and other detected installed objects.
- Resolves game item definitions from the selected Ostranauts game folder.
- Shows component images when a loose PNG/JPG or JSON-resolvable image path exists.
- Draws a small blueprint from save-position data.
- Supports mouse-wheel zoom for both component images and blueprint view.
- Exports CSV.

Build:
1. Install Python 3.10+.
2. Run build_exe.bat.
3. EXE output:
   dist\OstranautsSavePartViewer.exe

Manual build:
   py -m pip install --upgrade pip
   py -m pip install pyinstaller rarfile pillow
   py -m PyInstaller --onefile --windowed --name OstranautsSavePartViewer OstranautsSavePartViewer.py

Debug:
- Run run_debug.bat if the EXE starts but no window appears.

Notes:
- Some images are packed in Unity assets/sprite atlases and cannot be shown as loose files.
- Ship selector exists because docked saves may point at a station/current scene instead of the player's ship.

Signature:
Built for Dezgard's Ostranauts save-inspection workflow.
