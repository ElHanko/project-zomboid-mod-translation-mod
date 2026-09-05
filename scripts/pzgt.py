#!/usr/bin/env python3

from pathlib import Path
import json
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TRANSLATIONS = ROOT / "translations"

LOCAL_MODS = Path.home() / "Zomboid" / "mods"
LOCAL_LINK = LOCAL_MODS / "ElHanko-German-Translations"
CONFIG_FILE = ROOT / "pzgt.local.json"

VERSION_DIR_RE = re.compile(r"^\d+(?:\.\d+){0,2}$")
GAME_VERSION_RE = re.compile(
    r">\s+version=(\d+(?:\.\d+)+)\b"
)


def die(message):
    print(f"FEHLER: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_config():
    if not CONFIG_FILE.exists():
        die(f"Lokale Konfiguration fehlt: {CONFIG_FILE}")

    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        die(f"Konfiguration kann nicht gelesen werden: {exc}")

    required = ("game", "workshop", "zomboid_home")

    for key in required:
        if not config.get(key):
            die(f"Konfiguration enthält keinen Wert für {key!r}")

    return {
        key: Path(config[key]).expanduser()
        for key in required
    }


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
    en_files = language_files(path, "EN")
    de_files = language_files(path, "DE")

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
            "EN": en_files,
            "DE": de_files,
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


def discover_mods(workshop):
    mods = []

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
    en = len(layer["translations"]["EN"])
    de = len(layer["translations"]["DE"])

    if en and de:
        state = f"EN:{en}/DE:{de}"
    elif en:
        state = f"EN:{en}"
    elif de:
        state = f"DE:{de}"
    else:
        state = "-"

    return f"{layer['name']}[{state}]"


def cmd_scan():
    config = load_config()
    game_version = detect_game_version(config)

    mods = discover_mods(config["workshop"])

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

    DATA.mkdir(parents=True, exist_ok=True)

    output = DATA / "scan.json"

    payload = {
        "game": str(config["game"]),
        "game_version": game_version,
        "workshop": str(config["workshop"]),
        "zomboid_home": str(config["zomboid_home"]),
        "mods": mods,
    }

    output.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    workshop_ids = {
        mod["workshop_id"]
        for mod in mods
    }

    with_translations = [
        mod
        for mod in mods
        if any(
            layer["translations"]["EN"]
            or layer["translations"]["DE"]
            for layer in mod["layers"]
        )
    ]

    print("Project Zomboid Mod-Inventur")
    print()
    print(f"Spielversion:   {game_version}")
    print(f"Workshop:       {config['workshop']}")
    print(f"Workshop-Items: {len(workshop_ids)}")
    print(f"Mod-Verzeichn.: {len(mods)}")
    print(f"Mit Sprache:    {len(with_translations)}")
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
            layer["translations"]["EN"]
            or layer["translations"]["DE"]
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



def cmd_status():
    script = ROOT / "scripts" / "status.py"

    subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        check=True,
    )


def cmd_draft(selector):
    script = ROOT / "scripts" / "draft.py"

    subprocess.run(
        [
            sys.executable,
            str(script),
            selector,
        ],
        cwd=ROOT,
        check=True,
    )



def cmd_progress(selector=None):
    script = ROOT / "scripts" / "progress.py"

    command = [
        sys.executable,
        str(script),
    ]

    if selector is not None:
        command.append(selector)

    subprocess.run(
        command,
        cwd=ROOT,
        check=True,
    )



def cmd_build(selector):
    script = ROOT / "scripts" / "build.py"

    subprocess.run(
        [
            sys.executable,
            str(script),
            selector,
        ],
        cwd=ROOT,
        check=True,
    )



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



def cmd_verify():
    script = ROOT / "scripts" / "verify.py"

    subprocess.run(
        [
            sys.executable,
            str(script),
        ],
        cwd=ROOT,
        check=True,
    )



def cmd_work(args):
    script = ROOT / "scripts" / "work.py"

    subprocess.run(
        [
            sys.executable,
            str(script),
            *args,
        ],
        cwd=ROOT,
        check=True,
    )


def cmd_apply(work_file):
    script = ROOT / "scripts" / "apply.py"

    subprocess.run(
        [
            sys.executable,
            str(script),
            work_file,
        ],
        cwd=ROOT,
        check=True,
    )


def usage():
    print(
        "Verwendung:\n"
        "  ./pzgt scan\n"
        "  ./pzgt status\n"
        "  ./pzgt draft MOD-ID\n"
        "  ./pzgt progress\n"
        "  ./pzgt progress MOD-ID\n"
        "  ./pzgt build MOD-ID\n"
        "  ./pzgt install\n"
        "  ./pzgt verify\n"
        "  ./pzgt work [MOD-ID|--next] [--limit N] [--offset N]\n"
        "  ./pzgt apply WORK-DATEI\n"
    )


def main():
    if len(sys.argv) < 2:
        usage()
        return 1

    command = sys.argv[1]

    if command == "scan":
        if len(sys.argv) != 2:
            usage()
            return 1

        cmd_scan()
        return 0

    if command == "status":
        if len(sys.argv) != 2:
            usage()
            return 1

        cmd_status()
        return 0

    if command == "draft":
        if len(sys.argv) != 3:
            usage()
            return 1

        cmd_draft(sys.argv[2])
        return 0

    if command == "progress":
        if len(sys.argv) == 2:
            cmd_progress()
            return 0

        if len(sys.argv) == 3:
            cmd_progress(sys.argv[2])
            return 0

        usage()
        return 1

    if command == "build":
        if len(sys.argv) != 3:
            usage()
            return 1

        cmd_build(sys.argv[2])
        return 0

    if command == "install":
        if len(sys.argv) != 2:
            usage()
            return 1

        cmd_install()
        return 0

    if command == "verify":
        if len(sys.argv) != 2:
            usage()
            return 1

        cmd_verify()
        return 0

    if command == "work":
        cmd_work(sys.argv[2:])
        return 0

    if command == "apply":
        if len(sys.argv) != 3:
            usage()
            return 1

        cmd_apply(sys.argv[2])
        return 0

    if command in ("help", "--help", "-h"):
        usage()
        return 0

    die(f"Unbekannter Befehl: {command}")


if __name__ == "__main__":
    sys.exit(main())
