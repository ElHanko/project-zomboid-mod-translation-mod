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
    files = {Path("LICENSE"): license_file.read_bytes(),
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
