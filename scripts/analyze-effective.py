#!/usr/bin/env python3

from collections import Counter
from pathlib import Path
import json
import re
import sys

import config


ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "data" / "scan.json"
OUT = ROOT / "data" / "effective-formats.json"

TRANSLATE_REL = Path("media/lua/shared/Translate")


def die(message):
    print(f"FEHLER: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_scan():
    if not SCAN.is_file():
        die(f"{SCAN} fehlt. Zuerst './pzgt scan' ausführen.")

    return json.loads(SCAN.read_text(encoding="utf-8"))


def effective_files(mod, language):
    """
    common zuerst, danach die gewählte Versionsschicht.
    Eine gleichnamige Datei der Versionsschicht überschreibt common.
    """
    layers_by_name = {
        layer["name"]: layer
        for layer in mod["layers"]
    }

    result = {}

    for layer_name in mod.get("effective_layers", []):
        layer = layers_by_name.get(layer_name)

        if layer is None:
            continue

        base = (
            Path(layer["path"])
            / TRANSLATE_REL
            / language
        )

        for record in layer["translations"].get(language, []):
            rel = record["path"]
            path = base / rel

            result[rel] = {
                "path": str(path),
                "layer": layer_name,
                "suffix": record["suffix"],
                "size": record["size"],
            }

    return result


def classify_txt(path):
    try:
        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return "unreadable"

    name = path.name.lower()

    if name in ("title.txt", "description.txt"):
        return "plain-title-description"

    # Klassische PZ-Lua-Translationstabellen:
    # UI_EN = {
    #     UI_Foo = "Bar",
    # }
    if re.search(r"(?m)^\s*[A-Za-z0-9_]+\s*=\s*\{", text):
        return "lua-table"

    if re.search(
        r'(?m)^\s*[A-Za-z0-9_.:-]+\s*=\s*["\']',
        text,
    ):
        return "key-value"

    return "plain-or-unknown"


def analyze_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "valid": False,
            "error": str(exc),
            "entries": 0,
            "shape": None,
        }

    if isinstance(data, dict):
        scalar = sum(
            1
            for value in data.values()
            if isinstance(value, str)
        )

        return {
            "valid": True,
            "error": None,
            "entries": len(data),
            "string_entries": scalar,
            "shape": "object",
        }

    return {
        "valid": True,
        "error": None,
        "entries": len(data) if isinstance(data, list) else 1,
        "string_entries": 0,
        "shape": type(data).__name__,
    }


def main():
    scan = load_scan()

    records = []
    format_counts = Counter()
    suffix_counts = Counter()
    json_entries = 0
    json_errors = 0

    for mod in scan["mods"]:
        languages = {language: effective_files(mod, language)
                     for language in dict.fromkeys(["EN", *config.LANGUAGES])}

        if not any(languages.values()):
            continue

        mod_record = {
            "workshop_id": mod["workshop_id"],
            "directory": mod["directory"],
            "effective_id": mod.get("effective_id"),
            "effective_name": mod.get("effective_name"),
            "effective_layers": mod.get("effective_layers", []),
            **{language: {} for language in languages},
        }

        for language, files in languages.items():
            for rel, info in sorted(files.items()):
                path = Path(info["path"])
                suffix = path.suffix.lower()
                suffix_counts[suffix] += 1

                entry = dict(info)

                if suffix == ".json":
                    analysis = analyze_json(path)
                    entry["format"] = "json"
                    entry["analysis"] = analysis

                    format_counts["json"] += 1

                    if analysis["valid"]:
                        json_entries += analysis["entries"]
                    else:
                        json_errors += 1

                elif suffix == ".txt":
                    txt_format = classify_txt(path)
                    entry["format"] = txt_format
                    format_counts[txt_format] += 1

                else:
                    entry["format"] = "other"
                    format_counts["other"] += 1

                mod_record[language][rel] = entry

        records.append(mod_record)

    OUT.write_text(
        json.dumps(
            {
                "game_version": scan["game_version"],
                "format_counts": dict(
                    sorted(format_counts.items())
                ),
                "suffix_counts": dict(
                    sorted(suffix_counts.items())
                ),
                "json_entries": json_entries,
                "json_errors": json_errors,
                "mods": records,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print(f"Spielversion: {scan['game_version']}")
    print()
    print("Effektive Sprachdateien:")
    for suffix, count in sorted(suffix_counts.items()):
        print(f"  {suffix or '<ohne Endung>':8} {count:5}")

    print()
    print("Erkannte Formate:")
    for name, count in sorted(format_counts.items()):
        print(f"  {name:28} {count:5}")

    print()
    print(f"JSON-Einträge insgesamt: {json_entries}")
    print(f"JSON-Parsefehler:         {json_errors}")

    print()
    print("Beispiele für effektive TXT-Dateien:")
    shown = 0

    for mod in records:
        for rel, info in mod["EN"].items():
            if not rel.lower().endswith(".txt"):
                continue

            print(
                f'  {info["format"]:24} '
                f'{mod["effective_id"] or mod["directory"]}: '
                f'{rel} '
                f'[{info["layer"]}]'
            )

            shown += 1

            if shown >= 30:
                break

        if shown >= 30:
            break

    print()
    print(f"Vollständige Analyse: {OUT}")


if __name__ == "__main__":
    config.configure()
    main()
