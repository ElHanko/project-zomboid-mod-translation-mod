#!/usr/bin/env python3
"""Review draft audits and source-change flags without reading live sources."""
import config
from common import (AUDIT_TYPES, is_music_entry, is_sfx_entry, load_drafts,
                    placeholders, select_draft, translation_state, write_json)


def run(
        selector,
        language,
        audit_type,
        category=None,
        *,
        needed,
        include_music=False,
        include_sfx=False,
):
    language = config.select_language(language)
    if audit_type not in AUDIT_TYPES:
        raise ValueError(f"Ungültiger Audittyp: {audit_type}; erlaubt: {', '.join(AUDIT_TYPES)}")
    path, draft = select_draft(load_drafts(), selector)
    if draft.get("source_type") != "game":
        raise ValueError("review ist nur für Basis-Spiel-Audit-Einträge verfügbar")
    states = [translation_state(entry, language) for entry in draft["entries"]
              if (include_music or not is_music_entry(entry))
              and (include_sfx or not is_sfx_entry(entry))
              and translation_state(entry, language).get("audit") == audit_type
              and (category is None or entry["category"] == category)]
    if not states:
        raise ValueError(f"Keine passenden Audit-Kandidaten: {audit_type} / "
                         f"{category if category is not None else 'alle'}")
    changed = 0
    already = 0
    for state in states:
        if state["needed"] is needed and state.get("reviewed", 0) == 1:
            already += 1
            continue
        state["needed"] = needed
        state["reviewed"] = 1
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
    print(f"{'Bereits ' + decision + ':':24}{already:6}")
    print(f"{'Geändert:':24}{changed:6}")


def show_entry(entry, state, language, position, total, audit_type):
    print(f"\n[{position + 1}/{total}] {entry['category']} / {entry['key']}\n")
    if audit_type:
        print(f"Audit:   {audit_type}")
    needed_text = {True: "ja", False: "nein", None: "unbekannt"}[state["needed"]]
    print(f"Needed:   {needed_text}")
    print(f"Reviewed: {'ja' if state.get('reviewed', 0) == 1 else 'nein'}")
    print(f"Review:   {'ja' if state['review'] else 'nein'}")
    if audit_type:
        print(f"\nEN:\n{entry['english']}")
        official = "<leer>" if audit_type == "blank_target" else entry["english"]
        print(f"\nOffizielles {language} (laut Audit):\n{official}")
    else:
        print(f"\nVorheriges EN:\n{state.get('previous_english', '—')}")
        print(f"\nAktuelles EN:\n{entry['english']}")
    print(f"\nEigene Übersetzung:\n{state['text'] if state['text'].strip() else '—'}\n")
    if audit_type:
        print("[n] benötigt\n[x] nicht benötigt\n[t] direkt übersetzen")
    else:
        print("[a] Übersetzung bestätigen\n[t] Übersetzung ändern")
    print("[s] überspringen\n[q] beenden\n")


def valid_translation(text, english):
    if not text.strip():
        print("Übersetzung ist leer; keine Änderung.")
        return False
    if placeholders(text) != placeholders(english):
        print("Placeholder-Abweichung zum aktuellen EN-Text; keine Änderung.")
        return False
    return True


def run_interactive(
        selector,
        language=None,
        audit_type=None,
        category=None,
        *,
        offset=0,
        include_reviewed=False,
        include_music=False,
        include_sfx=False,
):
    language = config.select_language(language)
    if audit_type is not None and audit_type not in AUDIT_TYPES:
        raise ValueError(f"Ungültiger Audittyp: {audit_type}")
    if offset < 0:
        raise ValueError("--offset muss >= 0 sein")
    path, draft = select_draft(load_drafts(), selector)
    if audit_type is not None and draft.get("source_type") != "game":
        raise ValueError("review ist nur für Basis-Spiel-Audit-Einträge verfügbar")
    candidates = []
    for entry in draft["entries"]:
        if not include_music and is_music_entry(entry):
            continue
        if not include_sfx and is_sfx_entry(entry):
            continue
        state = translation_state(entry, language)
        if audit_type is not None:
            matches = (
                state.get("audit") == audit_type
                and (include_reviewed or state.get("reviewed", 0) == 0)
            )
        else:
            matches = state["review"] is True
        if matches and (category is None or entry["category"] == category):
            candidates.append(entry)
    if not candidates:
        raise ValueError(f"Keine passenden {'Audit-Kandidaten' if audit_type else 'Review-Einträge'}: "
                         f"{category if category is not None else 'alle'}")
    if offset >= len(candidates):
        raise ValueError(f"--offset liegt außerhalb der Kandidatenliste (0–{len(candidates) - 1})")
    name = draft.get("mod_id") or draft.get("name") or path.name
    print(f"Review {name} ({language})")
    position, changed = offset, 0
    stopped = False
    try:
        while position < len(candidates):
            entry = candidates[position]
            state = translation_state(entry, language)
            show_entry(entry, state, language, position, len(candidates), audit_type)
            choice = input("> ").strip().lower()
            before = dict(state)
            if choice == "q":
                stopped = True
                break
            if choice in ("n", "x") and audit_type:
                state["needed"] = choice == "n"
                state["reviewed"] = 1
            elif choice == "t":
                text = input("Übersetzung (leer = abbrechen):\n> ")
                if not valid_translation(text, entry["english"]):
                    continue
                state.update(text=text, review=False, reviewed=1)
                state.pop("previous_english", None)
                if audit_type:
                    state["needed"] = True
            elif choice == "a" and audit_type is None:
                if not valid_translation(state["text"], entry["english"]):
                    continue
                state["review"] = False
                state["reviewed"] = 1
                state.pop("previous_english", None)
            elif choice != "s":
                print("Ungültige Auswahl; bitte eine der angezeigten Tasten verwenden.")
                continue
            changed += state != before
            position += 1
    except (KeyboardInterrupt, EOFError):
        print()
        stopped = True
    if changed:
        write_json(path, draft)
        print("Zwischenstand gespeichert." if stopped else "Änderungen gespeichert.")
    else:
        print("Keine Änderungen.")
    print(f"Geändert: {changed}")
    if stopped:
        if audit_type:
            resume = (
                position
                if include_reviewed
                else sum(
                    translation_state(entry, language).get("reviewed", 0) == 0
                    for entry in candidates[:position]
                )
            )
        else:
            # Confirmed reviews disappear from the next session's filtered list.
            resume = sum(
                translation_state(entry, language)["review"] is True
                for entry in candidates[:position]
            )
        print(f"Fortsetzen mit --offset {resume}")
