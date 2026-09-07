#!/usr/bin/env python3
"""Record a need decision for existing base-game audit candidates."""
import config
from common import AUDIT_TYPES, load_drafts, select_draft, translation_state, write_json


def run(selector, language, audit_type, category=None, *, needed):
    language = config.select_language(language)
    if audit_type not in AUDIT_TYPES:
        raise ValueError(f"Ungültiger Audittyp: {audit_type}; erlaubt: {', '.join(AUDIT_TYPES)}")
    path, draft = select_draft(load_drafts(), selector)
    if draft.get("source_type") != "game":
        raise ValueError("review ist nur für Basis-Spiel-Audit-Einträge verfügbar")
    states = [translation_state(entry, language) for entry in draft["entries"]
              if translation_state(entry, language).get("audit") == audit_type
              and (category is None or entry["category"] == category)]
    if not states:
        raise ValueError(f"Keine passenden Audit-Kandidaten: {audit_type} / "
                         f"{category if category is not None else 'alle'}")
    changed = 0
    for state in states:
        if state["needed"] is not needed:
            state["needed"] = needed
            changed += 1
    if changed:
        write_json(path, draft)
    name = draft.get("mod_id") or draft.get("name") or path.name
    decision = "benötigt" if needed else "nicht benötigt"
    print(f"Review {name} ({language})")
    print(f"Audittyp: {audit_type}")
    print(f"Kategorie: {category if category is not None else 'alle'}")
    print(f"Entscheidung: {decision}\n")
    print(f"{'Passend:':24}{len(states):6}")
    print(f"{'Bereits ' + decision + ':':24}{len(states) - changed:6}")
    print(f"{'Geändert:':24}{changed:6}")
