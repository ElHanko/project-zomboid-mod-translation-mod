"""Local paths and native Project Zomboid language directory names."""
from pathlib import Path
import json
import unicodedata

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TRANSLATIONS = ROOT / "translations"
TRANSLATE = ROOT / "common/media/lua/shared/Translate"
LANGUAGES = ["DE"]


def validate_languages(languages):
    if not isinstance(languages, list) or not languages:
        raise ValueError("languages muss eine nichtleere Liste sein")
    seen = set()
    for name in languages:
        if (not isinstance(name, str) or not name or name != name.strip()
                or name in (".", "..") or any(c in name for c in '/\\:')
                or any(unicodedata.category(c).startswith("C") for c in name)):
            raise ValueError(f"Ungültiger Sprach-/Verzeichnisname: {name!r}")
        if name.casefold() in seen:
            raise ValueError(f"Doppelte Sprache: {name}")
        seen.add(name.casefold())
    return languages


def load_config(path=None):
    path = path or ROOT / "pzgt.local.json"
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            raise ValueError("JSON-Wurzel muss ein Objekt sein")
        result = {}
        for key in ("game", "workshop", "zomboid_home"):
            value = values.get(key)
            if not isinstance(value, str) or not value.strip() or "\0" in value:
                raise ValueError(f"Ungültiger Pflichtwert: {key}")
            result[key] = Path(value).expanduser()
        result["languages"] = validate_languages(values.get("languages", ["DE"]))
        return result
    except (OSError, ValueError) as exc:
        raise ValueError(f"Konfiguration {path}: {exc}") from exc


def configure():
    global LANGUAGES
    values = load_config()
    LANGUAGES = values["languages"]
    return values


def select_language(language=None):
    if language is None:
        if len(LANGUAGES) != 1:
            raise ValueError("Mehrere Zielsprachen konfiguriert; --language angeben")
        return LANGUAGES[0]
    if language not in LANGUAGES:
        raise ValueError(f"Sprache nicht konfiguriert: {language!r}")
    return language


def selected_languages(language=None):
    return [select_language(language)] if language is not None else list(LANGUAGES)
