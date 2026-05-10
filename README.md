# OstraTool

**OstraTool** is a Windows-friendly Ostranauts save inspection utility by **Dezgard**.

It reads an Ostranauts save, finds the player's ship data, lists installed parts and structure, previews component images where possible, and draws a small blueprint from save-position data.

## Current tool

`OstranautsSavePartViewer.py`

## What it does

- Select an Ostranauts save file or extracted save folder.
- Auto-scan save candidates.
- Select the Ostranauts game folder so the tool can resolve item definitions.
- Finds player/ship JSON data inside the save.
- Lists installed objects, including:
  - ship systems
  - racks
  - containers
  - installed items
  - floors
  - walls
  - conduits
  - frames/hull pieces where detected
- Groups matching objects by `CodeDef`.
- Shows count, name, category, mass, base price, damage, image status, and definition source.
- Shows component images when they can be resolved from loose game files.
- Supports mouse-wheel zoom on component image preview.
- Draws a simple ship blueprint from save object positions.
- Supports mouse-wheel zoom on the blueprint.
- Has a ship selector to avoid drawing the docked station when the save points at the current scene/station.
- Exports the analyzed list to CSV.

## Limitations

Some Ostranauts images are packed inside Unity assets or sprite atlases. If the game does not expose the image as a normal PNG/JPG or a direct JSON-resolvable path, the tool may show `No image found`.

Blueprint output depends on save-position data. Current logic uses installed object IDs matched against placement data such as `aItems.fX/fY`.

## Build the EXE

Requirements:

- Windows
- Python 3.10+
- Internet access for pip packages

Build steps:

```bat
build_exe.bat
```

Output:

```text
dist\OstranautsSavePartViewer.exe
```

Manual build:

```bat
py -m pip install --upgrade pip
py -m pip install pyinstaller rarfile pillow
py -m PyInstaller --onefile --windowed --name OstranautsSavePartViewer OstranautsSavePartViewer.py
```

## Debug run

If the EXE opens in Task Manager but no window appears, run:

```bat
run_debug.bat
```

That launches the Python script with console output so errors can be copied and checked.

## Files

```text
OstranautsSavePartViewer.py             Main GUI app
build_exe.bat                           Windows PyInstaller build script
run_debug.bat                           Console debug runner
README.md                               GitHub project readme
README_OstranautsSavePartViewer.txt     Short build/readme notes
```

## Signature

Built for Dezgard's Ostranauts save-inspection workflow.
