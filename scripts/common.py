"""Shared draft validation, language states and safe local writes."""
from collections import Counter
from copy import deepcopy
import re
from pathlib import Path, PureWindowsPath
import json
import os
import tempfile

import config

PLACEHOLDER_RE = re.compile(
    r"""
    %\d+                       # PZ: %1, %2 ...
    |
    %(?!%)[#0\- +']*
    (?:\d+|\*)?
    (?:\.(?:\d+|\*))?
    [a-zA-Z](?![A-Za-z0-9_])  # printf-artig: %s, %d ..., aber kein "100%ig"
    |
    \{[A-Za-z0-9_.:-]+\}       # {0}, {name}
    """,
    re.VERBOSE,
)


def placeholders(text):
    return Counter(
        match.group(0)
        for match in PLACEHOLDER_RE.finditer(text)
    )


LEGACY_FIELDS = ("german", "needed", "review", "previous_english")
AUDIT_TYPES = ("blank_target", "same_as_source")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Doppeltes JSON-Feld: {key}")
        result[key] = value
    return result


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc


def no_symlinks(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f"Symlink im Ausgabepfad: {part}")


def write_json(path, data):
    no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink()
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def safe_relative(value):
    if (not isinstance(value, str) or not value or "\\" in value
            or PureWindowsPath(value).drive or Path(value).is_absolute()
            or any(p in ("", ".", "..") for p in value.split("/"))
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError(f"Unsicherer Runtime-Pfad: {value!r}")
    return Path(value)


def entry_identity(entry):
    if not isinstance(entry, dict):
        raise ValueError("Eintrag muss ein Objekt sein")
    for field in ("category", "key"):
        if not isinstance(entry.get(field), str) or not entry[field]:
            raise ValueError(f"Ungültige Eintragsidentität: {field}")
    return entry["category"], entry["key"]


def index_entries(entries):
    result = {}
    for entry in entries:
        ident = entry_identity(entry)
        if ident in result:
            raise ValueError(f"Doppelter Draft-/Work-Eintrag: {ident}")
        result[ident] = entry
    return result


def index_audits(source, language):
    fields = {"blank_target": "audit_blank", "same_as_source": "audit_same_as_source"}
    if any(not isinstance(source.get(field), list) for field in fields.values()):
        raise ValueError("Status ohne Vanilla-Auditbestand; ./pzgt scan und "
                         f"./pzgt status --language {language} erneut ausführen")

    result = {}
    for audit_type, field in fields.items():
        for ident in index_entries(source[field]):
            if ident in result:
                raise ValueError(
                    f"Vanilla-Auditbestand überschneidet sich: {ident}; "
                    f"{result[ident]} / {audit_type}"
                )
            result[ident] = audit_type
    return result


def validate_draft(path, draft):
    if not isinstance(draft, dict) or not isinstance(draft.get("entries"), list):
        raise ValueError(f"{path}: entries muss eine Liste sein")
    index_entries(draft["entries"])
    for entry in draft["entries"]:
        if not isinstance(entry.get("english"), str):
            raise ValueError(f"{path}: english muss String sein")
        if any(field in entry for field in LEGACY_FIELDS):
            raise ValueError(f"{path}: altes/gemischtes Draft-Format; './pzgt draft --all' ausführen")
        safe_relative(entry["key"] if entry["category"] == "__plain__" else entry["category"] + ".json")
        states = entry.get("translations")
        if not isinstance(states, dict) or not states:
            raise ValueError(f"{path}: translations fehlt")
        config.validate_languages(list(states))
        for language, state in states.items():
            if (not isinstance(state, dict) or not isinstance(state.get("text"), str)
                    or type(state.get("review")) is not bool or "needed" not in state
                    or (state["needed"] is not None and type(state["needed"]) is not bool)):
                raise ValueError(f"{path}: ungültiger Translation-State für {language}")
            if "previous_english" in state and not isinstance(state["previous_english"], str):
                raise ValueError(f"{path}: previous_english muss String sein ({language})")
            if "audit" in state:
                if state["audit"] not in AUDIT_TYPES:
                    raise ValueError(
                        f"{path}: ungültiges audit für {language}; "
                        f"erwartet {', '.join(AUDIT_TYPES)}"
                    )
                if draft.get("source_type") != "game":
                    raise ValueError(
                        f"{path}: audit ist nur für Basis-Spiel-Drafts erlaubt ({language})"
                    )


def migrate_draft(draft):
    result = deepcopy(draft)
    if not isinstance(result, dict) or not isinstance(result.get("entries"), list):
        raise ValueError("Ungültiger Draft")
    formats = set()
    for entry in result["entries"]:
        entry_identity(entry)
        legacy = any(field in entry for field in LEGACY_FIELDS)
        if legacy and "translations" in entry:
            raise ValueError("Gemischtes altes/neues Draft-Format")
        formats.add("legacy" if legacy else "generic")
        if legacy:
            if (not isinstance(entry.get("german"), str)
                    or type(entry.get("needed")) is not bool
                    or type(entry.get("review")) is not bool):
                raise ValueError("Ungültiger alter deutscher Translation-State")
            state = {"text": entry.pop("german"), "needed": entry.pop("needed"),
                     "review": entry.pop("review")}
            if "previous_english" in entry:
                state["previous_english"] = entry.pop("previous_english")
            entry["translations"] = {"DE": state}
    if len(formats) > 1:
        raise ValueError("Gemischte Eintragsformate im Draft")
    return result


def load_drafts(migrate=False):
    no_symlinks(config.TRANSLATIONS)
    result = []
    for path in sorted(config.TRANSLATIONS.glob("*.json")):
        no_symlinks(path)
        draft = load_json(path)
        if migrate:
            draft = migrate_draft(draft)
        validate_draft(path, draft)
        result.append((path, draft))
    return result


def translation_state(entry, language):
    return entry["translations"].get(language, {"text": "", "needed": None, "review": False})


def require_known(draft, language):
    if any(translation_state(e, language)["needed"] is None for e in draft["entries"]):
        raise ValueError(f"{draft.get('mod_id') or draft.get('name') or 'Draft'} ({language}): Übersetzungsbedarf unbekannt; "
                         f"'./pzgt scan', './pzgt status --language {language}' und "
                         "'./pzgt draft --all' ausführen")


def matches(draft, selector):
    return any(isinstance(value, str) and value.casefold() == selector.casefold()
               for value in (draft.get("mod_id"), draft.get("directory"), draft.get("name")))


def select_draft(drafts, selector):
    found = [item for item in drafts if matches(item[1], selector)]
    if len(found) != 1:
        raise ValueError(f"Kein eindeutiger Draft: {selector}")
    return found[0]


def read_tree(directory):
    no_symlinks(directory)
    result = {}
    if directory.exists() and not directory.is_dir():
        raise ValueError(f"Kein Verzeichnis: {directory}")
    for path in sorted(directory.rglob("*")):
        no_symlinks(path)
        if path.is_file():
            result[path.relative_to(directory)] = path.read_bytes()
        elif not path.is_dir():
            raise ValueError(f"Keine reguläre Datei: {path}")
    return result


def replace_outputs(outputs):
    """Stage all files/trees, then exchange them together with rollback on failure."""
    import shutil

    for target, content in outputs.items():
        no_symlinks(target)
        if isinstance(content, dict):
            read_tree(target)
        elif target.exists() and not target.is_file():
            raise ValueError(f"Keine reguläre Datei: {target}")
    no_symlinks(config.ROOT)
    stage = Path(tempfile.mkdtemp(prefix=".pzgt-stage-", dir=config.ROOT))
    previous = []
    installed = []
    rollback_failed = False
    try:
        for number, (target, content) in enumerate(outputs.items()):
            output = stage / str(number)
            if isinstance(content, dict):
                output.mkdir()
                for rel, value in content.items():
                    path = output / safe_relative(str(rel))
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(value)
            else:
                output.write_bytes(content)
        try:
            for number, target in enumerate(outputs):
                target.parent.mkdir(parents=True, exist_ok=True)
                backup = stage / f"previous-{number}"
                if target.exists():
                    target.rename(backup)
                    previous.append((target, backup))
                (stage / str(number)).rename(target)
                installed.append(target)
        except BaseException:
            try:
                for target in reversed(installed):
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                for target, backup in reversed(previous):
                    backup.rename(target)
            except BaseException:
                rollback_failed = True
                raise
            raise
    finally:
        if not rollback_failed:
            shutil.rmtree(stage)
