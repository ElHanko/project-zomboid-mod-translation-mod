#!/usr/bin/env python3

from collections import Counter, defaultdict
from pathlib import Path
import json
import re
import shutil
import sys


ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS = ROOT / "translations"

COMMON = ROOT / "common"
VERSION = ROOT / "42"

DE_ROOT = (
    COMMON
    / "media"
    / "lua"
    / "shared"
    / "Translate"
    / "DE"
)

MOD_ID = "ElHankoGermanTranslations"
MOD_NAME = "ElHanko German Translations"


PLACEHOLDER_RE = re.compile(
    r"""
    %\d+                       # PZ: %1, %2 ...
    |
    %(?!%)[#0\- +']*
    (?:\d+|\*)?
    (?:\.(?:\d+|\*))?
    [a-zA-Z]                   # printf-artig: %s, %d ...
    |
    \{[A-Za-z0-9_.:-]+\}       # {0}, {name}
    """,
    re.VERBOSE,
)


def die(message):
    print(f"FEHLER: {message}", file=sys.stderr)
    raise SystemExit(1)


def placeholders(text):
    return Counter(
        match.group(0)
        for match in PLACEHOLDER_RE.finditer(text)
    )


def load_drafts():
    result = []

    for path in sorted(TRANSLATIONS.glob("*.json")):
        try:
            data = json.loads(
                path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            die(f"Ungültiger Draft {path}: {exc}")

        result.append((path, data))

    return result


def draft_matches(data, selector):
    folded = selector.casefold()

    for value in (
        data.get("mod_id"),
        data.get("directory"),
        data.get("name"),
    ):
        if (
            isinstance(value, str)
            and value.casefold() == folded
        ):
            return True

    return False


def validate_entry(entry, draft_path):
    required = (
        "category",
        "key",
        "english",
        "german",
    )

    for field in required:
        if field not in entry:
            die(
                f"{draft_path}: Eintrag ohne "
                f"{field!r}: {entry!r}"
            )

    german = entry["german"]

    if not isinstance(german, str):
        die(
            f"{draft_path}: deutscher Text ist "
            f"kein String für {entry['key']}"
        )

    if not german.strip():
        die(
            f"{draft_path}: Übersetzung fehlt: "
            f"{entry['key']}"
        )

    if entry.get("review", False):
        die(
            f"{draft_path}: Review offen: "
            f"{entry['key']}"
        )

    source_ph = placeholders(entry["english"])
    target_ph = placeholders(german)

    if source_ph != target_ph:
        die(
            f"{draft_path}: Placeholder-Abweichung "
            f"bei {entry['key']}\n"
            f"  EN: {dict(source_ph)}\n"
            f"  DE: {dict(target_ph)}"
        )


def validate_selected(drafts, selector):
    matches = [
        (path, data)
        for path, data in drafts
        if draft_matches(data, selector)
    ]

    if not matches:
        die(f"Kein Draft gefunden: {selector}")

    if len(matches) != 1:
        die(f"Mehrere Drafts passen auf: {selector}")

    path, data = matches[0]

    needed = [
        entry
        for entry in data.get("entries", [])
        if entry.get("needed", True)
    ]

    if not needed:
        die(f"{path}: keine benötigten Einträge")

    for entry in needed:
        validate_entry(entry, path)

    return path, data


def is_buildable(path, data):
    needed = [
        entry
        for entry in data.get("entries", [])
        if entry.get("needed", True)
    ]

    if not needed:
        return False

    for entry in needed:
        if not entry.get("german", "").strip():
            return False

        if entry.get("review", False):
            return False

        if (
            placeholders(entry.get("english", ""))
            != placeholders(entry.get("german", ""))
        ):
            return False

    return True


def write_mod_info():
    content = (
        f"name={MOD_NAME}\n"
        f"id={MOD_ID}\n"
        "author=ElHanko\n"
        "description=German translations for Project Zomboid mods\n"
        "modversion=0.1\n"
        "versionMin=42.0\n"
    )

    COMMON.mkdir(parents=True, exist_ok=True)
    VERSION.mkdir(parents=True, exist_ok=True)

    # Die real vorgefundenen B42-Mods verwenden Metadaten
    # sowohl in common als auch in Versionsschichten.
    (COMMON / "mod.info").write_text(
        content,
        encoding="utf-8",
    )

    (VERSION / "mod.info").write_text(
        content,
        encoding="utf-8",
    )


def build(drafts):
    categories = defaultdict(dict)
    plain_files = {}

    owners = {}

    built_drafts = []
    entry_count = 0

    for path, data in drafts:
        if not is_buildable(path, data):
            continue

        built_drafts.append(path)

        owner = (
            data.get("mod_id")
            or data.get("directory")
            or path.name
        )

        for entry in data.get("entries", []):
            if not entry.get("needed", True):
                continue

            validate_entry(entry, path)

            category = entry["category"]
            key = entry["key"]
            german = entry["german"]

            if category == "__plain__":
                rel = Path(key)

                if (
                    rel.is_absolute()
                    or ".." in rel.parts
                ):
                    die(
                        f"{path}: unsicherer Plain-Pfad: {key}"
                    )

                identity = ("plain", str(rel))

                if identity in owners:
                    die(
                        "Doppelter Übersetzungseintrag:\n"
                        f"  {key}\n"
                        f"  {owners[identity]}\n"
                        f"  {owner}"
                    )

                owners[identity] = owner
                plain_files[rel] = german
                entry_count += 1
                continue

            identity = (category, key)

            if identity in owners:
                die(
                    "Doppelter Translation-Key:\n"
                    f"  {category}/{key}\n"
                    f"  {owners[identity]}\n"
                    f"  {owner}"
                )

            owners[identity] = owner
            categories[category][key] = german
            entry_count += 1

    if not built_drafts:
        die("Kein vollständig übersetzter Draft vorhanden.")

    # Nur generierten DE-Bestand erneuern.
    if DE_ROOT.exists():
        shutil.rmtree(DE_ROOT)

    DE_ROOT.mkdir(parents=True, exist_ok=True)

    json_files = 0

    for category, entries in sorted(categories.items()):
        rel = Path(category + ".json")

        if (
            rel.is_absolute()
            or ".." in rel.parts
        ):
            die(
                f"Unsichere Kategorie im Draft: {category}"
            )

        out = DE_ROOT / rel
        out.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        out.write_text(
            json.dumps(
                dict(sorted(entries.items())),
                ensure_ascii=False,
                indent=4,
            ) + "\n",
            encoding="utf-8",
        )

        json_files += 1

    for rel, value in sorted(
        plain_files.items(),
        key=lambda item: str(item[0]),
    ):
        out = DE_ROOT / rel
        out.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        out.write_text(
            value.rstrip() + "\n",
            encoding="utf-8",
        )

    write_mod_info()

    print("Build erfolgreich")
    print()
    print(f"Fertige Drafts:      {len(built_drafts)}")
    print(f"Übersetzungseinträge:{entry_count:6}")
    print(f"JSON-Dateien:        {json_files:6}")
    print(f"Plain-Dateien:       {len(plain_files):6}")
    print()
    print(f"Ausgabe: {DE_ROOT}")

    print()
    print("Enthaltene Drafts:")

    for path in built_drafts:
        print(f"  {path.name}")


def validate_output():
    errors = 0
    files = sorted(DE_ROOT.rglob("*"))
    json_files = [
        path
        for path in files
        if path.is_file()
        and path.suffix.lower() == ".json"
    ]

    total_keys = 0

    for path in json_files:
        try:
            data = json.loads(
                path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            print(f"FEHLER JSON: {path}: {exc}")
            errors += 1
            continue

        if not isinstance(data, dict):
            print(
                f"FEHLER ROOT: {path}: "
                "JSON-Wurzel ist kein Objekt"
            )
            errors += 1
            continue

        for key, value in data.items():
            if not isinstance(key, str):
                print(
                    f"FEHLER KEY: {path}: "
                    f"{key!r}"
                )
                errors += 1

            if not isinstance(value, str):
                print(
                    f"FEHLER VALUE: {path}: "
                    f"{key!r}"
                )
                errors += 1

        total_keys += len(data)

    print()
    print("Validierung:")
    print(f"  JSON-Dateien: {len(json_files)}")
    print(f"  JSON-Keys:    {total_keys}")
    print(f"  Fehler:       {errors}")

    if errors:
        raise SystemExit(1)

    print("  Ergebnis:     OK")


def main():
    if len(sys.argv) != 2:
        die("Verwendung: build.py MOD-ID")

    selector = sys.argv[1]
    drafts = load_drafts()

    selected_path, selected = validate_selected(
        drafts,
        selector,
    )

    print(
        "Geprüfter Draft: "
        f"{selected.get('name') or selected_path.name}"
    )
    print()

    build(drafts)
    validate_output()


if __name__ == "__main__":
    main()
