#!/usr/bin/env python3
"""Summarize the durable language-specific audit inventory without source access."""
from collections import Counter

import config
from common import load_drafts, select_draft, translation_state


def run(selector, language=None, category=None):
    language = config.select_language(language)
    path, draft = select_draft(load_drafts(), selector)
    entries = [entry for entry in draft["entries"]
               if translation_state(entry, language).get("audit") == "blank_target"
               and (category is None or entry["category"] == category)]
    counts = Counter(entry["category"] for entry in entries)
    name = draft.get("mod_id") or draft.get("name") or path.name
    print(f"Audit {name} ({language}): blank_target")
    print(f"{'ANZAHL':>6}  KATEGORIE")
    for name, count in sorted(counts.items()):
        print(f"{count:6}  {name}")
    print(f"Audit-Kandidaten: {len(entries)}")
    print("Davon zur Übersetzung freigegeben: " + str(sum(
        translation_state(entry, language)["needed"] is True for entry in entries)))
