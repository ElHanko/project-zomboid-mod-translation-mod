#!/usr/bin/env python3

from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS = ROOT / "translations"


def die(message):
    print(f"FEHLER: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_drafts():
    drafts = []

    for path in sorted(
        TRANSLATIONS.glob("*.json")
    ):
        try:
            data = json.loads(
                path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            die(
                f"Ungültiger Draft {path}: {exc}"
            )

        drafts.append((path, data))

    return drafts


def state(path, data):
    needed = [
        entry
        for entry in data.get("entries", [])
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
        "path": path,
        "data": data,
        "needed": len(needed),
        "translated": len(translated),
        "open": (
            len(needed)
            - len(translated)
        ),
        "review": len(review),
    }


def matches(data, selector):
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


def print_single(item):
    data = item["data"]

    print(
        data.get("name")
        or data.get("mod_id")
        or item["path"].name
    )

    print(f"Benötigt:   {item['needed']}")
    print(f"Übersetzt:  {item['translated']}")
    print(f"Offen:      {item['open']}")
    print(f"Review:     {item['review']}")
    print()
    print(f"Draft: {item['path']}")


def print_all(items):
    items = sorted(
        items,
        key=lambda item: (
            item["open"],
            item["needed"],
            str(
                item["data"].get("mod_id")
                or item["path"].name
            ),
        ),
        reverse=True,
    )

    print(
        f'{"OFFEN":>6} '
        f'{"DE":>6} '
        f'{"GESAMT":>6} '
        f'{"REV":>5}  '
        f'{"MOD-ID":45} '
        f'NAME'
    )

    print("-" * 125)

    for item in items:
        data = item["data"]

        marker = (
            "✓"
            if (
                item["open"] == 0
                and item["review"] == 0
            )
            else " "
        )

        print(
            f'{item["open"]:6} '
            f'{item["translated"]:6} '
            f'{item["needed"]:6} '
            f'{item["review"]:5} {marker} '
            f'{str(data.get("mod_id") or "-")[:45]:45} '
            f'{data.get("name") or data.get("directory")}'
        )

    needed = sum(
        item["needed"]
        for item in items
    )

    translated = sum(
        item["translated"]
        for item in items
    )

    review = sum(
        item["review"]
        for item in items
    )

    finished = sum(
        1
        for item in items
        if (
            item["open"] == 0
            and item["review"] == 0
        )
    )

    print()
    print("Gesamt:")
    print(f"  Drafts:       {len(items)}")
    print(f"  Fertig:       {finished}")
    print(f"  Benötigt:     {needed}")
    print(f"  Übersetzt:    {translated}")
    print(f"  Offen:        {needed - translated}")
    print(f"  Review:       {review}")


def main():
    drafts = load_drafts()

    if not drafts:
        die("Keine Drafts vorhanden.")

    items = [
        state(path, data)
        for path, data in drafts
    ]

    if len(sys.argv) == 1:
        print_all(items)
        return

    if len(sys.argv) != 2:
        die(
            "Verwendung:\n"
            "  progress.py\n"
            "  progress.py MOD-ID"
        )

    selector = sys.argv[1]

    matches_found = [
        item
        for item in items
        if matches(
            item["data"],
            selector,
        )
    ]

    if not matches_found:
        die(
            f"Kein Draft gefunden: "
            f"{selector}"
        )

    if len(matches_found) > 1:
        die(
            f"Mehrere Drafts passen auf: "
            f"{selector}"
        )

    print_single(matches_found[0])


if __name__ == "__main__":
    main()
