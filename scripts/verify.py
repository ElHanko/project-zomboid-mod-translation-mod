#!/usr/bin/env python3

from collections import Counter, defaultdict
from pathlib import Path
import json
import sys

import build as build_script


ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS = ROOT / "translations"
STATUS = ROOT / "data" / "status.json"

DE_ROOT = (
    ROOT
    / "common"
    / "media"
    / "lua"
    / "shared"
    / "Translate"
    / "DE"
)


def error(errors, message):
    errors.append(message)
    print(f"FEHLER: {message}")


def load_status(errors):
    if not STATUS.is_file():
        error(
            errors,
            f"{STATUS} fehlt. Zuerst './pzgt status' ausführen.",
        )
        return None

    try:
        return json.loads(
            STATUS.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        error(errors, f"{STATUS} ungültig: {exc}")
        return None


def identity(entry):
    return (
        entry.get("category"),
        entry.get("key"),
    )


def find_status_mod(status, draft):
    workshop_id = str(draft.get("workshop_id") or "")
    directory = str(draft.get("directory") or "")

    matches = [
        mod
        for mod in status.get("mods", [])
        if (
            str(mod.get("workshop_id") or "") == workshop_id
            and str(mod.get("directory") or "") == directory
        )
    ]

    if len(matches) == 1:
        return matches[0]

    # Fallback für ältere Drafts.
    mod_id = str(draft.get("mod_id") or "")

    matches = [
        mod
        for mod in status.get("mods", [])
        if (
            str(mod.get("workshop_id") or "") == workshop_id
            and str(mod.get("mod_id") or "") == mod_id
        )
    ]

    if len(matches) == 1:
        return matches[0]

    return None


def validate_source_sync(path, draft, status, errors):
    mod = find_status_mod(status, draft)

    if mod is None:
        error(
            errors,
            f"{path.name}: Quellmod nicht eindeutig "
            "im aktuellen status.json gefunden",
        )
        return

    if draft.get("game_version") != status.get("game_version"):
        error(
            errors,
            f"{path.name}: Spielversion im Draft "
            f"{draft.get('game_version')!r}, "
            f"Status {status.get('game_version')!r}",
        )

    if (
        draft.get("effective_layers", [])
        != mod.get("effective_layers", [])
    ):
        error(
            errors,
            f"{path.name}: effektive Schichten haben sich geändert: "
            f"{draft.get('effective_layers', [])} -> "
            f"{mod.get('effective_layers', [])}",
        )

    current = {}

    for source_name in ("missing", "blank"):
        for entry in mod.get(source_name, []):
            current[identity(entry)] = entry

    draft_needed = {}

    for entry in draft.get("entries", []):
        if not entry.get("needed", True):
            continue

        entry_id = identity(entry)

        if entry_id in draft_needed:
            error(
                errors,
                f"{path.name}: doppelter Draft-Eintrag "
                f"{entry_id[0]}/{entry_id[1]}",
            )
            continue

        draft_needed[entry_id] = entry

    missing_in_draft = sorted(
        set(current) - set(draft_needed)
    )

    stale_in_draft = sorted(
        set(draft_needed) - set(current)
    )

    for category, key in missing_in_draft:
        error(
            errors,
            f"{path.name}: neuer offener Quell-Key fehlt im Draft: "
            f"{category}/{key}; './pzgt draft "
            f"{draft.get('mod_id')}' erneut ausführen",
        )

    for category, key in stale_in_draft:
        error(
            errors,
            f"{path.name}: Draft markiert Key noch als benötigt, "
            f"der aktuell nicht mehr offen ist: {category}/{key}; "
            f"'./pzgt draft {draft.get('mod_id')}' erneut ausführen",
        )

    for entry_id in sorted(
        set(current) & set(draft_needed)
    ):
        source = current[entry_id]
        draft_entry = draft_needed[entry_id]

        if (
            draft_entry.get("english")
            != source.get("english_or_german")
        ):
            category, key = entry_id

            error(
                errors,
                f"{path.name}: englischer Quelltext geändert: "
                f"{category}/{key}; './pzgt draft "
                f"{draft.get('mod_id')}' erneut ausführen",
            )


def analyze_draft(path, data, errors):
    needed = [
        entry
        for entry in data.get("entries", [])
        if entry.get("needed", True)
    ]

    if not needed:
        return {
            "complete": False,
            "needed": 0,
            "translated": 0,
            "open": 0,
            "review": 0,
        }

    translated = 0
    open_count = 0
    review_count = 0
    seen = set()

    for entry in needed:
        for field in (
            "category",
            "key",
            "english",
            "german",
        ):
            if field not in entry:
                error(
                    errors,
                    f"{path.name}: Feld {field!r} fehlt",
                )
                continue

        entry_id = identity(entry)

        if entry_id in seen:
            error(
                errors,
                f"{path.name}: doppelter Key "
                f"{entry_id[0]}/{entry_id[1]}",
            )

        seen.add(entry_id)

        german = entry.get("german", "")

        if not isinstance(german, str):
            error(
                errors,
                f"{path.name}: German ist kein String: "
                f"{entry.get('key')}",
            )
            continue

        if not german.strip():
            open_count += 1
        else:
            translated += 1

            source_ph = build_script.placeholders(
                entry.get("english", "")
            )
            target_ph = build_script.placeholders(german)

            if source_ph != target_ph:
                error(
                    errors,
                    f"{path.name}: Placeholder-Abweichung bei "
                    f"{entry.get('category')}/{entry.get('key')}: "
                    f"EN={dict(source_ph)} DE={dict(target_ph)}",
                )

        if entry.get("review", False):
            review_count += 1

    complete = (
        bool(needed)
        and open_count == 0
        and review_count == 0
    )

    return {
        "complete": complete,
        "needed": len(needed),
        "translated": translated,
        "open": open_count,
        "review": review_count,
    }


def collect_expected(drafts, states, errors):
    categories = defaultdict(dict)
    plain_files = {}
    owners = {}

    included = []

    for path, data in drafts:
        state = states[path]

        if not state["complete"]:
            continue

        included.append(path)

        owner = (
            data.get("mod_id")
            or data.get("directory")
            or path.name
        )

        for entry in data.get("entries", []):
            if not entry.get("needed", True):
                continue

            category = entry["category"]
            key = entry["key"]
            german = entry["german"]

            if category == "__plain__":
                rel = Path(key)

                if rel.is_absolute() or ".." in rel.parts:
                    error(
                        errors,
                        f"{path.name}: unsicherer Plain-Pfad {key}",
                    )
                    continue

                ident = ("plain", str(rel))

                if ident in owners:
                    error(
                        errors,
                        f"Doppelter Plain-Eintrag {key}: "
                        f"{owners[ident]} / {owner}",
                    )
                    continue

                owners[ident] = owner
                plain_files[rel] = german.rstrip() + "\n"
                continue

            rel = Path(category + ".json")

            if rel.is_absolute() or ".." in rel.parts:
                error(
                    errors,
                    f"{path.name}: unsichere Kategorie {category}",
                )
                continue

            ident = (category, key)

            if ident in owners:
                error(
                    errors,
                    f"Doppelter Translation-Key "
                    f"{category}/{key}: "
                    f"{owners[ident]} / {owner}",
                )
                continue

            owners[ident] = owner
            categories[category][key] = german

    expected = {}

    for category, entries in sorted(categories.items()):
        rel = Path(category + ".json")

        expected[rel] = (
            json.dumps(
                dict(sorted(entries.items())),
                ensure_ascii=False,
                indent=4,
            )
            + "\n"
        )

    for rel, content in plain_files.items():
        expected[rel] = content

    return expected, included


def verify_runtime(expected, errors):
    actual = {}

    if DE_ROOT.is_dir():
        for path in sorted(DE_ROOT.rglob("*")):
            if not path.is_file():
                continue

            actual[path.relative_to(DE_ROOT)] = path

    expected_names = set(expected)
    actual_names = set(actual)

    for rel in sorted(expected_names - actual_names):
        error(
            errors,
            f"Runtime-Datei fehlt: {rel}",
        )

    for rel in sorted(actual_names - expected_names):
        error(
            errors,
            f"Veraltete/unerwartete Runtime-Datei: {rel}",
        )

    modified = 0

    for rel in sorted(expected_names & actual_names):
        try:
            content = actual[rel].read_text(
                encoding="utf-8"
            )
        except OSError as exc:
            error(
                errors,
                f"Runtime-Datei nicht lesbar {rel}: {exc}",
            )
            continue

        if content != expected[rel]:
            modified += 1
            error(
                errors,
                f"Runtime-Datei stimmt nicht mit Drafts überein: "
                f"{rel}; './pzgt build <fertige MOD-ID>' ausführen",
            )

    return {
        "expected": len(expected_names),
        "actual": len(actual_names),
        "modified": modified,
    }


def expected_mod_info():
    return (
        f"name={build_script.MOD_NAME}\n"
        f"id={build_script.MOD_ID}\n"
        "author=ElHanko\n"
        "description=German translations for Project Zomboid mods\n"
        "modversion=0.1\n"
        "versionMin=42.0\n"
    )


def verify_mod_info(errors):
    expected = expected_mod_info()
    ok = 0

    for rel in (
        Path("common/mod.info"),
        Path("42/mod.info"),
    ):
        path = ROOT / rel

        if not path.is_file():
            error(errors, f"{rel} fehlt")
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            error(errors, f"{rel} nicht lesbar: {exc}")
            continue

        if content != expected:
            error(
                errors,
                f"{rel} entspricht nicht dem erwarteten Build",
            )
            continue

        ok += 1

    return ok


def main():
    errors = []

    print("Project Zomboid Translation Verify")
    print()

    status = load_status(errors)

    drafts = build_script.load_drafts()

    if not drafts:
        error(errors, "Keine Drafts vorhanden")

    states = {}

    for path, data in drafts:
        states[path] = analyze_draft(
            path,
            data,
            errors,
        )

        if status is not None:
            validate_source_sync(
                path,
                data,
                status,
                errors,
            )

    expected, included = collect_expected(
        drafts,
        states,
        errors,
    )

    runtime = verify_runtime(
        expected,
        errors,
    )

    mod_info_ok = verify_mod_info(errors)

    totals = Counter()

    for state in states.values():
        totals["needed"] += state["needed"]
        totals["translated"] += state["translated"]
        totals["open"] += state["open"]
        totals["review"] += state["review"]

        if state["complete"]:
            totals["complete_drafts"] += 1
        else:
            totals["incomplete_drafts"] += 1

    print()
    print("Drafts:")
    print(f"  Insgesamt:          {len(drafts)}")
    print(f"  Build-fertig:       {totals['complete_drafts']}")
    print(f"  Unvollständig:      {totals['incomplete_drafts']}")
    print(f"  Benötigte Einträge: {totals['needed']}")
    print(f"  Übersetzt:          {totals['translated']}")
    print(f"  Offen:              {totals['open']}")
    print(f"  Review:             {totals['review']}")

    print()
    print("Runtime:")
    print(f"  Erwartete Dateien:  {runtime['expected']}")
    print(f"  Vorhandene Dateien: {runtime['actual']}")
    print(f"  Abweichend:         {runtime['modified']}")
    print(f"  mod.info OK:        {mod_info_ok}/2")

    print()
    print("Enthaltene fertige Drafts:")

    for path in included:
        print(f"  {path.name}")

    print()

    if errors:
        print(f"Ergebnis: FEHLER ({len(errors)})")
        raise SystemExit(1)

    print("Ergebnis: OK")


if __name__ == "__main__":
    main()
