#!/usr/bin/env python3

from pathlib import Path
import argparse
import json
import sys


ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS = ROOT / "translations"
WORK = ROOT / "data" / "work"


def die(message):
    print(f"FEHLER: {message}", file=sys.stderr)
    raise SystemExit(1)


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


def candidates(data):
    return {
        str(data.get("mod_id") or ""),
        str(data.get("directory") or ""),
        str(data.get("name") or ""),
    }


def matches(data, selector):
    folded = selector.casefold()

    return any(
        value.casefold() == folded
        for value in candidates(data)
        if value
    )


def work_entries(data):
    result = []

    for entry in data.get("entries", []):
        if not entry.get("needed", True):
            continue

        german = entry.get("german", "")

        if german.strip() and not entry.get("review", False):
            continue

        result.append(entry)

    return result


def choose_draft(drafts, selector):
    if selector not in (None, "--next"):
        found = [
            item
            for item in drafts
            if matches(item[1], selector)
        ]

        if not found:
            die(f"Kein Draft gefunden: {selector}")

        if len(found) != 1:
            die(f"Mehrere Drafts passen auf: {selector}")

        return found[0]

    unfinished = []

    for path, data in drafts:
        entries = work_entries(data)

        if entries:
            unfinished.append(
                (
                    len(entries),
                    str(data.get("mod_id") or path.name),
                    path,
                    data,
                )
            )

    if not unfinished:
        die("Keine offenen Übersetzungen mehr vorhanden.")

    unfinished.sort(
        key=lambda item: (
            item[0],
            item[1].casefold(),
        )
    )

    _, _, path, data = unfinished[0]

    return path, data


def main():
    parser = argparse.ArgumentParser(
        description="Erzeugt ein Übersetzungs-Arbeitspaket."
    )

    parser.add_argument(
        "selector",
        nargs="?",
        default=None,
        help="MOD-ID",
    )

    parser.add_argument(
        "--next",
        action="store_true",
        help="Kleinsten noch offenen Mod auswählen",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximale Zahl Einträge (Standard: 25)",
    )

    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Startposition innerhalb der offenen Einträge",
    )

    args = parser.parse_args()

    if args.limit < 1:
        die("--limit muss mindestens 1 sein")

    if args.offset < 0:
        die("--offset darf nicht negativ sein")

    if args.next and args.selector is not None:
        die("--next und MOD-ID können nicht zusammen verwendet werden")

    selector = (
        "--next"
        if args.next or args.selector is None
        else args.selector
    )

    drafts = load_drafts()

    path, data = choose_draft(
        drafts,
        selector,
    )

    open_entries = work_entries(data)

    selected = open_entries[
        args.offset:
        args.offset + args.limit
    ]

    if not selected:
        die(
            "Für diesen Bereich gibt es keine offenen Einträge."
        )

    WORK.mkdir(
        parents=True,
        exist_ok=True,
    )

    out = WORK / (
        path.stem + ".work.json"
    )

    entries = []

    for entry in selected:
        item = {
            "category": entry["category"],
            "key": entry["key"],
            "english": entry["english"],
            "german": entry.get("german", ""),
            "source_file": entry.get("source_file"),
            "source_format": entry.get("source_format"),
            "review": bool(entry.get("review", False)),
        }

        if "previous_english" in entry:
            item["previous_english"] = (
                entry["previous_english"]
            )

        entries.append(item)

    payload = {
        "game_version": data.get("game_version"),
        "workshop_id": data.get("workshop_id"),
        "mod_id": data.get("mod_id"),
        "directory": data.get("directory"),
        "name": data.get("name"),
        "draft_file": path.name,
        "offset": args.offset,
        "open_total": len(open_entries),
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

    print(data.get("name") or data.get("mod_id"))
    print(f"Mod-ID:        {data.get('mod_id') or '-'}")
    print(f"Offen gesamt: {len(open_entries)}")
    print(
        f"Arbeitspaket:  {len(entries)} "
        f"(ab Position {args.offset})"
    )
    print()
    print(f"Datei: {out}")

    print()
    print("Einträge:")

    for number, entry in enumerate(
        entries,
        start=args.offset + 1,
    ):
        marker = " [REVIEW]" if entry["review"] else ""

        print()
        print(
            f"{number}. "
            f"{entry['category']}/{entry['key']}"
            f"{marker}"
        )
        print(f"   EN: {entry['english']}")
        print(
            "   DE: "
            + (
                entry["german"]
                if entry["german"]
                else "<offen>"
            )
        )


if __name__ == "__main__":
    main()
