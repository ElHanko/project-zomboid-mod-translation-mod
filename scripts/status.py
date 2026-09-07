#!/usr/bin/env python3

from collections import Counter
from pathlib import Path
import json
import re

import config
from common import load_json, write_json


TRANSLATE_REL = Path("media/lua/shared/Translate")

ASSIGNMENT_RE = re.compile(
    r'^\s*([A-Za-z0-9_.:-]+)\s*=\s*"((?:\\.|[^"\\])*)"\s*,?\s*(?:--.*)?$'
)


def strip_trailing_commas(text):
    """
    Entfernt nur Kommata außerhalb von Strings, wenn danach
    ausschließlich Whitespace und } oder ] folgt.
    """
    result = []
    in_string = False
    escaped = False
    removed = 0
    i = 0

    while i < len(text):
        ch = text[i]

        if in_string:
            result.append(ch)

            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False

            i += 1
            continue

        if ch == '"':
            in_string = True
            result.append(ch)
            i += 1
            continue

        if ch == ",":
            j = i + 1

            while j < len(text) and text[j].isspace():
                j += 1

            if j < len(text) and text[j] in "}]":
                removed += 1
                i += 1
                continue

        result.append(ch)
        i += 1

    return "".join(result), removed


def parse_json_file(path):
    try:
        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return {}, {
            "error": str(exc),
            "lenient": False,
            "trailing_commas_removed": 0,
            "non_string_values": 0,
        }

    lenient = False
    removed = 0

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        fixed, removed = strip_trailing_commas(text)

        try:
            data = json.loads(fixed)
            lenient = True
        except json.JSONDecodeError as exc:
            return {}, {
                "error": str(exc),
                "lenient": False,
                "trailing_commas_removed": removed,
                "non_string_values": 0,
            }

    if not isinstance(data, dict):
        return {}, {
            "error": "JSON-Wurzel ist kein Objekt",
            "lenient": lenient,
            "trailing_commas_removed": removed,
            "non_string_values": 0,
        }

    entries = {}
    non_string = 0

    for key, value in data.items():
        if not isinstance(key, str):
            continue

        if not isinstance(value, str):
            non_string += 1
            continue

        entries[key] = value

    return entries, {
        "error": None,
        "lenient": lenient,
        "trailing_commas_removed": removed,
        "non_string_values": non_string,
    }


def decode_lua_string(value):
    """
    Genug für die üblichen PZ-Translationstrings.
    Unbekannte Escape-Sequenzen bleiben erhalten.
    """
    result = []
    i = 0

    simple = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        '"': '"',
        "\\": "\\",
    }

    while i < len(value):
        ch = value[i]

        if ch != "\\" or i + 1 >= len(value):
            result.append(ch)
            i += 1
            continue

        nxt = value[i + 1]

        if nxt in simple:
            result.append(simple[nxt])
        else:
            result.append("\\")
            result.append(nxt)

        i += 2

    return "".join(result)


def parse_legacy_txt(path):
    try:
        lines = path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except OSError as exc:
        return {}, {
            "error": str(exc),
            "unparsed_assignments": [],
        }

    entries = {}
    unparsed = []

    for number, line in enumerate(lines, start=1):
        stripped = line.strip()

        if not stripped:
            continue

        if stripped.startswith("--"):
            continue

        # Wrapper wie:
        # IG_UI_EN = {
        # RecipesEN {
        # }
        if (
            stripped == "}"
            or stripped == "},"
            or stripped.endswith("{")
        ):
            continue

        match = ASSIGNMENT_RE.match(line)

        if match:
            key = match.group(1)
            value = decode_lua_string(match.group(2))
            entries[key] = value
            continue

        # Nur Zeilen melden, die wie ein Translation-Eintrag aussehen.
        if "=" in line and '"' in line:
            unparsed.append({
                "line": number,
                "text": line[:300],
            })

    return entries, {
        "error": None,
        "unparsed_assignments": unparsed,
    }


def normalize_category(relative_path, language):
    path = Path(relative_path)
    stem = path.stem

    # Legacy:
    # IG_UI_EN.txt      -> IG_UI
    # Recipes_DE.txt    -> Recipes
    #
    # Manche Wrapper benutzen RecipesEN, der Dateiname ist aber
    # in unseren Mods trotzdem meist Recipes_EN.txt.
    stem = re.sub(
        rf"[_-]?{re.escape(language)}$",
        "",
        stem,
        flags=re.IGNORECASE,
    )

    if path.parent == Path("."):
        return stem

    return str(path.parent / stem)


def is_metadata_key(key):
    # B42-Mods verwenden z.B.
    # HEADER_IG_UI_EN_84jeepXJ = Workshop-ID.
    return key.startswith("HEADER_")


def identity(category, key):
    return f"{category}\0{key}"


def layer_files(mod, layer_name, language):
    layer = next(
        (
            item
            for item in mod["layers"]
            if item["name"] == layer_name
        ),
        None,
    )

    if layer is None:
        return []

    base = (
        Path(layer["path"])
        / TRANSLATE_REL
        / language
    )

    result = []

    for record in layer["translations"].get(language, []):
        result.append((
            record["path"],
            base / record["path"],
        ))

    return sorted(result)


def collect_language(mod, language):
    """
    common zuerst, dann Versionsschicht.

    Dadurch überschreibt die Versionsschicht denselben Translation-Key
    auch dann, wenn der Autor beim Update den Dateinamen oder das
    Format geändert hat.
    """
    entries = {}
    parse_errors = []
    warnings = []
    metadata = 0
    duplicates_same_layer = []
    tolerant_json_files = 0

    for layer_name in mod.get("effective_layers", []):
        seen_this_layer = {}

        for rel, path in layer_files(
            mod,
            layer_name,
            language,
        ):
            suffix = path.suffix.lower()

            if (
                suffix == ".txt"
                and path.name.lower() in (
                    "title.txt",
                    "description.txt",
                )
            ):
                try:
                    value = path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    ).strip()
                except OSError as exc:
                    parse_errors.append({
                        "layer": layer_name,
                        "file": rel,
                        "error": str(exc),
                    })
                    continue

                entry_id = identity("__plain__", rel)

                record = {
                    "category": "__plain__",
                    "key": rel,
                    "text": value,
                    "file": rel,
                    "layer": layer_name,
                    "format": "plain-title-description",
                }

                if entry_id in seen_this_layer:
                    duplicates_same_layer.append({
                        "identity": entry_id,
                        "first": seen_this_layer[entry_id],
                        "second": rel,
                    })

                seen_this_layer[entry_id] = rel
                entries[entry_id] = record
                continue

            if suffix == ".json":
                parsed, info = parse_json_file(path)

                if info["error"]:
                    parse_errors.append({
                        "layer": layer_name,
                        "file": rel,
                        "error": info["error"],
                    })
                    continue

                if info["lenient"]:
                    tolerant_json_files += 1
                    warnings.append({
                        "layer": layer_name,
                        "file": rel,
                        "warning": (
                            "JSON nur nach Entfernen abschließender "
                            f"Kommata parsebar ({info['trailing_commas_removed']})"
                        ),
                    })

                if info["non_string_values"]:
                    warnings.append({
                        "layer": layer_name,
                        "file": rel,
                        "warning": (
                            f"{info['non_string_values']} "
                            "Nicht-String-Werte ignoriert"
                        ),
                    })

                file_format = "json"

            elif suffix == ".txt":
                parsed, info = parse_legacy_txt(path)

                if info["error"]:
                    parse_errors.append({
                        "layer": layer_name,
                        "file": rel,
                        "error": info["error"],
                    })
                    continue

                if info["unparsed_assignments"]:
                    warnings.append({
                        "layer": layer_name,
                        "file": rel,
                        "warning": "Nicht geparste Assignment-Zeilen",
                        "lines": info["unparsed_assignments"],
                    })

                file_format = "legacy-txt"

            else:
                continue

            # Vanilla JSON filenames are language-neutral: the end of
            # SurvivalGuide is part of its name, not a DE language suffix.
            category = (str(Path(rel).with_suffix(""))
                        if mod.get("source_type") == "game" and suffix == ".json"
                        else normalize_category(rel, language))

            for key, value in parsed.items():
                if is_metadata_key(key):
                    metadata += 1
                    continue

                entry_id = identity(category, key)

                record = {
                    "category": category,
                    "key": key,
                    "text": value,
                    "file": rel,
                    "layer": layer_name,
                    "format": file_format,
                }

                if entry_id in seen_this_layer:
                    duplicates_same_layer.append({
                        "identity": entry_id,
                        "first": seen_this_layer[entry_id],
                        "second": rel,
                    })

                seen_this_layer[entry_id] = rel

                # Absichtlich überschreiben:
                # spätere effektive Schicht gewinnt.
                entries[entry_id] = record

    return {
        "entries": entries,
        "parse_errors": parse_errors,
        "warnings": warnings,
        "metadata_ignored": metadata,
        "duplicates_same_layer": duplicates_same_layer,
        "tolerant_json_files": tolerant_json_files,
    }


def analyze_scan(scan, language):
    if language not in scan.get("languages", []):
        raise ValueError(f"Scan enthält {language} nicht; zuerst ./pzgt scan ausführen")

    rows = []
    totals = Counter()
    base_game = None

    sources = [(mod, False) for mod in scan["mods"]]
    if scan.get("base_game") is not None:
        sources.append((scan["base_game"], True))
    for mod, is_game in sources:
        en = collect_language(mod, "EN")
        target_data = collect_language(mod, language)

        en_entries = en["entries"]
        target_entries = target_data["entries"]

        missing = []
        translated = []
        blank = []
        ignored = Counter()

        for entry_id, source in en_entries.items():
            target = target_entries.get(entry_id)

            if target is None:
                if is_game and not source["text"].strip():
                    ignored["empty_source_ignored"] += 1
                    continue
                missing.append(source)
                continue

            if not target["text"].strip():
                if is_game:
                    ignored["blank_ignored"] += 1
                    continue
                item = dict(source)
                item["target_file"] = target["file"]
                item["target_layer"] = target["layer"]
                blank.append(item)
                continue

            translated.append(entry_id)

        extra_target = [
            record
            for entry_id, record in target_entries.items()
            if entry_id not in en_entries
        ]

        open_count = len(missing) + len(blank)
        parse_error_count = (
            len(en["parse_errors"])
            + len(target_data["parse_errors"])
        )

        row = {
            **({"source_type": "game", "name": mod["name"]} if is_game else {
                "workshop_id": mod["workshop_id"],
                "directory": mod["directory"],
                "mod_id": mod.get("effective_id"),
                "name": mod.get("effective_name"),
            }),
            "effective_layers": mod.get(
                "effective_layers",
                [],
            ),
            "counts": {
                "english": len(en_entries),
                "translated": len(translated),
                "missing": len(missing),
                "blank": len(blank),
                "open": open_count,
                "extra_target": len(extra_target),
                "parse_errors": parse_error_count,
            },
            "english": list(en_entries.values()),
            "missing": missing,
            "blank": blank,
            "extra_target": extra_target,
            "parser": {
                "EN": {
                    "parse_errors": en["parse_errors"],
                    "warnings": en["warnings"],
                    "metadata_ignored": en["metadata_ignored"],
                    "duplicates_same_layer": en[
                        "duplicates_same_layer"
                    ],
                    "tolerant_json_files": en[
                        "tolerant_json_files"
                    ],
                },
                language: {
                    "parse_errors": target_data["parse_errors"],
                    "warnings": target_data["warnings"],
                    "metadata_ignored": target_data["metadata_ignored"],
                    "duplicates_same_layer": target_data[
                        "duplicates_same_layer"
                    ],
                    "tolerant_json_files": target_data[
                        "tolerant_json_files"
                    ],
                },
            },
        }

        if is_game:
            row["counts"].update(
                missing_total=len(missing) + ignored["empty_source_ignored"],
                empty_source_ignored=ignored["empty_source_ignored"],
                blank_ignored=ignored["blank_ignored"],
            )
            base_game = row
            continue
        rows.append(row)

        totals["english"] += len(en_entries)
        totals["translated"] += len(translated)
        totals["missing"] += len(missing)
        totals["blank"] += len(blank)
        totals["open"] += open_count
        totals["extra_target"] += len(extra_target)
        totals["parse_errors"] += parse_error_count
        totals["metadata_ignored"] += (
            en["metadata_ignored"]
            + target_data["metadata_ignored"]
        )
        totals["tolerant_json_files"] += (
            en["tolerant_json_files"]
            + target_data["tolerant_json_files"]
        )

    rows.sort(
        key=lambda row: (
            row["counts"]["open"],
            row["counts"]["english"],
            row["mod_id"] or row["directory"],
        ),
        reverse=True,
    )

    return {"language": language, "game_version": scan["game_version"],
            "totals": dict(totals), "mods": rows,
            **({"base_game": base_game} if base_game is not None else {})}


def run(language=None):
    language = config.select_language(language)
    scan = load_json(config.DATA / "scan.json")
    data = analyze_scan(scan, language)
    write_json(config.DATA / "status.json", data)
    rows = data["mods"]
    totals = Counter(data["totals"])
    print(f"Project Zomboid {scan['game_version']}")
    print()
    if "base_game" in data:
        counts = data["base_game"]["counts"]
        print("Hauptspiel: Project Zomboid")
        print(f"  EN: {counts['english']} | {language} vollständig fehlend: {counts['missing_total']} | "
              f"Offen: {counts['open']} | Parserfehler: {counts['parse_errors']}")
        print(f"  Ignoriert: {counts['empty_source_ignored']} fehlende Keys mit leerem EN-Text; "
              f"{counts['blank_ignored']} vorhandene leere {language}-Werte")
        print()
    print(
        f'{"OFFEN":>6} '
        f'{language:>6} '
        f'{"EN":>6} '
        f'{"FEHLER":>6}  '
        f'{"MOD-ID":45} '
        f'NAME'
    )
    print("-" * 125)

    for row in rows:
        counts = row["counts"]

        marker = "✓" if counts["open"] == 0 else " "

        print(
            f'{counts["open"]:6} '
            f'{counts["translated"]:6} '
            f'{counts["english"]:6} '
            f'{counts["parse_errors"]:6} {marker} '
            f'{(row["mod_id"] or "-")[:45]:45} '
            f'{row["name"] or row["directory"]}'
        )

    print()
    print("Workshop gesamt:")
    print(f'  Englische Einträge:    {totals["english"]}')
    print(f'  {language} vorhanden:     {totals["translated"]}')
    print(f'  Fehlend:               {totals["missing"]}')
    print(f'  {language} leer:          {totals["blank"]}')
    print(f'  Offen gesamt:          {totals["open"]}')
    print(f'  Nur in {language}:             {totals["extra_target"]}')
    print(f'  Parserfehler:          {totals["parse_errors"]}')
    print(f'  Metadaten ignoriert:   {totals["metadata_ignored"]}')
    print(
        "  Tolerant gelesene JSON:"
        f' {totals["tolerant_json_files"]}'
    )

    print()
    print(f"Details: {config.DATA / 'status.json'}")

    if totals["parse_errors"]:
        print()
        print(
            "WARNUNG: Parserfehler vorhanden; "
            "Zahlen für betroffene Mods sind noch nicht vollständig."
        )


if __name__ == "__main__":
    config.configure()
    run()
