#!/usr/bin/env python3
"""Export only a verified distribution; never rebuild the runtime implicitly."""
from io import BytesIO
from pathlib import Path
import zipfile

import config
from build import collect_expected, expected_mod_info
from common import load_drafts, no_symlinks, replace_outputs
from verify import mod_info_errors, runtime_errors

MOD_DIRECTORY = "Project-Zomboid-Mod-Translations"


def supported_mods_text(drafts, plans, languages):
    by_path = dict(drafts)
    supported = {}
    game_languages = set()

    for language in languages:
        _, included, _ = plans[language]

        for path in included:
            if by_path[path].get("source_type") == "game":
                game_languages.add(language)
                continue
            supported.setdefault(path, []).append(language)

    rows = []

    for path, target_languages in supported.items():
        draft = by_path[path]

        name = (
            draft.get("name")
            or draft.get("mod_id")
            or draft.get("directory")
            or path.stem
        )
        workshop_id = str(draft.get("workshop_id") or "")
        mod_id = str(draft.get("mod_id") or "")

        rows.append(
            (
                name.casefold(),
                workshop_id,
                mod_id.casefold(),
                path.name.casefold(),
                name,
                workshop_id,
                mod_id,
                target_languages,
            )
        )

    lines = [
        "Project Zomboid Mod Translations",
        "Supported Mods",
        "",
        f"Languages: {', '.join(languages)}",
        f"Supported mods: {len(rows)}",
        *([f"Base game translations: included ({', '.join(sorted(game_languages))})"]
          if game_languages else []),
        "",
        "This export contains complete translations for the following mods:",
        "",
    ]

    for (
        _,
        _,
        _,
        _,
        name,
        workshop_id,
        mod_id,
        target_languages,
    ) in sorted(rows):
        lines.append(name)

        if workshop_id:
            lines.append(f"  Workshop ID: {workshop_id}")
            lines.append(
                "  Workshop: "
                "https://steamcommunity.com/sharedfiles/filedetails/"
                f"?id={workshop_id}"
            )

        if mod_id:
            lines.append(f"  Mod ID: {mod_id}")

        languages_text = ", ".join(
            sorted(target_languages, key=str.casefold)
        )
        lines.append(f"  Languages: {languages_text}")
        lines.append("")

    return (
        "\n".join(lines).rstrip() + "\n"
    ).encode("utf-8")


def run(language=None, make_zip=False):
    drafts = load_drafts()
    languages = config.selected_languages(language)
    plans = {target: collect_expected(drafts, target) for target in languages}
    errors = mod_info_errors()
    for target, (expected, _, _) in plans.items():
        errors.extend(f"{target}: {error}" for error in runtime_errors(expected, config.TRANSLATE / target))
    if errors:
        raise ValueError("Runtime nicht exportierbar; './pzgt build' ausführen.\n" + "\n".join(errors))
    license_file = config.ROOT / "LICENSE"
    no_symlinks(license_file)
    readme_file = config.ROOT / "export/README-DIST.md"
    no_symlinks(readme_file)
    if not readme_file.is_file():
        raise ValueError(f"Pflichtdatei für Distribution-README fehlt: {readme_file}")
    if len(languages) == 1:
        localized = readme_file.with_name(f"README-DIST-{languages[0]}.md")
        no_symlinks(localized)
        if localized.is_file():
            readme_file = localized
    files = {Path("LICENSE"): license_file.read_bytes(),
             Path("README.md"): readme_file.read_bytes(),
             Path("SUPPORTED-MODS.txt"): supported_mods_text(drafts, plans, languages),
             Path("common/mod.info"): expected_mod_info(), Path("42/mod.info"): expected_mod_info()}
    for target, (expected, _, _) in plans.items():
        files.update({Path("common/media/lua/shared/Translate") / target / rel: content
                      for rel, content in expected.items()})
    dist = config.ROOT / "dist"
    outputs = {dist / MOD_DIRECTORY: files}
    if make_zip:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for rel, content in sorted(files.items()):
                info = zipfile.ZipInfo(f"{MOD_DIRECTORY}/{rel.as_posix()}")
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, content)
        outputs[dist / (MOD_DIRECTORY + ".zip")] = buffer.getvalue()
    replace_outputs(outputs)
    print(f"Export {', '.join(languages)}: OK | {dist / MOD_DIRECTORY}")
    if make_zip:
        print(f"ZIP: {dist / (MOD_DIRECTORY + '.zip')}")


if __name__ == "__main__":
    config.configure()
    run()
