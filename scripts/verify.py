#!/usr/bin/env python3
"""Verify draft/source synchronization and exact deterministic runtime bytes."""
from collections import Counter

import config
import status as status_script
from build import collect_expected, expected_mod_info, placeholders
from common import (AUDIT_TYPES, entry_identity, index_audits, index_entries, load_drafts, no_symlinks,
                    read_tree, translation_state)
from progress import state as draft_state


def runtime_errors(expected, directory):
    try:
        actual = read_tree(directory)
    except (OSError, ValueError) as exc:
        return [str(exc)]
    errors = [f"Runtime-Datei fehlt: {rel}" for rel in sorted(expected.keys() - actual.keys())]
    errors += [f"Veraltete/unerwartete Runtime-Datei: {rel}" for rel in sorted(actual.keys() - expected.keys())]
    errors += [f"Runtime-Datei stimmt nicht mit Drafts überein: {rel}"
               for rel in sorted(actual.keys() & expected.keys()) if actual[rel] != expected[rel]]
    return errors


def mod_info_errors():
    errors = []
    for rel in ("common/mod.info", "42/mod.info"):
        path = config.ROOT / rel
        try:
            no_symlinks(path)
            if path.read_bytes() != expected_mod_info():
                errors.append(f"{rel} entspricht nicht dem erwarteten Build")
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    return errors


def source_errors(path, draft, status, language):
    """Return None for an absent Workshop source, otherwise synchronization errors."""
    if status.get("language") != language:
        return [f"Status-Sprache passt nicht zu {language}"]
    is_game = draft.get("source_type") == "game"
    if is_game:
        mod = status.get("base_game")
        if mod is None:
            return [f"{path.name}: Basis-Spielquelle fehlt"]
    else:
        mods = [mod for mod in status["mods"] if
                (str(mod["workshop_id"]), mod["directory"]) ==
                (str(draft.get("workshop_id")), draft.get("directory"))]
        if not mods:
            return None
        if len(mods) != 1:
            return [f"{path.name}: Quellmod nicht eindeutig gefunden"]
        mod = mods[0]
    errors = []
    if mod["counts"].get("parse_errors", 0):
        errors.append(f"{path.name}: Parserfehler in der Quelle")
    if draft.get("game_version") != status["game_version"]:
        errors.append(f"{path.name}: Spielversion geändert")
    if not is_game and draft.get("effective_layers") != mod["effective_layers"]:
        errors.append(f"{path.name}: effektive Schichten geändert")
    current = index_entries(mod["english"])
    needed = set(index_entries(mod["missing"] + mod["blank"]))
    stored = {entry_identity(e) for e in draft["entries"] if translation_state(e, language)["needed"] is True}
    excluded = {entry_identity(e) for e in draft["entries"]
                if not is_game and translation_state(e, language)["needed"] is False
                and translation_state(e, language).get("reviewed", 0) == 1}
    audits = {}
    if is_game:
        try:
            audits = index_audits(mod, language)
        except ValueError as exc:
            return errors + [f"{path.name}: {exc}"]
        stored_audit = {entry_identity(e): translation_state(e, language)["audit"]
                        for e in draft["entries"] if translation_state(e, language).get("audit") in AUDIT_TYPES}
        for ident in sorted(audits.keys() - stored_audit.keys()):
            errors.append(f"{path.name}: neuer Audit-Kandidat fehlt im Draft: {ident}")
        for ident in sorted(stored_audit.keys() - audits.keys()):
            errors.append(f"{path.name}: veraltetes {stored_audit[ident]}-Audit: {ident}")
        for ident in sorted(audits.keys() & stored_audit.keys()):
            if audits[ident] != stored_audit[ident]:
                errors.append(f"{path.name}: falscher Audittyp: {ident}; "
                              f"{stored_audit[ident]} statt {audits[ident]}")
    for ident in sorted(needed - stored - excluded):
        errors.append(f"{path.name}: neuer offener Quell-Key fehlt im Draft: {ident}")
    for ident in sorted(stored - needed - audits.keys()):
        errors.append(f"{path.name}: Key nicht mehr benötigt: {ident}")
    for entry in draft["entries"]:
        source = current.get(entry_identity(entry))
        if source and source["text"] != entry["english"]:
            errors.append(f"{path.name}: englischer Quelltext geändert: {entry_identity(entry)}")
    return errors


def run(language=None):
    from pzgt import scan_data

    drafts = load_drafts()
    languages = config.selected_languages(language)
    supported = {(str(draft.get("workshop_id")), draft.get("directory")) for _, draft in drafts
                 if draft.get("source_type") != "game"}
    include_game = any(draft.get("source_type") == "game" for _, draft in drafts)
    scan = scan_data(supported=supported, include_game=include_game)
    errors = []
    for target in languages:
        status = status_script.analyze_scan(scan, target)
        totals = Counter()
        source_totals = Counter()
        target_errors = []
        for path, draft in drafts:
            summary = draft_state(path, draft, target)
            totals.update({key: summary[key] for key in
                           ("needed", "translated", "open", "review", "unknown", "complete")})
            sync_errors = source_errors(path, draft, status, target)
            if sync_errors is None:
                source_totals["missing"] += 1
                print(f"Source-Sync {target}: {path.name}: Quelle lokal nicht vorhanden / nicht aktuell prüfbar")
            else:
                source_totals["checked"] += 1
                source_totals["different"] += bool(sync_errors)
                target_errors.extend(sync_errors)
            for entry in draft["entries"]:
                state = translation_state(entry, target)
                if state["needed"] is not True:
                    continue
                if state["review"]:
                    target_errors.append(f"{path.name}: Review offen: {entry['key']}")
                if state["text"].strip() and placeholders(entry["english"]) != placeholders(state["text"]):
                    target_errors.append(f"{path.name}: Placeholder-Abweichung: {entry['key']}")
        try:
            expected, included, _ = collect_expected(drafts, target)
            runtime = runtime_errors(expected, config.TRANSLATE / target)
            target_errors.extend(runtime)
            print(f"Runtime {target}: {len(expected)} erwartet | "
                  f"{len(read_tree(config.TRANSLATE / target))} vorhanden | {len(runtime)} Abweichungen")
        except (OSError, ValueError) as exc:
            target_errors.append(str(exc))
        print(f"Drafts {target}: {len(drafts)} | Build-fertig: {totals['complete']} | "
              f"Unvollständig: {len(drafts) - totals['complete']} | Benötigt: {totals['needed']} | "
              f"Übersetzt: {totals['translated']} | Offen: {totals['open']} | "
              f"Review: {totals['review']} | Unbekannt: {totals['unknown']}")
        errors.extend(f"{target}: {message}" for message in target_errors)
        print(f"Source-Sync {target}: geprüft: {source_totals['checked']} | "
              f"Quelle nicht lokal: {source_totals['missing']} | Abweichend: {source_totals['different']}")
    errors.extend(mod_info_errors())
    if errors:
        raise ValueError("\n".join(errors) + "\nQuellen: ./pzgt scan, status --language CODE, draft --all; Runtime: ./pzgt build")
    print("Ergebnis: OK")


if __name__ == "__main__":
    config.configure()
    run()
