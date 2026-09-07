#!/usr/bin/env python3
"""Summarize the durable language-specific audit inventory without source access."""
from collections import Counter

import config
from common import AUDIT_TYPES, is_music_entry, load_drafts, select_draft, translation_state


def run(selector, language=None, category=None, audit_type=None, *, include_music=False):
    language = config.select_language(language)
    if audit_type is not None and audit_type not in AUDIT_TYPES:
        raise ValueError(f"Ungültiger Audittyp: {audit_type}; erlaubt: {', '.join(AUDIT_TYPES)}")
    path, draft = select_draft(load_drafts(), selector)
    entries = [entry for entry in draft["entries"]
               if (include_music or not is_music_entry(entry))
               and translation_state(entry, language).get("audit") in AUDIT_TYPES
               and (audit_type is None or translation_state(entry, language)["audit"] == audit_type)
               and (category is None or entry["category"] == category)]
    totals = Counter(translation_state(entry, language)["audit"] for entry in entries)
    counts = Counter((entry["category"], translation_state(entry, language)["audit"]) for entry in entries)
    name = draft.get("mod_id") or draft.get("name") or path.name
    print(f"Audit {name} ({language})")
    print()
    print(f"{'ANZAHL':>6}  TYP")
    for name in AUDIT_TYPES:
        print(f"{totals[name]:6}  {name}")
    print(f"{len(entries):6}  gesamt")
    print("\nNach Kategorie:")
    print(f"{'KATEGORIE':24} {'BLANK':>6} {'SAME':>6} {'GESAMT':>7}")
    for name in sorted({entry["category"] for entry in entries}):
        blank, same = counts[name, "blank_target"], counts[name, "same_as_source"]
        print(f"{name:24} {blank:6} {same:6} {blank + same:7}")
    reviewed = sum(
        translation_state(entry, language).get("reviewed", 0) == 1
        for entry in entries
    )
    print(f"Audit-Kandidaten: {len(entries)}")
    print(f"Reviewed:         {reviewed}")
    print(f"Unreviewed:       {len(entries) - reviewed}")
    print("Davon zur Übersetzung freigegeben: " + str(sum(
        translation_state(entry, language)["needed"] is True for entry in entries)))
