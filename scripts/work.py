#!/usr/bin/env python3
"""Create a bounded language-specific work package."""
from copy import deepcopy
from pathlib import Path

import config
from common import load_drafts, require_known, select_draft, translation_state, write_json


def work_entries(data, language):
    return [entry for entry in data["entries"]
            if translation_state(entry, language)["needed"] is True
            and (not translation_state(entry, language)["text"].strip()
                 or translation_state(entry, language)["review"])]


def make_work(drafts, selector=None, limit=25, offset=0, language=None):
    language = config.select_language(language)
    for _, draft in drafts:
        require_known(draft, language)
    if limit < 1 or offset < 0:
        raise ValueError("--limit muss positiv und --offset nicht negativ sein")
    if selector:
        path, draft = select_draft(drafts, selector)
    else:
        candidates = [item for item in drafts if work_entries(item[1], language)]
        if not candidates:
            raise ValueError("Keine offenen Übersetzungen mehr vorhanden")
        path, draft = min(candidates, key=lambda item: (len(work_entries(item[1], language)),
                                                       str(item[1].get("mod_id") or item[1].get("name") or item[0].name).casefold()))
    opened = work_entries(draft, language)
    selected = opened[offset:offset + limit]
    if not selected:
        raise ValueError("Für diesen Bereich gibt es keine offenen Einträge")
    entries = []
    for entry in selected:
        item = deepcopy(entry)
        state = translation_state(item, language)
        del item["translations"]
        item.update(translation=state["text"], original_translation=state["text"], review=state["review"])
        if "previous_english" in state:
            item["previous_english"] = state["previous_english"]
        entries.append(item)
    payload = {field: draft[field] for field in
               ("game_version", "workshop_id", "mod_id", "directory", "name", "source_type")
               if field in draft}
    payload.update(language=language, draft_file=path.name, offset=offset,
                   open_total=len(opened), entries=entries)
    return payload


def run(selector=None, limit=25, offset=0, language=None):
    work = make_work(load_drafts(), selector, limit, offset, language)
    out = config.DATA / "work" / (Path(work["draft_file"]).stem + "." + work["language"] + ".work.json")
    write_json(out, work)
    name = work.get("mod_id") or work.get("name") or work["draft_file"]
    print(f"{name} ({work['language']}): {len(work['entries'])} / {work['open_total']} offene Einträge")
    print(f"Arbeitsdatei: {out}")


if __name__ == "__main__":
    config.configure()
    run()
