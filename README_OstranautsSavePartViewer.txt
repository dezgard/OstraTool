Ostranauts Save Part Viewer v1.0

Fix:
- Correctly detects ship files stored as:
  ships/*.json
  */ships/*.json

This fixes the v0.9 error:
  Could not find any ships/*.json files in the save.

Keeps:
- Ship selector dropdown.
- saveInfo.shipName preference.
- Blueprint mouse-wheel zoom.
- Component image mouse-wheel zoom.
- Stronger image fallback.

Build:
1. Extract this package.
2. Double-click build_exe.bat.
3. Run:
   dist\OstranautsSavePartViewer.exe
