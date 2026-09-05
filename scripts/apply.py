#!/usr/bin/env python3

from pathlib import Path
import json
import sys

import build as build_script


ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS = ROOT / "translations"


def die(message):
    print(f"FEHLER: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path):
    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        die(f"{path} kann nicht gelesen werden: {exc}")


def identity(entry):
    return (
        entry.get("category"),
        entry.get("key"),
    )


def main():
    if len(sys.argv) != 2:
        die("Verwendung: apply.py WORK-DATEI")

    work_path = Path(sys.argv[1]).expanduser()

    if not work_path.is_absolute():
        work_path = (
            Path.cwd() / work_path
        ).resolve()

    if not work_path.is_file():
        die(f"Work-Datei fehlt: {work_path}")

    work = load_json(work_path)

    draft_name = work.get("draft_file")

    if (
        not isinstance(draft_name, str)
        or Path(draft_name).name != draft_name
    ):
        die("Ungültiges draft_file im Arbeitspaket")

    draft_path = TRANSLATIONS / draft_name

    if not draft_path.is_file():
        die(f"Draft fehlt: {draft_path}")

    draft = load_json(draft_path)

    # Metadaten müssen zum Draft passen.
    for field in (
        "workshop_id",
        "mod_id",
        "directory",
    ):
        if work.get(field) != draft.get(field):
            die(
                f"Arbeitspaket passt nicht zum Draft: "
                f"{field}"
            )

    draft_entries = {}

    for entry in draft.get("entries", []):
        ident = identity(entry)

        if ident in draft_entries:
            die(
                f"Doppelter Draft-Key: "
                f"{ident[0]}/{ident[1]}"
            )

        draft_entries[ident] = entry

    applied = 0
    skipped = 0

    for item in work.get("entries", []):
        ident = identity(item)

        target = draft_entries.get(ident)

        if target is None:
            die(
                "Key aus Arbeitspaket existiert nicht mehr: "
                f"{ident[0]}/{ident[1]}"
            )

        if not target.get("needed", True):
            die(
                "Key wird im Draft nicht mehr benötigt: "
                f"{ident[0]}/{ident[1]}"
            )

        if item.get("english") != target.get("english"):
            die(
                "Englischer Quelltext hat sich geändert: "
                f"{ident[0]}/{ident[1]}\n"
                "Zuerst './pzgt status' und "
                "'./pzgt draft --all' ausführen."
            )

        german = item.get("german", "")

        if not isinstance(german, str):
            die(
                f"DE ist kein String: "
                f"{ident[0]}/{ident[1]}"
            )

        if not german.strip():
            skipped += 1
            continue

        source_ph = build_script.placeholders(
            target["english"]
        )

        target_ph = build_script.placeholders(
            german
        )

        if source_ph != target_ph:
            die(
                "Placeholder-Abweichung bei "
                f"{ident[0]}/{ident[1]}\n"
                f"  EN: {dict(source_ph)}\n"
                f"  DE: {dict(target_ph)}"
            )

        target["german"] = german
        target["review"] = False
        target.pop("previous_english", None)

        applied += 1

    tmp = draft_path.with_suffix(
        draft_path.suffix + ".tmp"
    )

    tmp.write_text(
        json.dumps(
            draft,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    tmp.replace(draft_path)

    needed = [
        entry
        for entry in draft.get("entries", [])
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

    print(
        draft.get("name")
        or draft.get("mod_id")
        or draft_path.name
    )
    print()
    print(f"Übernommen:   {applied}")
    print(f"Leer gelassen:{skipped:4}")
    print()
    print(f"Benötigt:     {len(needed)}")
    print(f"Übersetzt:    {len(translated)}")
    print(f"Offen:        {len(needed) - len(translated)}")
    print(f"Review:       {len(review)}")
    print()
    print(f"Draft: {draft_path}")


if __name__ == "__main__":
    main()
