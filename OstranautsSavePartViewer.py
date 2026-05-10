#!/usr/bin/env python3
# OstraTool / Ostranauts Save Part Viewer
# Dezgard signature: built for Dezgard's Ostranauts save-inspection workflow.
"""
Ostranauts Save Part Viewer

Small Windows-friendly Tkinter tool.

Dezgard signature:
  Built for Dezgard's Ostranauts save-inspection workflow.

Version: 1.0 - fixes ship file detection for saves using ships/*.json paths.

What it does:
  - Select Ostranauts game/data folder.
  - Select or auto-scan save files/folders.
  - Finds player JSON -> strShip -> ships/<ship id>.json.
  - Lists installed ship parts.
  - Tries to resolve part definitions from game data/items/*.json.
  - Exports CSV.
  - Shows a preview image for the selected component when a matching image is found.

Supported save input:
  - Extracted save folder
  - .zip save archive
  - .rar save archive if rarfile + UnRAR/7-Zip are installed and working

Build into exe on Windows:
  pip install pyinstaller rarfile pillow
  pyinstaller --onefile --windowed --name OstranautsSavePartViewer OstranautsSavePartViewer.py
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from collections import Counter, defaultdict
from typing import Any

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None

APP_NAME = "Ostranauts Save Part Viewer v1.0"
APP_AUTHOR = "Dezgard"
APP_SIGNATURE = "OstraTool by Dezgard"

STRUCTURAL_DEF_PREFIXES = (
    "ItmFloor",
    "ItmWall",
    "ItmConduit",
    "ItmFrame",
    "ItmHull",
)

STRUCTURAL_CONDS = {
    "IsFloorGrate",
    "IsWall",
    "IsWall1x1",
    "IsPowerConduit",
}

PART_HINT_CONDS = {
    "IsShipSpecialItem",
    "IsPowered",
    "IsPowerStorage",
    "IsAirPump",
    "IsRTA",
    "IsComputer",
    "IsNavStation",
    "IsTransponder",
    "IsBattery01",
    "IsAtmoScrubber",
    "IsCanister",
    "IsRechargingContainer",
}

DEF_ID_KEYS = (
    "strName", "strID", "strCODef", "id", "ID", "name", "Name", "def", "Def"
)

FRIENDLY_KEYS = (
    "strFriendlyName", "strDisplayName", "strNameDisplay", "displayName",
    "DisplayName", "friendlyName", "FriendlyName", "strTitle", "title", "Title"
)

DESC_KEYS = (
    "strDesc", "description", "Description", "desc", "Desc"
)

CATEGORY_KEYS = (
    "strCategory", "category", "Category", "categories", "Categories"
)

IMAGE_KEYS = (
    "strImg", "strImage", "strSprite", "strIcon", "strTexture",
    "strTex", "strAtlas", "strSpriteName", "strPortrait", "strFile",
    "image", "Image", "icon", "Icon", "sprite", "Sprite",
    "texture", "Texture", "tex", "Tex", "atlas", "Atlas",
    "img", "Img", "path", "Path", "file", "File", "filename", "Filename"
)

IMAGE_KEYWORDS = (
    "image", "sprite", "icon", "texture", "tex", "atlas",
    "portrait", "thumbnail", "png", "jpg", "jpeg"
)

COMMON_SAVE_DIRS = [
    Path.home() / "AppData" / "LocalLow" / "Blue Bottle Games" / "Ostranauts" / "Saves",
    Path.home() / "AppData" / "LocalLow" / "Blue Bottle Games" / "Ostranauts",
]

COMMON_GAME_DIRS = [
    Path(r"C:\Program Files (x86)\Steam\steamapps\common\Ostranauts"),
    Path(r"C:\Program Files\Steam\steamapps\common\Ostranauts"),
]

CONFIG_PATH = Path.home() / "AppData" / "Local" / "OstranautsSavePartViewer" / "settings.json"

LAST_IMAGE_INDEX: dict[str, str] = {}


@dataclass
class PartDef:
    codedef: str
    friendly_name: str = ""
    category: str = ""
    description: str = ""
    source: str = ""
    image_path: str = ""


@dataclass
class PartRow:
    count: int
    codedef: str
    save_name: str
    resolved_name: str
    category: str
    mass: str
    base_price: str
    damage: str
    damage_max: str
    ids: str
    source: str
    image_path: str = ""
    positions: str = ""


def safe_json_loads(data: bytes | str) -> Any:
    if isinstance(data, bytes):
        text = data.decode("utf-8-sig", errors="replace")
    else:
        text = data
    return json.loads(text)


def cond_name(cond: str) -> str:
    return str(cond).split("=", 1)[0]


def cond_value(cond: str) -> str | None:
    s = str(cond)
    if "=" not in s:
        return None
    return s.split("=", 1)[1]


def cond_names(co: dict[str, Any]) -> set[str]:
    return {cond_name(c) for c in co.get("aConds", []) if isinstance(c, str)}


def has_cond(co: dict[str, Any], wanted: str) -> bool:
    return wanted in cond_names(co)


def get_stat(co: dict[str, Any], stat_name: str) -> str:
    prefix = stat_name + "="
    for c in co.get("aConds", []):
        if isinstance(c, str) and c.startswith(prefix):
            raw = c.split("=", 1)[1]
            if "x" in raw:
                return raw.split("x", 1)[1]
            return raw
    return ""


def classify_installed(co: dict[str, Any]) -> str:
    codedef = str(co.get("strCODef", ""))
    conds = cond_names(co)
    if codedef.startswith(STRUCTURAL_DEF_PREFIXES) or conds.intersection(STRUCTURAL_CONDS):
        return "structural"
    if any(c.startswith("IsCategory") for c in conds) or conds.intersection(PART_HINT_CONDS):
        return "part"
    return "other_installed"


def extract_zip_bytes(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path, "r") as z:
        return {n.replace("\\", "/"): z.read(n) for n in z.namelist() if not n.endswith("/")}


def extract_rar_bytes(path: Path) -> dict[str, bytes]:
    try:
        import rarfile
    except ImportError as e:
        raise RuntimeError("RAR support needs: pip install rarfile") from e

    try:
        with rarfile.RarFile(path) as rf:
            names = [n for n in rf.namelist() if not n.endswith("/")]
            inner_zips = [n for n in names if n.lower().endswith(".zip")]
            if inner_zips:
                inner = rf.read(inner_zips[0])
                with zipfile.ZipFile(io.BytesIO(inner), "r") as z:
                    return {n.replace("\\", "/"): z.read(n) for n in z.namelist() if not n.endswith("/")}
            return {n.replace("\\", "/"): rf.read(n) for n in names}
    except Exception as e:
        raise RuntimeError(
            "Could not read RAR. Install 7-Zip or UnRAR and add it to PATH, "
            "or extract/re-save the save as ZIP.\n\n" + str(e)
        ) from e


def load_save_files(path: Path) -> dict[str, bytes]:
    if path.is_dir():
        files: dict[str, bytes] = {}
        for p in path.rglob("*"):
            if p.is_file():
                rel = p.relative_to(path).as_posix()
                try:
                    files[rel] = p.read_bytes()
                except Exception:
                    pass
        return files

    suffix = path.suffix.lower()
    if suffix == ".zip":
        return extract_zip_bytes(path)
    if suffix == ".rar":
        return extract_rar_bytes(path)
    raise RuntimeError("Save must be an extracted folder, .zip, or .rar")


def find_json_by_exact(files: dict[str, bytes], exact_name: str) -> Any | None:
    wanted = exact_name.replace("\\", "/").lower()
    wanted_base = wanted.split("/")[-1]
    for name, data in files.items():
        low = name.replace("\\", "/").lower()
        if low == wanted or low.endswith("/" + wanted_base) or low == wanted_base:
            return safe_json_loads(data)
    return None


def find_player_json(files: dict[str, bytes]) -> tuple[str, dict[str, Any]]:
    candidates = []
    checked = []
    for name in files:
        low = name.replace("\\", "/").lower()
        base = low.split("/")[-1]
        if low.endswith(".json") and base != "saveinfo.json" and not "/ships/" in low:
            candidates.append(name)

    # Prefer shallow files first, but allow nested save folders.
    candidates.sort(key=lambda n: (n.count("/"), n.lower()))

    for name in candidates:
        checked.append(name)
        try:
            data = safe_json_loads(files[name])
            root = data[0] if isinstance(data, list) and data else data
            if isinstance(root, dict) and "strShip" in root:
                return name, root
        except Exception:
            continue

    sample = "\n".join(checked[:30]) if checked else "No JSON files checked."
    raise RuntimeError("Could not find the player JSON. Expected a JSON containing strShip.\n\nChecked:\n" + sample)


def find_ship_json(files: dict[str, bytes], ship_id: str) -> tuple[str, dict[str, Any]]:
    wanted = f"ships/{ship_id}.json".lower()
    for name, data in files.items():
        low = name.replace("\\", "/").lower()
        if low == wanted or low.endswith("/" + wanted):
            obj = safe_json_loads(data)
            if isinstance(obj, list) and obj:
                return name, obj[0]
            if isinstance(obj, dict):
                return name, obj
    raise RuntimeError(f"Could not find ships/{ship_id}.json")


def first_string(d: dict[str, Any], keys: tuple[str, ...]) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, list) and v:
            return ", ".join(str(x) for x in v[:5])
    return ""


def normalize_asset_key(value: str) -> str:
    """Normalize game asset/image names so loose JSON refs can match real files."""
    s = str(value).replace("\\", "/").strip().strip('"').strip("'").lower()
    if not s:
        return ""
    for prefix in ("assets/resources/", "resources/", "streamingassets/", "data/"):
        s = s.replace(prefix, "")
    while "//" in s:
        s = s.replace("//", "/")
    return s


def add_image_index_key(index: dict[str, str], key: str, path: Path) -> None:
    key = normalize_asset_key(key)
    if not key:
        return
    index.setdefault(key, str(path))
    if key.endswith((".png", ".jpg", ".jpeg")):
        index.setdefault(key.rsplit(".", 1)[0], str(path))
    base = Path(key).name.lower()
    stem = Path(key).stem.lower()
    if base:
        index.setdefault(base, str(path))
    if stem:
        index.setdefault(stem, str(path))


def build_image_index(roots: list[Path]) -> dict[str, str]:
    index: dict[str, str] = {}
    search_roots: list[Path] = []
    for root in roots:
        search_roots.append(root)
        if root.parent not in search_roots:
            search_roots.append(root.parent)

    for root in search_roots:
        try:
            image_files = []
            for ext in ("*.png", "*.jpg", "*.jpeg"):
                image_files.extend(root.rglob(ext))
        except Exception:
            image_files = []

        for img in image_files:
            add_image_index_key(index, img.name, img)
            add_image_index_key(index, img.stem, img)
            add_image_index_key(index, img.as_posix(), img)
            try:
                rel = img.relative_to(root).as_posix()
                add_image_index_key(index, rel, img)
                add_image_index_key(index, rel.rsplit(".", 1)[0], img)
            except Exception:
                pass

            parts = [p.lower() for p in img.parts]
            if "data" in parts:
                i = parts.index("data")
                add_image_index_key(index, "/".join(img.parts[i:]), img)
                add_image_index_key(index, "/".join(img.parts[i + 1:]), img)
    return index


def collect_all_strings(obj: Any, values: list[str]) -> None:
    if isinstance(obj, str):
        if obj.strip():
            values.append(obj.strip())
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_all_strings(v, values)
    elif isinstance(obj, list):
        for v in obj:
            collect_all_strings(v, values)


def collect_image_like_strings(obj: Any, values: list[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_l = str(k).lower()
            key_says_image = k in IMAGE_KEYS or any(word in key_l for word in IMAGE_KEYWORDS)
            if isinstance(v, str):
                val = v.strip()
                val_l = val.lower()
                val_says_image = (
                    val_l.endswith((".png", ".jpg", ".jpeg"))
                    or ("/" in val_l and any(word in val_l for word in IMAGE_KEYWORDS))
                    or val_l.startswith(("tex", "sprite", "icon", "itm"))
                )
                if key_says_image or val_says_image:
                    values.append(val)
            elif isinstance(v, (list, dict)):
                if key_says_image:
                    collect_all_strings(v, values)
                collect_image_like_strings(v, values)
    elif isinstance(obj, list):
        for v in obj:
            collect_image_like_strings(v, values)


def image_candidates_from_obj(obj: dict[str, Any]) -> list[str]:
    values: list[str] = []
    collect_image_like_strings(obj, values)
    seen = set()
    out = []
    for v in values:
        key = normalize_asset_key(v)
        if key and key not in seen:
            seen.add(key)
            out.append(v)
    return out


def resolve_image_path(obj: dict[str, Any], codedef: str, image_index: dict[str, str]) -> str:
    raw_values = image_candidates_from_obj(obj)
    raw_values.extend([codedef, codedef.lower(), codedef.replace("Itm", "itm", 1), codedef.replace("Itm", "", 1)])

    for raw in raw_values:
        if not raw:
            continue
        r = normalize_asset_key(raw)
        checks = [r, Path(r).name.lower(), Path(r).stem.lower()]
        if not r.endswith((".png", ".jpg", ".jpeg")):
            checks.extend([r + ".png", Path(r).name.lower() + ".png", Path(r).stem.lower() + ".png"])
        for key in checks:
            key = normalize_asset_key(key)
            if key in image_index:
                return image_index[key]

    cd = codedef.lower()
    cd_no_itm = cd[3:] if cd.startswith("itm") else cd
    for key, img in image_index.items():
        stem = Path(key).stem.lower()
        if stem == cd or stem == cd_no_itm or cd in stem or cd_no_itm in stem:
            return img
    return ""

def maybe_item_id(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    v = value.strip()
    if len(v) < 4:
        return False
    return v.startswith(("Itm", "CO", "Obj"))


def walk_defs(obj: Any, source: str, found: dict[str, PartDef], image_index: dict[str, str]) -> None:
    if isinstance(obj, dict):
        codedef = ""
        for key in DEF_ID_KEYS:
            if maybe_item_id(obj.get(key)):
                codedef = str(obj[key]).strip()
                break

        if not codedef:
            # Fall back: some defs have one obvious item-like value.
            item_values = [str(v).strip() for v in obj.values() if maybe_item_id(v)]
            if len(item_values) == 1:
                codedef = item_values[0]

        if codedef and codedef not in found:
            found[codedef] = PartDef(
                codedef=codedef,
                friendly_name=first_string(obj, FRIENDLY_KEYS),
                category=first_string(obj, CATEGORY_KEYS),
                description=first_string(obj, DESC_KEYS),
                source=source,
                image_path=resolve_image_path(obj, codedef, image_index),
            )

        for v in obj.values():
            walk_defs(v, source, found, image_index)

    elif isinstance(obj, list):
        for v in obj:
            walk_defs(v, source, found, image_index)


def find_data_roots(game_folder: Path) -> list[Path]:
    roots = []
    candidates = [
        game_folder / "data",
        game_folder / "Ostranauts_Data" / "StreamingAssets" / "data",
        game_folder / "StreamingAssets" / "data",
    ]
    for c in candidates:
        if c.exists() and c.is_dir():
            roots.append(c)

    if not roots:
        # Limited recursive fallback. Avoid scanning entire drive.
        try:
            for p in game_folder.rglob("data"):
                if p.is_dir() and (p / "items").exists():
                    roots.append(p)
                    break
        except Exception:
            pass

    return roots


def load_part_defs(game_folder: Path) -> dict[str, PartDef]:
    if not game_folder or not game_folder.exists():
        return {}

    roots = find_data_roots(game_folder)
    found: dict[str, PartDef] = {}
    image_index = build_image_index(roots)

    global LAST_IMAGE_INDEX
    LAST_IMAGE_INDEX = image_index

    json_files: list[Path] = []
    for root in roots:
        preferred_dirs = [
            root / "items",
            root / "parts",
            root / "ship",
            root / "ships",
            root / "objects",
            root / "equipment",
        ]
        for preferred in preferred_dirs:
            if preferred.exists():
                json_files.extend(preferred.rglob("*.json"))

        # Also scan direct JSON files under data, but avoid a huge unrestricted startup crawl.
        try:
            json_files.extend(root.glob("*.json"))
        except Exception:
            pass

    seen = set()
    for jf in json_files:
        if jf in seen:
            continue
        seen.add(jf)
        try:
            obj = safe_json_loads(jf.read_bytes())
            walk_defs(obj, jf.as_posix(), found, image_index)
        except Exception:
            continue

    return found


def fallback_image_from_names(codedef: str, display_name: str = "") -> str:
    """
    Last-resort image lookup using CodeDef and display name.

    This helps when the item definition exists but does not directly carry a usable
    image/sprite field.
    """
    candidates = [
        codedef,
        codedef.lower(),
        codedef.replace("Itm", "", 1),
        codedef.replace("Itm", "itm", 1),
        display_name,
        display_name.replace(" ", ""),
        display_name.replace(" ", "_"),
        display_name.replace(":", ""),
        display_name.replace('"', ""),
    ]

    for raw in candidates:
        if not raw:
            continue
        key = normalize_asset_key(raw)
        checks = [key, Path(key).name.lower(), Path(key).stem.lower()]
        if not key.endswith((".png", ".jpg", ".jpeg")):
            checks.extend([key + ".png", Path(key).name.lower() + ".png", Path(key).stem.lower() + ".png"])
        for check in checks:
            check = normalize_asset_key(check)
            if check in LAST_IMAGE_INDEX:
                return LAST_IMAGE_INDEX[check]

    cd = codedef.lower()
    cd_no_itm = cd[3:] if cd.startswith("itm") else cd
    name_bits = [
        b.lower().strip('":()[]')
        for b in display_name.replace("-", " ").replace("_", " ").split()
        if len(b.strip('":()[]')) >= 4
    ]

    for key, img in LAST_IMAGE_INDEX.items():
        stem = Path(key).stem.lower()
        if cd in stem or cd_no_itm in stem:
            return img
        if name_bits and all(bit in stem for bit in name_bits[:2]):
            return img

    return ""


def list_ship_files(files: dict[str, bytes]) -> list[tuple[str, dict[str, Any]]]:
    ships: list[tuple[str, dict[str, Any]]] = []
    for name, data in files.items():
        low = name.replace("\\", "/").lower()
        if not low.endswith(".json"):
            continue
        if not (low.startswith("ships/") or "/ships/" in low):
            continue
        try:
            obj = safe_json_loads(data)
            root = obj[0] if isinstance(obj, list) and obj else obj
            if isinstance(root, dict):
                ships.append((name, root))
        except Exception:
            pass
    ships.sort(key=lambda pair: (
        str(pair[1].get("publicName", "")).lower(),
        str(pair[1].get("make", "")).lower(),
        pair[0].lower(),
    ))
    return ships


def select_ship_from_save(files: dict[str, bytes], player: dict[str, Any], save_info_root: dict[str, Any], preferred_ship_file: str = "") -> tuple[str, dict[str, Any], list[tuple[str, str]]]:
    """
    Select the actual player ship.

    In docked saves, player.strShip can point to the station/scene the player is in.
    saveInfo.shipName is usually the player's vessel name, so prefer a ship file
    whose publicName/shipName matches it. Expose all ship files for manual override.
    """
    ships = list_ship_files(files)
    choices: list[tuple[str, str]] = []

    for name, ship in ships:
        public = str(ship.get("publicName", ""))
        make_model = f"{ship.get('make', '')} {ship.get('model', '')}".strip()
        label = f"{public or Path(name).stem}  [{make_model}]  ({name})"
        choices.append((label, name))

    if preferred_ship_file:
        for name, ship in ships:
            if name == preferred_ship_file:
                return name, ship, choices

    save_ship_name = str(save_info_root.get("shipName", "")).strip().lower()
    if save_ship_name:
        for name, ship in ships:
            public = str(ship.get("publicName", "")).strip().lower()
            if public == save_ship_name:
                return name, ship, choices

    # Fall back to player.strShip only if no better match exists.
    ship_id = str(player.get("strShip", ""))
    wanted = f"ships/{ship_id}.json".lower()
    for name, ship in ships:
        low = name.replace("\\", "/").lower()
        if low == wanted or low.endswith("/" + wanted):
            return name, ship, choices

    # Final fallback: first ship file.
    if ships:
        return ships[0][0], ships[0][1], choices

    # Emergency fallback using player.strShip and the older recursive finder.
    if ship_id:
        try:
            name, ship = find_ship_json(files, ship_id)
            label = f"{ship.get('publicName', Path(name).stem)}  [{ship.get('make', '')} {ship.get('model', '')}]  ({name})"
            return name, ship, [(label, name)]
        except Exception:
            pass

    sample = "\n".join(list(files.keys())[:40])
    raise RuntimeError("Could not find any ships/*.json files in the save.\n\nFirst files seen:\n" + sample)

def get_coord_value(co: dict[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        v = co.get(name)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except Exception:
                pass
    for cond in co.get("aConds", []):
        if not isinstance(cond, str) or "=" not in cond:
            continue
        key, raw = cond.split("=", 1)
        if key in names:
            try:
                if "x" in raw:
                    raw = raw.split("x", 1)[-1]
                return float(raw)
            except Exception:
                pass
    return None


def get_position(co: dict[str, Any]) -> tuple[float, float] | None:
    """
    Try to find an object's ship-local/grid position.

    Ostranauts stores installed object state in aCOs, but placement usually lives
    in aItems/aShallowPSpecs using the same strID plus fX/fY.
    """
    x_names = ("x", "X", "fX", "iX", "nX", "gridX", "intX", "posX", "vX", "tileX")
    y_names = ("y", "Y", "fY", "iY", "nY", "gridY", "intY", "posY", "vY", "tileY")

    x = get_coord_value(co, x_names)
    y = get_coord_value(co, y_names)
    if x is not None and y is not None:
        return (x, y)

    for key in ("vPos", "vecPos", "position", "pos", "loc", "location", "aPos"):
        v = co.get(key)
        if isinstance(v, dict):
            x = get_coord_value(v, x_names)
            y = get_coord_value(v, y_names)
            if x is not None and y is not None:
                return (x, y)
        if isinstance(v, list) and len(v) >= 2:
            try:
                return (float(v[0]), float(v[1]))
            except Exception:
                pass
        if isinstance(v, str):
            cleaned = v.replace(",", " ").replace("x", " ").replace(";", " ")
            parts = [p for p in cleaned.split() if p]
            if len(parts) >= 2:
                try:
                    return (float(parts[0]), float(parts[1]))
                except Exception:
                    pass

    for cond in co.get("aConds", []):
        if isinstance(cond, str) and "=" in cond:
            key, raw = cond.split("=", 1)
            if key.lower() in {"pos", "position", "gridpos", "tilepos"}:
                cleaned = raw.replace(",", " ").replace("x", " ").replace(";", " ")
                parts = [p for p in cleaned.split() if p]
                if len(parts) >= 2:
                    try:
                        return (float(parts[0]), float(parts[1]))
                    except Exception:
                        pass

    return None


def make_item_position_index(ship: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """
    Build strID -> placement/spec map from aItems and aShallowPSpecs.

    aCOs has the installed item state. aItems usually has fX/fY/fRotation.
    """
    index: dict[str, dict[str, Any]] = {}
    for list_name in ("aItems", "aShallowPSpecs"):
        for item in ship.get(list_name, []):
            if not isinstance(item, dict):
                continue
            sid = item.get("strID")
            if isinstance(sid, str) and sid:
                index[sid] = item
    return index


def blueprint_kind(co: dict[str, Any]) -> str:
    codedef = str(co.get("strCODef", ""))
    conds = cond_names(co)
    if codedef.startswith("ItmWall") or "IsWall" in conds or "IsWall1x1" in conds:
        return "wall"
    if codedef.startswith(("ItmFloor", "ItmFrame", "ItmHull")) or "IsFloorGrate" in conds:
        return "floor"
    if codedef.startswith("ItmConduit") or "IsPowerConduit" in conds:
        return "conduit"
    return "item"


def make_blueprint_points(ship: dict[str, Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    pos_index = make_item_position_index(ship)

    for co in ship.get("aCOs", []):
        if not isinstance(co, dict) or not has_cond(co, "IsInstalled"):
            continue

        sid = co.get("strID")
        placed = pos_index.get(sid, {}) if isinstance(sid, str) else {}

        # Prefer aItems/aShallowPSpecs placement, then fall back to aCOs.
        pos = get_position(placed) if placed else None
        if pos is None:
            pos = get_position(co)
        if pos is None:
            continue

        points.append({
            "x": pos[0],
            "y": pos[1],
            "kind": blueprint_kind(co),
            "codedef": str(co.get("strCODef", "")),
            "name": str(co.get("strFriendlyName", "")),
        })

    return points


def parse_save(path: Path, part_defs: dict[str, PartDef], include_structural: bool, preferred_ship_file: str = "") -> tuple[dict[str, str], list[PartRow], list[dict[str, Any]], list[tuple[str, str]]]:
    files = load_save_files(path)

    save_info = find_json_by_exact(files, "saveInfo.json")
    save_info_root = save_info[0] if isinstance(save_info, list) and save_info else save_info if isinstance(save_info, dict) else {}

    player_file, player = find_player_json(files)
    ship_id = str(player.get("strShip", ""))

    ship_file, ship, ship_choices = select_ship_from_save(files, player, save_info_root, preferred_ship_file)

    blueprint_points = make_blueprint_points(ship)

    pos_index = make_item_position_index(ship)

    raw_rows = []
    for co in ship.get("aCOs", []):
        if not isinstance(co, dict):
            continue
        if not has_cond(co, "IsInstalled"):
            continue
        category = classify_installed(co)
        if category == "structural" and not include_structural:
            continue
        raw_rows.append(co)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for co in raw_rows:
        grouped[str(co.get("strCODef", ""))].append(co)

    rows: list[PartRow] = []
    for codedef, items in grouped.items():
        first = items[0]
        pdef = part_defs.get(codedef)
        save_name = str(first.get("strFriendlyName", ""))
        resolved_name = pdef.friendly_name if pdef and pdef.friendly_name else save_name
        cat = pdef.category if pdef and pdef.category else classify_installed(first)
        rows.append(PartRow(
            count=len(items),
            codedef=codedef,
            save_name=save_name,
            resolved_name=resolved_name,
            category=cat,
            mass=get_stat(first, "StatMass"),
            base_price=get_stat(first, "StatBasePrice"),
            damage=get_stat(first, "StatDamage"),
            damage_max=get_stat(first, "StatDamageMax"),
            ids=", ".join(str(x.get("strID", "")) for x in items if x.get("strID")),
            source=pdef.source if pdef else "save only",
            image_path=(pdef.image_path if pdef and pdef.image_path else fallback_image_from_names(codedef, resolved_name or save_name)),
            positions="; ".join(
                f"{pos[0]:.0f},{pos[1]:.0f}"
                for pos in (
                    get_position(pos_index.get(x.get("strID"), {})) or get_position(x)
                    for x in items
                )
                if pos is not None
            ),
        ))

    rows.sort(key=lambda r: (r.category, r.resolved_name or r.codedef, r.codedef))

    meta = {
        "save_path": str(path),
        "player_file": player_file,
        "ship_id": ship_id,
        "ship_file": ship_file,
        "player_name": str(save_info_root.get("playerName", player.get("strPlayerCO", ""))),
        "save_ship_name": str(save_info_root.get("shipName", "")),
        "version": str(save_info_root.get("version", "")),
        "ship_public_name": str(ship.get("publicName", "")),
        "ship_make_model": f"{ship.get('make', '')} {ship.get('model', '')}".strip(),
        "installed_count": str(sum(r.count for r in rows)),
        "definition_count": str(len(part_defs)),
    }
    return meta, rows, blueprint_points, ship_choices


def is_save_candidate(path: Path) -> bool:
    if path.is_file() and path.suffix.lower() in {".zip", ".rar"}:
        return True
    if path.is_dir():
        if (path / "saveInfo.json").exists():
            return True
        try:
            if any((path / "ships").glob("*.json")):
                return True
        except Exception:
            pass
    return False


def scan_saves(root: Path) -> list[Path]:
    results: list[Path] = []
    if not root.exists():
        return results

    # Direct archive/folder.
    if is_save_candidate(root):
        return [root]

    try:
        for p in root.iterdir():
            if is_save_candidate(p):
                results.append(p)
    except Exception:
        return []

    # Also check one level deeper for extracted saves.
    try:
        for p in root.iterdir():
            if p.is_dir():
                for q in p.iterdir():
                    if is_save_candidate(q):
                        results.append(q)
    except Exception:
        pass

    return sorted(set(results), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)


def load_config() -> dict[str, str]:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict[str, str]) -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1200x720")
        self.minsize(900, 560)

        self.cfg = load_config()
        self.game_folder = tk.StringVar(value=self.cfg.get("game_folder", self.detect_game_folder()))
        self.save_root = tk.StringVar(value=self.cfg.get("save_root", self.detect_save_root()))
        self.selected_save = tk.StringVar()
        self.include_structural = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value=f"{APP_SIGNATURE} — Select game folder and scan saves.")

        self.part_defs: dict[str, PartDef] = {}
        self.current_rows: list[PartRow] = []
        self.current_meta: dict[str, str] = {}
        self.current_blueprint_points: list[dict[str, Any]] = []
        self.ship_choices: list[tuple[str, str]] = []
        self.selected_ship_label = tk.StringVar()
        self.blueprint_zoom = 1.0
        self.save_paths: list[Path] = []
        self.row_by_iid: dict[str, PartRow] = {}
        self.preview_photo = None
        self.preview_image_original = None
        self.preview_zoom = 1.0
        self.preview_image_path = ""

        self.build_ui()

        # Do not scan game data before the window is visible.
        # Large Ostranauts folders can block startup long enough that the EXE appears
        # in Task Manager but no window is shown.
        self.after(50, self.finish_startup)

    def detect_game_folder(self) -> str:
        for p in COMMON_GAME_DIRS:
            if p.exists():
                return str(p)
        return ""

    def detect_save_root(self) -> str:
        for p in COMMON_SAVE_DIRS:
            if p.exists():
                return str(p)
        return str(Path.home())

    def build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)

        ttk.Label(top, text="Game folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.game_folder).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(top, text="Browse", command=self.browse_game_folder).grid(row=0, column=2, padx=4)
        ttk.Button(top, text="Load definitions", command=self.reload_defs).grid(row=0, column=3, padx=4)

        ttk.Label(top, text="Save folder/file:").grid(row=1, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.save_root).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Button(top, text="Browse folder", command=self.browse_save_folder).grid(row=1, column=2, padx=4)
        ttk.Button(top, text="Browse file", command=self.browse_save_file).grid(row=1, column=3, padx=4)

        top.columnconfigure(1, weight=1)

        mid = ttk.Frame(self)
        mid.pack(fill="x", **pad)

        ttk.Button(mid, text="Scan saves", command=self.scan_save_list).pack(side="left", padx=4)
        ttk.Label(mid, text="Save:").pack(side="left", padx=(16, 4))
        self.save_combo = ttk.Combobox(mid, textvariable=self.selected_save, state="readonly", width=80)
        self.save_combo.pack(side="left", fill="x", expand=True, padx=4)
        ttk.Checkbutton(mid, text="Show everything installed (floors/walls/conduits/frames/hull)", variable=self.include_structural).pack(side="left", padx=8)
        ttk.Button(mid, text="Analyze", command=self.analyze_selected).pack(side="left", padx=4)
        ttk.Button(mid, text="Export CSV", command=self.export_csv).pack(side="left", padx=4)

        meta_frame = ttk.LabelFrame(self, text="Save / ship info")
        meta_frame.pack(fill="x", **pad)
        self.meta_text = tk.Text(meta_frame, height=4, wrap="none")
        self.meta_text.pack(fill="x", padx=6, pady=4)
        self.meta_text.configure(state="disabled")

        ship_select_frame = ttk.Frame(self)
        ship_select_frame.pack(fill="x", **pad)
        ttk.Label(ship_select_frame, text="Ship for blueprint/list:").pack(side="left", padx=4)
        self.ship_combo = ttk.Combobox(ship_select_frame, textvariable=self.selected_ship_label, state="readonly", width=100)
        self.ship_combo.pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(ship_select_frame, text="Analyze selected ship", command=self.analyze_selected).pack(side="left", padx=4)

        table_frame = ttk.Frame(self)
        table_frame.pack(fill="both", expand=True, **pad)

        self.main_pane = ttk.PanedWindow(table_frame, orient="vertical")
        self.main_pane.pack(fill="both", expand=True)

        top_pane_holder = ttk.Frame(self.main_pane)
        blueprint_frame = ttk.LabelFrame(self.main_pane, text="Ship blueprint")

        self.main_pane.add(top_pane_holder, weight=4)
        self.main_pane.add(blueprint_frame, weight=1)

        self.table_pane = ttk.PanedWindow(top_pane_holder, orient="horizontal")
        self.table_pane.pack(fill="both", expand=True)

        table_left = ttk.Frame(self.table_pane)
        preview_frame = ttk.LabelFrame(self.table_pane, text="Component image")

        self.table_pane.add(table_left, weight=4)
        self.table_pane.add(preview_frame, weight=1)

        self.preview_label = ttk.Label(preview_frame, text="Select a part", anchor="center")
        self.preview_label.pack(fill="both", expand=True, padx=8, pady=8)
        self.preview_label.bind("<MouseWheel>", self.on_preview_mousewheel)
        self.preview_label.bind("<Button-4>", self.on_preview_mousewheel)
        self.preview_label.bind("<Button-5>", self.on_preview_mousewheel)
        self.preview_path = ttk.Label(preview_frame, text="", wraplength=360, justify="center")
        self.preview_path.pack(fill="x", padx=8, pady=(0, 8))

        self.blueprint_canvas = tk.Canvas(blueprint_frame, height=170, background="white")
        self.blueprint_canvas.pack(fill="both", expand=True, padx=6, pady=6)
        self.blueprint_canvas.bind("<Configure>", lambda event: self.draw_blueprint())
        self.blueprint_canvas.bind("<MouseWheel>", self.on_blueprint_mousewheel)
        self.blueprint_canvas.bind("<Button-4>", self.on_blueprint_mousewheel)
        self.blueprint_canvas.bind("<Button-5>", self.on_blueprint_mousewheel)

        columns = ("count", "codedef", "name", "category", "mass", "price", "damage", "image", "source")
        self.tree = ttk.Treeview(table_left, columns=columns, show="headings")
        headings = {
            "count": "Count", "codedef": "CodeDef", "name": "Name", "category": "Category",
            "mass": "Mass", "price": "Base Price", "damage": "Damage", "image": "Image", "source": "Definition Source",
        }
        widths = {"count": 70, "codedef": 180, "name": 230, "category": 130, "mass": 80, "price": 90, "damage": 90, "image": 70, "source": 280}
        for col in columns:
            self.tree.heading(col, text=headings[col], command=lambda c=col: self.sort_tree(c, False))
            self.tree.column(col, width=widths[col], anchor="w")

        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        vsb = ttk.Scrollbar(table_left, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_left.rowconfigure(0, weight=1)
        table_left.columnconfigure(0, weight=1)

        footer = ttk.Frame(self)
        footer.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(footer, textvariable=self.status, anchor="w").pack(side="left", fill="x", expand=True)
        ttk.Label(footer, text=APP_SIGNATURE, anchor="e").pack(side="right")

    def finish_startup(self) -> None:
        """Run light startup work only after the window has painted."""
        try:
            self.deiconify()
            self.lift()
            self.update_idletasks()
        except Exception:
            pass

        self.status.set("Window ready. Scan saves, then press Load definitions to resolve images/names.")
        try:
            self.scan_save_list()
        except Exception as e:
            self.status.set(f"Startup save scan skipped: {e}")

    def browse_game_folder(self) -> None:
        start = self.game_folder.get() or str(Path.home())
        chosen = filedialog.askdirectory(title="Select Ostranauts game folder or data folder", initialdir=start)
        if chosen:
            self.game_folder.set(chosen)
            self.reload_defs()

    def browse_save_folder(self) -> None:
        start = self.save_root.get() or str(Path.home())
        chosen = filedialog.askdirectory(title="Select Ostranauts save folder", initialdir=start)
        if chosen:
            self.save_root.set(chosen)
            self.scan_save_list()

    def browse_save_file(self) -> None:
        start = self.save_root.get() or str(Path.home())
        chosen = filedialog.askopenfilename(
            title="Select Ostranauts save archive",
            initialdir=start,
            filetypes=[("Save archives", "*.zip *.rar"), ("All files", "*.*")],
        )
        if chosen:
            self.save_root.set(chosen)
            self.scan_save_list()

    def reload_defs(self, silent: bool = False) -> None:
        folder = Path(self.game_folder.get()) if self.game_folder.get() else Path()
        try:
            self.part_defs = load_part_defs(folder)
            self.cfg["game_folder"] = str(folder) if str(folder) != "." else ""
            save_config(self.cfg)
            image_count = sum(1 for d in self.part_defs.values() if d.image_path)
            self.status.set(f"Loaded {len(self.part_defs)} part definitions from game data. Images resolved for {image_count}.")
            if not silent and not self.part_defs:
                messagebox.showwarning(APP_NAME, "No part definitions found. Select the Ostranauts folder that contains the data folder.")
        except Exception as e:
            self.part_defs = {}
            self.status.set("Failed to load game definitions.")
            if not silent:
                messagebox.showerror(APP_NAME, str(e))

    def scan_save_list(self) -> None:
        raw = self.save_root.get()
        if not raw:
            return
        root = Path(raw)
        self.cfg["save_root"] = raw
        save_config(self.cfg)
        self.save_paths = scan_saves(root)
        display = [str(p) for p in self.save_paths]
        self.save_combo["values"] = display
        if display:
            self.selected_save.set(display[0])
            self.status.set(f"Found {len(display)} save candidate(s).")
        else:
            self.selected_save.set("")
            self.status.set("No save candidates found. Browse directly to a .zip/.rar save or extracted save folder.")

    def analyze_selected(self) -> None:
        sel = self.selected_save.get()
        if not sel:
            messagebox.showwarning(APP_NAME, "No save selected.")
            return
        try:
            # Lazy-load definitions here instead of during startup.
            if not self.part_defs and self.game_folder.get():
                self.status.set("Loading game definitions/images...")
                self.update_idletasks()
                self.reload_defs(silent=True)

            preferred_ship_file = ""
            selected_label = self.selected_ship_label.get()
            for label, ship_file in self.ship_choices:
                if label == selected_label:
                    preferred_ship_file = ship_file
                    break

            meta, rows, blueprint_points, ship_choices = parse_save(Path(sel), self.part_defs, self.include_structural.get(), preferred_ship_file)
            self.ship_choices = ship_choices
            self.ship_combo["values"] = [label for label, _ in ship_choices]
            # Select the active ship label.
            for label, ship_file in ship_choices:
                if ship_file == meta.get("ship_file", ""):
                    self.selected_ship_label.set(label)
                    break

            self.current_meta = meta
            self.current_rows = rows
            self.current_blueprint_points = blueprint_points
            self.populate_meta(meta)
            self.populate_table(rows)
            self.draw_blueprint()
            img_rows = sum(1 for r in rows if r.image_path)
            self.status.set(f"Analyzed {Path(sel).name}: {meta.get('installed_count', '0')} installed object(s), {len(rows)} grouped row(s), {img_rows} with images, {len(blueprint_points)} blueprint points.")
        except Exception as e:
            self.current_meta = {}
            self.current_rows = []
            self.current_blueprint_points = []
            self.ship_choices = []
            self.ship_combo["values"] = []
            self.selected_ship_label.set("")
            self.populate_meta({})
            self.populate_table([])
            self.draw_blueprint()
            messagebox.showerror(APP_NAME, str(e))
            self.status.set("Analyze failed.")

    def populate_meta(self, meta: dict[str, str]) -> None:
        lines = []
        if meta:
            lines = [
                f"Player: {meta.get('player_name', '')}    Save ship: {meta.get('save_ship_name', '')}    Version: {meta.get('version', '')}",
                f"Ship ID: {meta.get('ship_id', '')}    Public name: {meta.get('ship_public_name', '')}    Make/model: {meta.get('ship_make_model', '')}",
                f"Ship file: {meta.get('ship_file', '')}    Player file: {meta.get('player_file', '')}",
                f"Resolved definitions loaded: {meta.get('definition_count', '0')}    Installed count: {meta.get('installed_count', '0')}",
            ]
        self.meta_text.configure(state="normal")
        self.meta_text.delete("1.0", "end")
        self.meta_text.insert("1.0", "\n".join(lines))
        self.meta_text.configure(state="disabled")

    def populate_table(self, rows: list[PartRow]) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.row_by_iid = {}
        self.clear_preview()
        for r in rows:
            dmg = ""
            if r.damage or r.damage_max:
                dmg = f"{r.damage}/{r.damage_max}" if r.damage_max else r.damage
            iid = self.tree.insert("", "end", values=(
                r.count, r.codedef, r.resolved_name or r.save_name, r.category,
                r.mass, r.base_price, dmg, "Yes" if r.image_path else "", r.source
            ))
            self.row_by_iid[iid] = r

    def clear_preview(self) -> None:
        self.preview_photo = None
        self.preview_image_original = None
        self.preview_zoom = 1.0
        self.preview_image_path = ""
        self.preview_label.configure(image="", text="Select a part")
        self.preview_path.configure(text="")

    def on_tree_select(self, event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            self.clear_preview()
            return
        row = self.row_by_iid.get(selected[0])
        if not row:
            self.clear_preview()
            return
        self.show_preview(row)

    def show_preview(self, row: PartRow) -> None:
        self.preview_zoom = 1.0
        self.preview_image_path = row.image_path or ""

        if not row.image_path:
            self.preview_photo = None
            self.preview_image_original = None
            self.preview_label.configure(image="", text="No image found")
            self.preview_path.configure(text=row.codedef)
            return

        path = Path(row.image_path)
        try:
            if Image is not None and ImageTk is not None:
                self.preview_image_original = Image.open(path).copy()
                self.render_preview_image()
            else:
                self.preview_image_original = None
                self.preview_photo = tk.PhotoImage(file=str(path))
                self.preview_label.configure(image=self.preview_photo, text="")
            self.preview_path.configure(text=f"{row.codedef}\\n{path.name}\\nMouse wheel = zoom")
        except Exception as e:
            self.preview_photo = None
            self.preview_image_original = None
            self.preview_label.configure(image="", text="Image load failed")
            self.preview_path.configure(text=f"{path}\\n{e}")

    def render_preview_image(self) -> None:
        if self.preview_image_original is None or ImageTk is None:
            return

        img = self.preview_image_original.copy()
        base_w, base_h = img.size

        # Fit to current panel, then apply user zoom.
        panel_w = max(self.preview_label.winfo_width(), 260)
        panel_h = max(self.preview_label.winfo_height(), 260)
        fit = min(panel_w / max(base_w, 1), panel_h / max(base_h, 1), 1.0)
        scale = max(0.1, min(8.0, fit * self.preview_zoom))

        new_size = (max(1, int(base_w * scale)), max(1, int(base_h * scale)))
        img = img.resize(new_size)
        self.preview_photo = ImageTk.PhotoImage(img)
        self.preview_label.configure(image=self.preview_photo, text="")

    def on_preview_mousewheel(self, event) -> None:
        if self.preview_image_original is None:
            return

        direction = 0
        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            direction = 1
        elif getattr(event, "num", None) == 5 or getattr(event, "delta", 0) < 0:
            direction = -1

        if direction > 0:
            self.preview_zoom *= 1.15
        elif direction < 0:
            self.preview_zoom /= 1.15

        self.preview_zoom = max(0.1, min(8.0, self.preview_zoom))
        self.render_preview_image()

    def draw_blueprint(self) -> None:
        canvas = getattr(self, "blueprint_canvas", None)
        if canvas is None:
            return

        canvas.delete("all")
        points = getattr(self, "current_blueprint_points", [])

        w = max(canvas.winfo_width(), 200)
        h = max(canvas.winfo_height(), 120)

        if not points:
            canvas.create_text(
                w // 2, h // 2,
                text="No blueprint position data found in this save.",
                fill="gray",
                anchor="center",
            )
            return

        xs = [p["x"] for p in points]
        ys = [p["y"] for p in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1)
        span_y = max(max_y - min_y, 1)

        pad = 20
        scale = min((w - pad * 2) / span_x, (h - pad * 2) / span_y) * self.blueprint_zoom
        if scale <= 0:
            scale = 1

        def tx(x: float) -> float:
            return pad + (x - min_x) * scale

        def ty(y: float) -> float:
            return h - pad - (y - min_y) * scale

        order = {"floor": 0, "conduit": 1, "item": 2, "wall": 3}
        colors = {
            "floor": "#d9d9d9",
            "wall": "#222222",
            "conduit": "#4d79ff",
            "item": "#cc6600",
        }

        cell = max(3, min(12, scale * 0.8))

        for p in sorted(points, key=lambda p: order.get(p.get("kind", "item"), 9)):
            x = tx(float(p["x"]))
            y = ty(float(p["y"]))
            kind = p.get("kind", "item")
            fill = colors.get(kind, "#777777")

            if kind == "wall":
                canvas.create_rectangle(
                    x - cell / 2, y - cell / 2,
                    x + cell / 2, y + cell / 2,
                    fill=fill, outline=fill,
                )
            elif kind == "floor":
                canvas.create_rectangle(
                    x - cell / 2, y - cell / 2,
                    x + cell / 2, y + cell / 2,
                    fill=fill, outline="#aaaaaa",
                )
            elif kind == "conduit":
                canvas.create_oval(
                    x - cell / 2, y - cell / 2,
                    x + cell / 2, y + cell / 2,
                    fill=fill, outline=fill,
                )
            else:
                canvas.create_oval(
                    x - cell / 2, y - cell / 2,
                    x + cell / 2, y + cell / 2,
                    fill=fill, outline="#663300",
                )

        canvas.create_text(
            8, 8,
            text=f"floor  wall  conduit  item    points: {len(points)}    zoom: {self.blueprint_zoom:.2f}x",
            anchor="nw",
            fill="#444444",
        )

    def on_blueprint_mousewheel(self, event) -> None:
        direction = 0
        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            direction = 1
        elif getattr(event, "num", None) == 5 or getattr(event, "delta", 0) < 0:
            direction = -1

        if direction > 0:
            self.blueprint_zoom *= 1.15
        elif direction < 0:
            self.blueprint_zoom /= 1.15

        self.blueprint_zoom = max(0.2, min(20.0, self.blueprint_zoom))
        self.draw_blueprint()

    def sort_tree(self, col: str, reverse: bool) -> None:
        data = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        def key(pair):
            v = pair[0]
            try:
                return float(v)
            except Exception:
                return str(v).lower()
        data.sort(key=key, reverse=reverse)
        for index, (_, k) in enumerate(data):
            self.tree.move(k, "", index)
        self.tree.heading(col, command=lambda: self.sort_tree(col, not reverse))

    def export_csv(self) -> None:
        if not self.current_rows:
            messagebox.showwarning(APP_NAME, "Analyze a save first.")
            return
        default = "ship_parts.csv"
        if self.current_meta.get("save_ship_name"):
            default = self.current_meta["save_ship_name"].replace(" ", "_") + "_parts.csv"
        out = filedialog.asksaveasfilename(
            title="Export CSV",
            defaultextension=".csv",
            initialfile=default,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not out:
            return
        try:
            with open(out, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Count", "CodeDef", "Name", "Save Name", "Category", "Mass", "Base Price", "Damage", "Damage Max", "IDs", "Positions", "Image Path", "Definition Source"])
                for r in self.current_rows:
                    writer.writerow([r.count, r.codedef, r.resolved_name, r.save_name, r.category, r.mass, r.base_price, r.damage, r.damage_max, r.ids, r.positions, r.image_path, r.source])
            self.status.set(f"CSV exported: {out}")
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))


def main() -> int:
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
