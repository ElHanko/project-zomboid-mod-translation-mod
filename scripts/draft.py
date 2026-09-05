#!/usr/bin/env python3

from pathlib import Path
import json
import re
import sys


ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "data" / "status.json"
TRANSLATIONS = ROOT / "translations"


def die(message):
    print(f"FEHLER: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_status():
    if not STATUS.is_file():
        die(
            f"{STATUS} fehlt. "
            "Zuerst './pzgt status' ausführen."
        )

    try:
        return json.loads(
            STATUS.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        die(f"{STATUS} ist ungültig: {exc}")


def safe_filename(workshop_id, mod_id, directory):
    source = mod_id or directory

    safe = re.sub(
        r"[^A-Za-z0-9._-]+",
        "__",
        source,
    ).strip("_")

    return f"{workshop_id}__{safe}.json"


def draft_path_for_mod(mod):
    return (
        TRANSLATIONS
        / safe_filename(
            mod["workshop_id"],
            mod.get("mod_id"),
            mod["directory"],
        )
    )


def find_mod(data, selector):
    folded = selector.casefold()

    matches = []

    for mod in data["mods"]:
        candidates = {
            str(mod.get("mod_id") or ""),
            str(mod.get("directory") or ""),
            str(mod.get("name") or ""),
        }

        if any(
            candidate.casefold() == folded
            for candidate in candidates
            if candidate
        ):
            matches.append(mod)

    if not matches:
        die(f"Kein Mod gefunden: {selector}")

    if len(matches) > 1:
        print(
            f"FEHLER: Mehrere Mods passen auf {selector!r}:",
            file=sys.stderr,
        )

        for mod in matches:
            print(
                f"  {mod.get('mod_id') or '-'} "
                f"({mod['workshop_id']}, {mod['directory']})",
                file=sys.stderr,
            )

        raise SystemExit(1)

    return matches[0]


def entry_identity(entry):
    return (
        entry["category"],
        entry["key"],
    )


def load_existing(path):
    if not path.is_file():
        return None

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        die(
            f"Bestehender Draft ist ungültig: "
            f"{path}: {exc}"
        )


def draft_entries_from_status(mod):
    result = []

    for source_name in ("missing", "blank"):
        for entry in mod.get(source_name, []):
            result.append(
                {
                    "category": entry["category"],
                    "key": entry["key"],
                    "english": entry[
                        "english_or_german"
                    ],
                    "german": "",
                    "source_file": entry["file"],
                    "source_layer": entry["layer"],
                    "source_format": entry["format"],
                    "needed": True,
                    "review": False,
                }
            )

    return result


def merge_existing(current, existing):
    if not existing:
        return current

    old_by_id = {
        entry_identity(entry): entry
        for entry in existing.get("entries", [])
        if (
            "category" in entry
            and "key" in entry
        )
    }

    current_ids = set()
    merged = []

    for entry in current:
        ident = entry_identity(entry)
        current_ids.add(ident)

        old = old_by_id.get(ident)

        if old is None:
            merged.append(entry)
            continue

        new = dict(entry)

        new["german"] = old.get("german", "")

        old_english = old.get("english", "")

        if old_english != entry["english"]:
            new["review"] = True

            if old_english:
                new["previous_english"] = old_english

        else:
            new["review"] = bool(
                old.get("review", False)
            )

            if "previous_english" in old:
                new["previous_english"] = (
                    old["previous_english"]
                )

        merged.append(new)

    # Alte Einträge erhalten, falls der Quellmod inzwischen
    # selbst Deutsch mitbringt oder der Key entfernt wurde.
    for ident, old in old_by_id.items():
        if ident in current_ids:
            continue

        preserved = dict(old)
        preserved["needed"] = False
        merged.append(preserved)

    return merged


def write_draft(mod):
    TRANSLATIONS.mkdir(
        parents=True,
        exist_ok=True,
    )

    out = draft_path_for_mod(mod)

    current = draft_entries_from_status(mod)
    existing = load_existing(out)

    entries = merge_existing(
        current,
        existing,
    )

    payload = {
        "game_version": load_game_version(mod),
        "workshop_id": mod["workshop_id"],
        "mod_id": mod.get("mod_id"),
        "directory": mod["directory"],
        "name": mod.get("name"),
        "effective_layers": mod.get(
            "effective_layers",
            [],
        ),
        "entries": entries,
    }

    out.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    needed = [
        entry
        for entry in entries
        if entry.get("needed", True)
    ]

    translated = [
        entry
        for entry in needed
        if entry.get("german", "").strip()
    ]

    review = [
        entry
        for entry in needed
        if entry.get("review", False)
    ]

    return {
        "path": out,
        "needed": len(needed),
        "translated": len(translated),
        "open": (
            len(needed)
            - len(translated)
        ),
        "review": len(review),
        "created": existing is None,
    }


STATUS_GAME_VERSION = None


def load_game_version(mod):
    # Wird in main einmal aus status.json gesetzt.
    return STATUS_GAME_VERSION


def print_one(mod, result):
    print(mod.get("name") or mod["directory"])
    print(
        f"Mod-ID:       "
        f"{mod.get('mod_id') or '-'}"
    )
    print(
        f"Workshop:     {mod['workshop_id']}"
    )
    print(
        "Schichten:    "
        + " + ".join(
            mod.get("effective_layers", [])
        )
    )
    print()
    print(
        f"Benötigt:     {result['needed']}"
    )
    print(
        f"Übersetzt:    {result['translated']}"
    )
    print(
        f"Offen:        {result['open']}"
    )
    print(
        f"Review:       {result['review']}"
    )
    print()
    print(f"Draft: {result['path']}")


def draft_all(data):
    selected = []

    for mod in data["mods"]:
        out = draft_path_for_mod(mod)

        open_count = (
            mod.get("counts", {})
            .get("open", 0)
        )

        # Neue Drafts nur für Mods mit offenen Einträgen.
        # Bestehende Drafts immer aktualisieren, damit z.B.
        # inzwischen offizielle DE-Übersetzungen needed=false
        # setzen können.
        if open_count <= 0 and not out.is_file():
            continue

        selected.append(mod)

    results = []

    for mod in selected:
        result = write_draft(mod)
        results.append((mod, result))

    created = sum(
        1
        for _, result in results
        if result["created"]
    )

    updated = len(results) - created

    needed = sum(
        result["needed"]
        for _, result in results
    )

    translated = sum(
        result["translated"]
        for _, result in results
    )

    review = sum(
        result["review"]
        for _, result in results
    )

    print("Drafts aktualisiert")
    print()
    print(f"Drafts gesamt:  {len(results)}")
    print(f"Neu:            {created}")
    print(f"Aktualisiert:   {updated}")
    print()
    print(f"Benötigt:       {needed}")
    print(f"Übersetzt:      {translated}")
    print(f"Offen:          {needed - translated}")
    print(f"Review:         {review}")
    print()
    print(f"Verzeichnis: {TRANSLATIONS}")


def main():
    global STATUS_GAME_VERSION

    if len(sys.argv) != 2:
        die(
            "Verwendung:\n"
            "  draft.py MOD-ID\n"
            "  draft.py --all"
        )

    selector = sys.argv[1]

    data = load_status()
    STATUS_GAME_VERSION = data["game_version"]

    if selector == "--all":
        draft_all(data)
        return

    mod = find_mod(
        data,
        selector,
    )

    result = write_draft(mod)

    print_one(
        mod,
        result,
    )


if __name__ == "__main__":
    main()
