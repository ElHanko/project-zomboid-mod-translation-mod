#!/usr/bin/env python3
"""Validate a whole package before committing any durable translation changes."""
from copy import deepcopy
from pathlib import Path

import config
from build import placeholders
from common import index_entries, load_drafts, load_json, translation_state, write_json


def apply_work(work, drafts):
    if not isinstance(work, dict) or not isinstance(work.get("entries"), list):
        raise ValueError("Ungültiges Arbeitspaket")
    if not isinstance(work.get("language"), str):
        raise ValueError("Arbeitspaket ohne Sprache; mit ./pzgt work neu erzeugen")
    language = config.select_language(work["language"])
    found = [(path, draft) for path, draft in drafts if path.name == work.get("draft_file")]
    if len(found) != 1:
        raise ValueError("draft_file verweist nicht auf genau einen existierenden Draft")
    path, original = found[0]
    for field in ("workshop_id", "mod_id", "directory"):
        if work.get(field) != original.get(field):
            raise ValueError(f"Arbeitspaket passt nicht zum Draft: {field}")
    draft = deepcopy(original)
    targets = index_entries(draft["entries"])
    applied = 0
    for ident, item in index_entries(work["entries"]).items():
        target = targets.get(ident)
        if target is None:
            raise ValueError(f"Key existiert nicht mehr: {ident}")
        text = item.get("translation")
        if not isinstance(text, str):
            raise ValueError(f"Translation muss String sein: {ident}")
        if not text.strip():
            continue
        state = translation_state(target, language)
        if state["needed"] is not True:
            raise ValueError(f"Key nicht benötigt oder Bedarf unbekannt: {language}/{ident}; "
                             f"./pzgt status --language {language} und ./pzgt draft --all ausführen")
        if item.get("english") != target["english"]:
            raise ValueError(f"Englischer Quelltext inzwischen geändert: {ident}")
        if item.get("original_translation") != state["text"]:
            raise ValueError(f"Zielübersetzung inzwischen geändert: {ident}; neues Arbeitspaket erstellen")
        if placeholders(text) != placeholders(target["english"]):
            raise ValueError(f"Placeholder-Abweichung: {ident}")
        state.update(text=text, review=False)
        state.pop("previous_english", None)
        applied += 1
    return path, draft, applied


def run(filename):
    path, draft, count = apply_work(load_json(Path(filename).expanduser()), load_drafts())
    if count:
        write_json(path, draft)
    print(f"Übernommen: {count}; Draft: {path}")


if __name__ == "__main__":
    import sys
    config.configure()
    run(sys.argv[1])
