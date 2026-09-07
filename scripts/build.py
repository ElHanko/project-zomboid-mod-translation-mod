#!/usr/bin/env python3
"""Plan deterministic PZ output before replacing any selected language."""
from collections import defaultdict
from pathlib import Path
import json

import config
from common import (load_drafts, require_known, select_draft, translation_state,
                    validate_draft, safe_relative, read_tree, replace_outputs, no_symlinks, placeholders)
from progress import state as draft_state

MOD_ID = "ElHankoModTranslations"
MOD_NAME = "ElHanko Mod Translations"


def expected_mod_info():
    return (f"name={MOD_NAME}\n"
            f"id={MOD_ID}\n"
            "author=ElHanko\n"
            "description=Translations for Project Zomboid mods\n"
            "modversion=0.1\n"
            "versionMin=42.0\n").encode("utf-8")


def is_buildable(path, data, language):
    return draft_state(path, data, language)["complete"]


def collect_expected(drafts, language):
    """Plan finished entries; report complete/incomplete drafts separately."""
    categories = defaultdict(dict)
    plain_files = {}
    owners = {}
    shared_texts = {}
    complete = []
    incomplete = []
    for path, data in sorted(drafts, key=lambda item: item[0].name):
        validate_draft(path, data)
        require_known(data, language)
        if not is_buildable(path, data, language):
            incomplete.append(path)
        else:
            complete.append(path)
        owner = data.get("mod_id") or data.get("directory") or path.name
        for entry in data["entries"]:
            state = translation_state(entry, language)
            if (state["needed"] is not True or not state["text"].strip() or state["review"]
                    or placeholders(entry["english"]) != placeholders(state["text"])):
                continue
            category, key = entry["category"], entry["key"]
            text = state["text"]
            if category == "__plain__":
                rel = safe_relative(key)
                ident = ("__plain__", str(rel))
                value = text.rstrip() + "\n"
                texts = value
            else:
                ident = (category, key)
                texts = (entry["english"], text)
            if ident in owners:
                if owner in owners[ident] or shared_texts[ident] != texts:
                    raise ValueError(f"Doppelter Übersetzungseintrag/Konflikt ({language}): {ident}; "
                                     f"{sorted(owners[ident])} / {owner}")
                owners[ident].add(owner)
                continue
            owners[ident] = {owner}
            shared_texts[ident] = texts
            if category == "__plain__":
                plain_files[rel] = value.encode("utf-8")
            else:
                categories[category][key] = text
    expected = {}
    for category, entries in sorted(categories.items()):
        expected[safe_relative(category + ".json")] = (json.dumps(dict(sorted(entries.items())),
            ensure_ascii=False, indent=4) + "\n").encode("utf-8")
    for rel, value in plain_files.items():
        if rel in expected:
            raise ValueError(f"Plain-/JSON-Zielkollision: {rel}")
        expected[rel] = value
    # File-vs-directory collisions must fail during planning, even for export.
    names = {str(p).casefold() for p in expected}
    if len(names) != len(expected):
        raise ValueError("Runtime-Pfade kollidieren ohne Beachtung der Großschreibung")
    for path in expected:
        if any(str(parent).casefold() in names for parent in path.parents):
            raise ValueError(f"Runtime-Datei kollidiert mit Verzeichnis: {path}")
    return expected, complete, incomplete


def build(drafts, languages):
    plans = {language: collect_expected(drafts, language) for language in languages}
    # Replace the Translate tree once, preserving explicitly unselected languages.
    actual = read_tree(config.TRANSLATE)
    output = {rel: content for rel, content in actual.items() if rel.parts[0] not in languages}
    for language, (expected, _, _) in plans.items():
        output.update({Path(language) / rel: content for rel, content in expected.items()})
    outputs = {}
    if actual != output:
        outputs[config.TRANSLATE] = output
    for rel in ("common/mod.info", "42/mod.info"):
        path = config.ROOT / rel
        no_symlinks(path)
        if not path.is_file() or path.read_bytes() != expected_mod_info():
            outputs[path] = expected_mod_info()
    if outputs:
        replace_outputs(outputs)
    for language, (expected, complete, incomplete) in plans.items():
        print(f"Build {language}: OK | {len(complete)} fertige Drafts | {len(incomplete)} unvollständige Drafts | {len(expected)} Dateien")
    return plans


def run(selector=None, language=None):
    drafts = load_drafts()
    languages = config.selected_languages(language)
    if selector:
        path, draft = select_draft(drafts, selector)
        for target in languages:
            require_known(draft, target)
            if not is_buildable(path, draft, target):
                raise ValueError(f"{selector}: Draft für {target} nicht vollständig")
    build(drafts, languages)


if __name__ == "__main__":
    config.configure()
    run()
