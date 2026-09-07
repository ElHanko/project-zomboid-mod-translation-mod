#!/usr/bin/env python3
"""Count only the selected target-language state."""
import config
from common import load_drafts, select_draft, translation_state, placeholders


def state(path, data, language):
    states = [translation_state(e, language) for e in data["entries"]]
    needed = [s for s in states if s["needed"] is True]
    translated = sum(bool(s["text"].strip()) for s in needed)
    review = sum(s["review"] for s in needed)
    unknown = sum(s["needed"] is None for s in states)
    valid_placeholders = all(placeholders(e["english"]) == placeholders(translation_state(e, language)["text"])
                             for e in data["entries"] if translation_state(e, language)["needed"] is True)
    return {"path": path, "data": data, "needed": len(needed), "translated": translated,
            "open": len(needed) - translated, "review": review, "unknown": unknown,
            "complete": bool(needed) and len(needed) == translated and not review and not unknown and valid_placeholders}


def run(selector=None, language=None):
    language = config.select_language(language)
    drafts = load_drafts()
    if selector:
        drafts = [select_draft(drafts, selector)]
    if not drafts:
        raise ValueError("Keine Drafts vorhanden")
    items = [state(path, data, language) for path, data in drafts]
    print(f"Fortschritt {language}")
    print(f"{'OFFEN':>6} {'ÜBERSETZT':>9} {'GESAMT':>6} {'REV':>5} {'UNBEKANNT':>9}  MOD-ID")
    for item in sorted(items, key=lambda item: (-item["open"], str(item["path"]))):
        print(f"{item['open']:6} {item['translated']:9} {item['needed']:6} {item['review']:5} "
              f"{item['unknown']:9}  {item['data'].get('mod_id') or item['data'].get('name') or item['path'].name}")
    print(f"\nDrafts:       {len(items)}")
    print(f"Fertig:       {sum(item['complete'] for item in items)}")
    for key, label in (("needed", "Benötigt"), ("translated", "Übersetzt"), ("open", "Offen"),
                       ("review", "Review"), ("unknown", "Unbekannt")):
        print(f"{label + ':':14}{sum(item[key] for item in items)}")


if __name__ == "__main__":
    config.configure()
    run()
