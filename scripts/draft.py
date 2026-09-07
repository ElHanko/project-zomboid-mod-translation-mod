#!/usr/bin/env python3
"""Refresh one language's requirements while preserving all translation text."""
from copy import deepcopy
import re

import config
from common import (AUDIT_TYPES, entry_identity, index_audits, index_entries, load_drafts, load_json,
                    matches, validate_draft, write_json)


def safe_filename(workshop_id, mod_id, directory):
    safe = re.sub(r"[^A-Za-z0-9._-]+", "__", mod_id or directory).strip("_")
    if not str(workshop_id).isdigit() or not safe:
        raise ValueError("Ungültige Workshop-/Mod-Identität")
    return f"{workshop_id}__{safe}.json"


def draft_path_for_mod(mod):
    return config.TRANSLATIONS / safe_filename(mod["workshop_id"], mod.get("mod_id"), mod["directory"])


def merge_entries(mod, previous, language):
    sources = index_entries(mod["english"])
    needed = set(index_entries(mod["missing"] + mod["blank"]))
    is_game = mod.get("source_type") == "game"
    audits = index_audits(mod, language) if is_game else {}
    tracked = needed | audits.keys()
    if not tracked <= sources.keys():
        raise ValueError("Status enthält benötigte/Audit-Einträge ohne englische Quelle")
    old = index_entries(previous)
    # Keep stable ordering and history; append new requirements and audit sources.
    identities = list(old) + [ident for ident in sources
                              if ident in tracked and ident not in old]
    result = []
    for ident in identities:
        before = old.get(ident)
        source = sources.get(ident)
        entry = deepcopy(before) if before else {"translations": {}}
        if source is not None:
            if before and before["english"] != source["text"]:
                for state in entry["translations"].values():
                    state["review"] = True
                    state.setdefault("previous_english", before["english"])
            entry.update(category=source["category"], key=source["key"], english=source["text"],
                         source_file=source["file"], source_layer=source["layer"], source_format=source["format"])
        for target in config.LANGUAGES:
            entry["translations"].setdefault(target, {"text": "", "needed": None, "review": False})
        state = entry["translations"][language]
        if ident in audits:
            # Only an existing audit can carry a deliberate manual release.
            state["needed"] = state.get("audit") in AUDIT_TYPES and state["needed"] is True
            state["audit"] = audits[ident]
        else:
            state["needed"] = ident in needed
            if is_game:
                state.pop("audit", None)
        result.append(entry)
    return result


def run(selector):
    status = load_json(config.DATA / "status.json")
    if not isinstance(status, dict) or not isinstance(status.get("language"), str):
        raise ValueError("Status ohne explizite Sprache; zuerst './pzgt status --language CODE' ausführen")
    language = config.select_language(status["language"])
    if not isinstance(status.get("mods"), list):
        raise ValueError("Ungültiger Status; ./pzgt status erneut ausführen")
    existing = dict(load_drafts(migrate=True))
    # Match sources by Workshop identity, not a potentially colliding filename.
    mods = {}
    known = {(str(data.get("workshop_id")), data.get("directory")) for data in existing.values()
             if data.get("source_type") != "game"}
    for path, data in existing.items():
        if data.get("source_type") == "game":
            if status.get("base_game") is None:
                raise ValueError(f"{path.name}: Basis-Spielquelle fehlt im Status; scan und status erneut ausführen")
            mods[path] = status["base_game"]
            continue
        found = [mod for mod in status["mods"]
                 if (str(mod["workshop_id"]), mod["directory"]) ==
                 (str(data.get("workshop_id")), data.get("directory"))]
        if len(found) > 1:
            raise ValueError(f"{path.name}: Quellmod nicht eindeutig gefunden")
        if found:
            mods[path] = found[0]
    # Draft files define the supported catalogue. Discovery alone never adds mods.
    selected = set(existing)
    if selector != "--all":
        selected = {path for path, data in existing.items()
                    if matches(data, selector) or (path in mods and matches(mods[path], selector))}
        game = status.get("base_game")
        if (game is not None and matches(game, selector)
                and not any(data.get("source_type") == "game" for data in existing.values())):
            path = config.TRANSLATIONS / "__project_zomboid.json"
            if path in existing or path in mods:
                raise ValueError(f"Mehrdeutiger Draft-Dateiname: {path}")
            mods[path] = game
            selected.add(path)
        for mod in status["mods"]:
            if (str(mod["workshop_id"]), mod["directory"]) in known or not matches(mod, selector):
                continue
            path = draft_path_for_mod(mod)
            if path in existing or path in mods:
                raise ValueError(f"Mehrdeutiger Draft-Dateiname: {path}")
            mods[path] = mod
            selected.add(path)
        if len(selected) != 1:
            raise ValueError(f"Kein eindeutiger Mod: {selector}")
    pending = []
    for path in sorted(selected):
        mod = mods.get(path)
        draft = deepcopy(existing.get(path, {"entries": []}))
        if mod is not None:
            if not isinstance(mod.get("english"), list):
                raise ValueError("Alter Status ohne englischen Quellbestand; ./pzgt status erneut ausführen")
            if mod["counts"].get("parse_errors", 0):
                raise ValueError(f"{path.name}: Parserfehler; kein zuverlässiger Status, keine Änderung")
            if mod.get("source_type") == "game":
                draft.update(source_type="game", name=mod["name"])
            else:
                draft.update({field: mod.get(field) for field in
                              ("workshop_id", "mod_id", "directory", "name", "effective_layers")})
            draft["game_version"] = status["game_version"]
            draft["entries"] = merge_entries(mod, draft["entries"], language)
        else:
            # An unavailable mod is not evidence that its translations are obsolete.
            for entry in draft["entries"]:
                for target in config.LANGUAGES:
                    entry["translations"].setdefault(target, {"text": "", "needed": None, "review": False})
            print(f"Hinweis: {path.name}: Quelle lokal nicht vorhanden; nicht aktuell prüfbar, vorhandenen Bedarf erhalten")
        validate_draft(path, draft)
        pending.append((path, draft))
    for path, draft in pending:
        write_json(path, draft)
    print(f"Drafts aktualisiert ({language}): {len(pending)}")


if __name__ == "__main__":
    import sys
    config.configure()
    run(sys.argv[1])
