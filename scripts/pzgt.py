#!/usr/bin/env python3

from pathlib import Path
import re
import argparse
import importlib

import config as settings
import sys
from common import AUDIT_TYPES, write_json


ROOT = Path(__file__).resolve().parent.parent

LOCAL_MODS = Path.home() / "Zomboid" / "mods"
LOCAL_LINK = LOCAL_MODS / "ElHanko-German-Translations"

VERSION_DIR_RE = re.compile(r"^\d+(?:\.\d+){0,2}$")
GAME_VERSION_RE = re.compile(
    r">\s+version=(\d+(?:\.\d+)+)\b"
)


def die(message):
    print(f"FEHLER: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_config():
    return settings.load_config()


def version_tuple(value):
    parts = tuple(int(part) for part in value.split("."))
    return parts + (0,) * (3 - len(parts))


def detect_game_version(config):
    console = config["zomboid_home"] / "console.txt"

    if not console.is_file():
        die(f"console.txt fehlt: {console}")

    content = console.read_text(
        encoding="utf-8",
        errors="replace",
    )

    match = GAME_VERSION_RE.search(content)

    if not match:
        die(
            "Project-Zomboid-Version konnte aus "
            f"{console} nicht bestimmt werden."
        )

    return match.group(1)


def select_effective_layers(layers, game_version):
    game = version_tuple(game_version)
    game_major = game[0]

    common = next(
        (
            layer
            for layer in layers
            if layer["kind"] == "common"
        ),
        None,
    )

    compatible = []

    for layer in layers:
        if layer["kind"] != "version":
            continue

        version = version_tuple(layer["name"])

        # B42 lädt keine B41-Payloads als Fallback.
        if version[0] != game_major:
            continue

        if version <= game:
            compatible.append((version, layer))

    selected = (
        max(compatible, key=lambda item: item[0])[1]
        if compatible
        else None
    )

    effective = []

    if common is not None:
        effective.append(common)

    if selected is not None:
        effective.append(selected)

    return effective, selected


def parse_mod_info(path):
    result = {}

    if not path.is_file():
        return result

    try:
        lines = path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except OSError:
        return result

    for raw_line in lines:
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()

    return result


def translation_directory(layer):
    return (
        layer
        / "media"
        / "lua"
        / "shared"
        / "Translate"
    )


def language_files(layer, language):
    directory = translation_directory(layer) / language

    if not directory.is_dir():
        return []

    result = []

    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue

        result.append(
            {
                "path": str(path.relative_to(directory)),
                "suffix": path.suffix.lower(),
                "size": path.stat().st_size,
            }
        )

    return result


def inspect_layer(path, name, kind):
    mod_info_path = path / "mod.info"

    return {
        "name": name,
        "kind": kind,
        "path": str(path),
        "mod_info_path": (
            str(mod_info_path)
            if mod_info_path.is_file()
            else None
        ),
        "mod_info": parse_mod_info(mod_info_path),
        "translations": {
            language: language_files(path, language)
            for language in dict.fromkeys(["EN", *settings.LANGUAGES])
        },
    }


def discover_layers(mod_root):
    layers = []

    # Root: wichtig zur Bestandsaufnahme von B41-/Legacy-Inhalten.
    root_has_content = (
        (mod_root / "mod.info").is_file()
        or translation_directory(mod_root).is_dir()
    )

    if root_has_content:
        layers.append(
            inspect_layer(
                mod_root,
                "root",
                "legacy-root",
            )
        )

    common = mod_root / "common"

    if common.is_dir():
        layers.append(
            inspect_layer(
                common,
                "common",
                "common",
            )
        )

    version_dirs = [
        path
        for path in mod_root.iterdir()
        if (
            path.is_dir()
            and VERSION_DIR_RE.fullmatch(path.name)
        )
    ]

    def version_key(path):
        return tuple(
            int(part)
            for part in path.name.split(".")
        )

    for path in sorted(version_dirs, key=version_key):
        layers.append(
            inspect_layer(
                path,
                path.name,
                "version",
            )
        )

    return layers


def discover_mods(workshop, supported=None):
    mods = []

    if supported is not None and not workshop.exists():
        return mods

    if not workshop.is_dir():
        die(f"Workshop-Verzeichnis fehlt: {workshop}")

    for workshop_root in sorted(workshop.iterdir()):
        if not workshop_root.is_dir():
            continue

        if not workshop_root.name.isdigit():
            continue

        mods_dir = workshop_root / "mods"

        if not mods_dir.is_dir():
            continue

        for mod_root in sorted(mods_dir.iterdir()):
            if supported is not None and (workshop_root.name, mod_root.name) not in supported:
                continue
            if not mod_root.is_dir():
                continue

            layers = discover_layers(mod_root)

            mod_infos = [
                layer["mod_info"]
                for layer in layers
                if layer["mod_info"]
            ]

            ids = sorted(
                {
                    info["id"]
                    for info in mod_infos
                    if info.get("id")
                }
            )

            names = sorted(
                {
                    info["name"]
                    for info in mod_infos
                    if info.get("name")
                }
            )

            mods.append(
                {
                    "workshop_id": workshop_root.name,
                    "directory": mod_root.name,
                    "path": str(mod_root),
                    "ids": ids,
                    "names": names,
                    "layers": layers,
                }
            )

    return mods


def layer_translation_marker(layer):
    state = "/".join(f"{language}:{len(files)}" for language, files in layer["translations"].items() if files) or "-"
    return f"{layer['name']}[{state}]"


def scan_data(config=None, supported=None, include_game=None):
    config = config or load_config()
    if include_game is None:
        include_game = supported is None
    base_game = None
    if include_game:
        game_root = config["game"] / "projectzomboid"
        translate = translation_directory(game_root)
        if not translate.is_dir() or not (translate / "EN").is_dir():
            raise ValueError(f"Project Zomboid: Vanilla-Translate-Root mit EN fehlt: {translate}; "
                             "konfigurierten game-Pfad prüfen")
        base_game = {"source_type": "game", "name": "Project Zomboid",
                     "effective_layers": ["game"],
                     "layers": [inspect_layer(game_root, "game", "game")]}
    mods = discover_mods(config["workshop"], supported)
    # Without installed supported sources, local reproducibility needs no game log.
    game_version = detect_game_version(config) if supported is None or mods or include_game else None

    for mod in mods:
        effective, selected = select_effective_layers(
            mod["layers"],
            game_version,
        )

        mod["effective_layers"] = [
            layer["name"]
            for layer in effective
        ]

        mod["effective_version"] = (
            selected["name"]
            if selected is not None
            else None
        )

        info_sources = list(reversed(effective))

        effective_info = next(
            (
                layer["mod_info"]
                for layer in info_sources
                if layer["mod_info"]
            ),
            {},
        )

        mod["effective_id"] = effective_info.get("id")
        mod["effective_name"] = effective_info.get("name")

    return {
        "game": str(config["game"]),
        "game_version": game_version,
        "workshop": str(config["workshop"]),
        "zomboid_home": str(config["zomboid_home"]),
        "languages": list(settings.LANGUAGES),
        "mods": mods,
        **({"base_game": base_game} if include_game else {}),
    }


def cmd_scan():
    payload = scan_data()
    mods = payload["mods"]
    game_version = payload["game_version"]
    output = settings.DATA / "scan.json"
    write_json(output, payload)
    workshop_ids = {
        mod["workshop_id"]
        for mod in mods
    }

    with_translations = [
        mod
        for mod in mods
        if any(
            any(layer["translations"].values())
            for layer in mod["layers"]
        )
    ]

    print("Project Zomboid Mod-Inventur")
    print()
    print(f"Spielversion:   {game_version}")
    print(f"Workshop:       {payload['workshop']}")
    print(f"Workshop-Items: {len(workshop_ids)}")
    print(f"Mod-Verzeichn.: {len(mods)}")
    print(f"Mit Sprache:    {len(with_translations)}")
    print("Hauptspiel:     Project Zomboid | " + " ".join(
        layer_translation_marker(layer) for layer in payload["base_game"]["layers"]))
    print()

    print(
        f"{'WORKSHOP':12} "
        f"{'MOD-ID':32} "
        f"{'VERZEICHNIS':35} "
        "SCHICHTEN"
    )
    print("-" * 125)

    for mod in mods:
        if not any(
            any(layer["translations"].values())
            for layer in mod["layers"]
        ):
            continue

        mod_id = (
            ",".join(mod["ids"])
            if mod["ids"]
            else "-"
        )

        layers = " ".join(
            layer_translation_marker(layer)
            for layer in mod["layers"]
        )

        print(
            f"{mod['workshop_id']:12} "
            f"{mod_id[:32]:32} "
            f"{mod['directory'][:35]:35} "
            f"{layers}"
        )

    print()
    print(f"Vollständige Inventur: {output}")



def cmd_install():
    LOCAL_MODS.mkdir(
        parents=True,
        exist_ok=True,
    )

    expected = ROOT.resolve()

    if LOCAL_LINK.is_symlink():
        actual = LOCAL_LINK.resolve()

        if actual == expected:
            print(
                "Symlink bereits korrekt:\n"
                f"  {LOCAL_LINK}\n"
                f"  -> {actual}"
            )
            return

        die(
            f"{LOCAL_LINK} zeigt auf {actual}, "
            f"erwartet wird {expected}."
        )

    if LOCAL_LINK.exists():
        die(
            f"{LOCAL_LINK} existiert bereits "
            "und ist kein Symlink. "
            "Keine Änderung vorgenommen."
        )

    LOCAL_LINK.symlink_to(
        expected,
        target_is_directory=True,
    )

    print("Symlink angelegt:")
    print(f"  {LOCAL_LINK}")
    print(f"  -> {expected}")



def main(argv=None):
    parser = argparse.ArgumentParser(prog="./pzgt")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("scan", "status", "build", "verify", "install", "export", "progress", "work", "draft", "apply", "audit", "review"):
        command = commands.add_parser(name)
        if name in ("status", "build", "verify", "export", "progress", "work", "audit", "review"):
            command.add_argument("--language")
        if name in ("progress", "work", "build"):
            command.add_argument("selector", nargs="?")
        if name == "draft":
            group = command.add_mutually_exclusive_group(required=True)
            group.add_argument("selector", nargs="?")
            group.add_argument("--all", action="store_true")
        if name == "work":
            command.add_argument("--next", action="store_true")
            command.add_argument("--limit", type=int, default=25)
            command.add_argument("--offset", type=int, default=0)
        if name == "export":
            command.add_argument("--zip", action="store_true", dest="make_zip")
        if name == "apply":
            command.add_argument("file")
        if name in ("audit", "review"):
            command.add_argument("selector")
            command.add_argument("--category")
            command.add_argument("--type", dest="audit_type", choices=AUDIT_TYPES, required=name == "review")
        if name == "review":
            group = command.add_mutually_exclusive_group(required=True)
            group.add_argument("--need", action="store_true")
            group.add_argument("--not-needed", action="store_true")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["help"]:
        argv = ["--help"]
    args = parser.parse_args(argv)
    try:
        settings.configure()
        if args.command == "scan":
            cmd_scan()
        elif args.command == "install":
            cmd_install()
        else:
            module = importlib.import_module(args.command)
            if args.command == "draft":
                module.run("--all" if args.all else args.selector)
            elif args.command in ("progress", "build"):
                module.run(args.selector, args.language)
            elif args.command == "work":
                if args.next and args.selector:
                    raise ValueError("--next und MOD-ID schließen sich aus")
                module.run(args.selector, args.limit, args.offset, args.language)
            elif args.command == "apply":
                module.run(args.file)
            elif args.command == "export":
                module.run(args.language, args.make_zip)
            elif args.command == "audit":
                module.run(args.selector, args.language, args.category, args.audit_type)
            elif args.command == "review":
                module.run(args.selector, args.language, args.audit_type, args.category, needed=args.need)
            else:
                module.run(args.language)
    except (OSError, ValueError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
